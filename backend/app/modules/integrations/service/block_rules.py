"""Block rules for unwanted mail (WP-046a S6; REQ-INC-026).

Mail matching an enabled rule creates nothing and waits in the review queue as blocked, for the
mailbox's quarantine days (see inbound.py); an admin may release it, which then creates the
incident. The mailbox managers' right (`integrations.manage_email`) sets the rules; every change
is audited by the route and announced live (no address or text in the event).
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.integrations.domain.mailboxes import (
    BlockKind,
    block_rule_problems,
    normalised_rule_value,
)
from app.modules.integrations.events import MailBlockRuleChanged
from app.modules.integrations.infra.models import MailBlockRule
from app.shared.events import record_event

RULES_MAX = 500  # per tenant; a list longer than this belongs in the mail server's own filter

# Every field code the checks give (labels errors.field.<code>; tests/test_error_labels.py).
FIELD_PROBLEMS = frozenset({"required", "mailbox_address_invalid", "host_name_invalid"})


def _tenant(session: AsyncSession) -> uuid.UUID:
    from app.core.database import SESSION_TENANT_KEY  # noqa: PLC0415 - one use
    from app.core.tenancy import TenantContext  # noqa: PLC0415 - one use

    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):  # pragma: no cover - a tenant session always
        msg = "block rules live in a tenant session"
        raise TypeError(msg)
    return context.tenant_id


def _checked(kind: BlockKind, value: str) -> str:
    if problems := block_rule_problems(kind, value):
        raise ValidationFailed(
            errors=[
                FieldError(field=f"body.{name}", code=code, message_key=f"errors.field.{code}")
                for name, code in problems
            ]
        )
    return normalised_rule_value(kind, value)


async def _taken(
    session: AsyncSession, kind: BlockKind, value: str, but: uuid.UUID | None = None
) -> bool:
    query = select(MailBlockRule.id).where(
        MailBlockRule.deleted_at.is_(None),
        MailBlockRule.kind == kind.value,
        func.lower(MailBlockRule.value) == value.lower(),
    )
    if but is not None:
        query = query.where(MailBlockRule.id != but)
    return await session.scalar(query.limit(1)) is not None


Change = Literal["added", "changed", "removed"]


async def _announce(session: AsyncSession, row: MailBlockRule, change: Change) -> None:
    await record_event(
        session,
        MailBlockRuleChanged(rule_id=row.id, change=change),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def list_rules(session: AsyncSession) -> list[MailBlockRule]:
    """The tenant's rules, by kind and value."""
    rows = await session.scalars(
        select(MailBlockRule)
        .where(MailBlockRule.deleted_at.is_(None))
        .order_by(MailBlockRule.kind, func.lower(MailBlockRule.value))
    )
    return list(rows)


async def get_rule(session: AsyncSession, rule_id: uuid.UUID) -> MailBlockRule:
    """One rule (404 when removed or unknown)."""
    row = await session.get(MailBlockRule, rule_id)
    if row is None or row.deleted_at is not None:
        raise NotFound(code="mail_block_rule_not_found")
    return row


async def create_rule(
    session: AsyncSession, kind: BlockKind, value: str, *, enabled: bool = True
) -> MailBlockRule:
    """A new rule; the same kind and value twice is refused."""
    stored = _checked(kind, value)
    if await _taken(session, kind, stored):
        raise Conflict(code="mail_block_rule_exists")
    count = await session.scalar(
        select(func.count()).select_from(MailBlockRule).where(MailBlockRule.deleted_at.is_(None))
    )
    if (count or 0) >= RULES_MAX:
        raise Conflict(code="mail_block_rules_full", params={"max": RULES_MAX})
    row = MailBlockRule(
        tenant_id=_tenant(session), kind=kind.value, value=stored, enabled=enabled, version=1
    )
    session.add(row)
    await session.flush()
    await _announce(session, row, "added")
    return row


async def update_rule(
    session: AsyncSession,
    rule_id: uuid.UUID,
    *,
    expected_version: int,
    value: str | None = None,
    enabled: bool | None = None,
) -> MailBlockRule:
    """Change a rule's value or switch it on or off (If-Match)."""
    row = await get_rule(session, rule_id)
    if row.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": row.version},
        )
    kind = BlockKind(row.kind)
    changed = False
    if value is not None:
        stored = _checked(kind, value)
        if stored != row.value:
            if await _taken(session, kind, stored, but=row.id):
                raise Conflict(code="mail_block_rule_exists")
            row.value, changed = stored, True
    if enabled is not None and enabled != row.enabled:
        row.enabled, changed = enabled, True
    if changed:
        row.version += 1
        row.updated_at = datetime.now(UTC)
        await session.flush()
        await _announce(session, row, "changed")
    return row


async def remove_rule(session: AsyncSession, rule_id: uuid.UUID, *, expected_version: int) -> None:
    """Remove a rule (kept, soft-deleted, for the audit trail)."""
    row = await get_rule(session, rule_id)
    if row.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": row.version},
        )
    row.deleted_at = row.updated_at = datetime.now(UTC)
    row.version += 1
    await session.flush()
    await _announce(session, row, "removed")
