"""Kept drafts of unsent create forms (WP-046a S5c; REQ-INC-019).

A person's unsent form is kept on the server, sealed, so a reload, a crashed browser or an
expired session loses nothing (the browser's own copy stays as the first net). Lane B's
conditions:

- Owner only: every query names the session's tenant (RLS) and the caller as owner; anyone
  else, admins included, gets 404. No route lists another person's drafts.
- Sealed with `field.work_items.draft`, bound to the row's ID (made before sealing), so a body
  opens nowhere else; one that does not open comes back as unreadable, never as empty.
- No audit (personal and unsent; the record it becomes is audited), never the body or its size
  in a log. A personal signal carries only the form key and the version.
- It goes when the record is saved (the caller's own draft only), when discarded, when its
  owner is deactivated or erased, and after 30 days.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.work_items.domain import drafts as rules
from app.modules.work_items.events import WorkItemDraftChanged
from app.modules.work_items.infra.models import WorkItemDraft
from app.shared.events import ConsumerSpec, EventEnvelope, record_event
from app.shared.fields import Binding, field_cipher_for, purpose
from app.shared.ids import new_id

log = get_logger(__name__)
DRAFT = purpose(module="work_items", what="draft")
TABLE = "work_item_drafts"


@dataclass(frozen=True)
class Kept:
    """A person's draft as they get it back: its values, or that it could not be read."""

    version: int
    updated_at: datetime
    values: dict[str, Any] | None  # None: unreadable (the page offers Discard only)


def _type_of(form_key: str) -> str:
    """The form's work item type; 422 for a key that keeps no draft (lane B's condition 1)."""
    found = rules.form_type(form_key)
    if found is None:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="path.form_key",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            ]
        )
    return found


async def _row(
    session: AsyncSession, owner_id: uuid.UUID, form_key: str, *, lock: bool = False
) -> WorkItemDraft | None:
    query = select(WorkItemDraft).where(
        WorkItemDraft.owner_id == owner_id,
        WorkItemDraft.type == _type_of(form_key),
        WorkItemDraft.form_key == form_key,
    )
    return await session.scalar(query.with_for_update() if lock else query)


async def get(
    session: AsyncSession, settings: Settings, owner_id: uuid.UUID, form_key: str
) -> Kept:
    """The caller's own draft of this form (404 when there is none)."""
    row = await _row(session, owner_id, form_key)
    if row is None:
        raise NotFound(code="draft_not_found")
    cipher = field_cipher_for(session, settings)
    opened = await cipher.open(DRAFT, Binding(TABLE, row.id, "body"), row.body)
    values: dict[str, Any] | None = None
    if opened is not None:
        try:
            parsed = json.loads(opened)
        except ValueError:
            parsed = None
        values = parsed if isinstance(parsed, dict) else None
    return Kept(row.version, row.updated_at, values)


async def _announce(
    session: AsyncSession, owner_id: uuid.UUID, form_key: str, version: int
) -> None:
    await record_event(
        session,
        WorkItemDraftChanged(owner_id=owner_id, form_key=form_key, version=version),
        aggregate_id=owner_id,
        aggregate_version=version,
    )


async def put(  # noqa: PLR0913, PLR0917 - the draft and its version, explicit
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    owner_id: uuid.UUID,
    form_key: str,
    values: Any,  # noqa: ANN401 - the request's JSON, checked here
    *,
    expected_version: int,
) -> int:
    """Keep the caller's draft (If-Match: 0 for a new one); its new version."""
    wtype = _type_of(form_key)
    try:
        plain = rules.checked(values)
    except rules.DraftRefused as refused:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.values",
                    code=refused.code,
                    message_key=f"errors.field.{refused.code}",
                )
            ]
        ) from None
    row = await _row(session, owner_id, form_key, lock=True)
    current = 0 if row is None else row.version
    if current != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current},
        )
    cipher = field_cipher_for(session, settings)
    now = datetime.now(UTC)
    if row is None:
        draft_id = new_id()  # UUIDv7, made before sealing: the row is inserted with it (lane B)
        body = await cipher.seal(DRAFT, Binding(TABLE, draft_id, "body"), plain)
        # Two first saves at once (two tabs, both If-Match 0): one inserts, the other finds the
        # row taken and is told it is stale, never a 500 (lane B's #495 review).
        inserted = await session.scalar(
            insert(WorkItemDraft)
            .values(
                id=draft_id,
                tenant_id=tenant_id,
                owner_id=owner_id,
                type=wtype,
                form_key=form_key,
                body=body,
                version=1,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "owner_id", "type", "form_key"])
            .returning(WorkItemDraft.id)
        )
        if inserted is None:
            raise Conflict(
                code="version_conflict", params={"expected_version": 0, "current_version": 1}
            )
        version = 1
    else:
        row.body = await cipher.seal(DRAFT, Binding(TABLE, row.id, "body"), plain)
        row.version += 1
        row.updated_at = now
        await session.flush()
        version = row.version
    await _announce(session, owner_id, form_key, version)
    return version


async def discard(session: AsyncSession, owner_id: uuid.UUID, form_key: str) -> None:
    """Remove the caller's draft of this form (nothing to remove is fine)."""
    row = await _row(session, owner_id, form_key, lock=True)
    if row is None:
        return
    version = row.version + 1
    await session.delete(row)
    await session.flush()
    await _announce(session, owner_id, form_key, version)


async def saved(session: AsyncSession, owner_id: uuid.UUID, form_key: str | None) -> None:
    """The record was saved: the caller's own draft of that form goes (lane B's condition 8).

    A key that keeps no draft, or another person's, does nothing.
    """
    if form_key is None or rules.form_type(form_key) is None:
        return
    await discard(session, owner_id, form_key)


async def forget_owner(session: AsyncSession, owner_id: uuid.UUID) -> int:
    """A deactivated or erased person's drafts go (lane B's condition 3)."""
    result = await session.execute(delete(WorkItemDraft).where(WorkItemDraft.owner_id == owner_id))
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_old(session: AsyncSession, now: datetime) -> int:
    """Drafts not touched for 30 days go."""
    result = await session.execute(
        delete(WorkItemDraft).where(WorkItemDraft.updated_at < now - rules.KEPT_FOR)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_schedule(database: Database, settings: Settings) -> None:
    """Daily, every tenant: drafts older than 30 days go."""
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    now = datetime.now(UTC)
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            await purge_old(session, now)


async def on_user_status_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Deactivated (an admin, the directory, or an erasure): their drafts go."""
    if session is None or envelope.payload.get("status") != "disabled":
        return
    await forget_owner(session, uuid.UUID(str(envelope.payload["user_id"])))


OWNER_LEFT = ConsumerSpec(
    name="work_items__drafts_owner_left",
    event_types=("identity_access.user.status_changed",),
    handler=on_user_status_changed,
)


__all__ = [
    "DRAFT",
    "OWNER_LEFT",
    "Kept",
    "discard",
    "forget_owner",
    "get",
    "purge_old",
    "purge_schedule",
    "put",
    "saved",
]
