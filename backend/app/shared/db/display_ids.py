"""Human display IDs per tenant: INC-1042, SR-77, CHG-208 (architecture.md §7.1; WP-005).

One counter row per (tenant, prefix) in `display_id_sequences`, advanced with a single atomic
upsert:

    INSERT ... VALUES (tenant, prefix, 1)
    ON CONFLICT (tenant_id, prefix) DO UPDATE SET last_value = last_value + 1
    RETURNING last_value

Behaviour (documented contract):
- No duplicates: the upsert takes a row lock, so concurrent callers in one tenant queue on that
  row and each gets the next number. Different tenants or prefixes never wait for each other.
- Runs in the caller's transaction: the number is reserved until that transaction ends. If it
  rolls back, the increment rolls back too, so rollbacks leave no gap; the next caller reuses the
  number. Gaps are still possible (e.g. a record created and later hard-deleted) and are allowed.
- The lock is held until the caller commits, so keep record-creating transactions short.
- The tenant always comes from the session context; RLS rejects any other tenant.

Work items (ADR-026) key their counter by *type* (`WI_INCIDENT`), not by the prefix an admin may
rename: `next_display_number` returns the bare number and the caller adds the current prefix, so
a renamed prefix continues the numbering and old IDs keep their old prefix.
"""

import re
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import SESSION_TENANT_KEY
from app.core.tenancy import TenantContext
from app.shared.db.models import Base

PREFIX_PATTERN = r"^[A-Z]{2,6}$"
_PREFIX = re.compile(PREFIX_PATTERN)
# Counter keys: a display prefix (ANN) or an internal key such as WI_INCIDENT.
KEY_PATTERN = r"^[A-Z][A-Z_]{1,39}$"
_KEY = re.compile(KEY_PATTERN)


class DisplayIdSequence(Base):
    """Per-tenant counter. Infrastructure, not an editable record: no version or soft delete."""

    __tablename__ = "display_id_sequences"
    __table_args__ = (
        CheckConstraint(f"prefix ~ '{KEY_PATTERN}'", name="prefix_format"),
        CheckConstraint("last_value > 0", name="last_value_positive"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    prefix: Mapped[str] = mapped_column(primary_key=True)
    last_value: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


def format_display_id(prefix: str, value: int) -> str:
    """`INC`, 1042 → `INC-1042`."""
    return f"{prefix}-{value}"


async def next_display_id(session: AsyncSession, prefix: str) -> str:
    """Reserve the next display ID for the session's tenant, e.g. `INC-1043`."""
    if not _PREFIX.fullmatch(prefix):
        msg = f"display ID prefix must be 2-6 capital letters, got {prefix!r}"
        raise ValueError(msg)
    return format_display_id(prefix, await _next_value(session, prefix))


async def next_display_number(session: AsyncSession, counter_key: str) -> int:
    """Reserve the next number of a named counter (e.g. `WI_INCIDENT`) for the session's tenant."""
    if not _KEY.fullmatch(counter_key):
        msg = f"counter key must match {KEY_PATTERN}, got {counter_key!r}"
        raise ValueError(msg)
    return await _next_value(session, counter_key)


async def _next_value(session: AsyncSession, key: str) -> int:
    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):
        msg = "next_display_id needs a tenant session"
        raise TypeError(msg)
    sequence = DisplayIdSequence
    statement = (
        insert(sequence)
        .values(tenant_id=context.tenant_id, prefix=key, last_value=1)
        .on_conflict_do_update(
            index_elements=[sequence.tenant_id, sequence.prefix],
            set_={"last_value": sequence.last_value + 1, "updated_at": func.now()},
        )
        .returning(sequence.last_value)
    )
    value = await session.scalar(statement)
    if value is None:  # pragma: no cover - RETURNING always yields a row for an upsert
        msg = "display ID upsert returned no row"
        raise RuntimeError(msg)
    return int(value)


async def last_number(session: AsyncSession, counter_key: str) -> int:
    """The last number a counter handed out in the session's tenant (0: none yet)."""
    value = await session.scalar(
        select(DisplayIdSequence.last_value).where(DisplayIdSequence.prefix == counter_key)
    )
    return int(value or 0)


class NumberAlreadyUsedError(ValueError):
    """The next number asked for is not above the last one handed out (REQ-ADM-045 AC3)."""


async def set_next_number(session: AsyncSession, counter_key: str, next_number: int) -> None:
    """Make the counter hand out `next_number` next; never backwards (IDs are never reused).

    Locks the counter row, so a create running at the same time either finishes first (and the
    check sees its number) or waits and gets the new number.
    """
    if not _KEY.fullmatch(counter_key):
        msg = f"counter key must match {KEY_PATTERN}, got {counter_key!r}"
        raise ValueError(msg)
    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):
        msg = "set_next_number needs a tenant session"
        raise TypeError(msg)
    current = await session.scalar(
        select(DisplayIdSequence.last_value)
        .where(DisplayIdSequence.prefix == counter_key)
        .with_for_update()
    )
    if next_number <= (current or 0):
        raise NumberAlreadyUsedError(next_number)
    if next_number == 1:
        return  # nothing handed out yet and the next is 1: already so
    if current is None:
        await session.execute(
            insert(DisplayIdSequence).values(
                tenant_id=context.tenant_id, prefix=counter_key, last_value=next_number - 1
            )
        )
        return
    await session.execute(
        update(DisplayIdSequence)
        .where(DisplayIdSequence.prefix == counter_key)
        .values(last_value=next_number - 1, updated_at=func.now())
    )
