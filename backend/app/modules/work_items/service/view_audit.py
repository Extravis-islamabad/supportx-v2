"""The shared-view audit (D-176; lane C's review).

Shared views whose filter names a field some recipient may not see go back to private.

Who sees a shared view is decided on every read (`lists.usable`): that is the guarantee. This
job tidies up after it, so a view stops being shared at all once its filter names a field that
any role restricts (ADR-047, as search counts it) or that is sealed (ADR-050):

- the view becomes private to its owner: version, field history (source system), the usual
  `work_items.view.changed` event and `work_items.view.unshared` with the field's key;
- nothing is deleted; other people's stars of it go (theirs no longer);
- the owner is told which field caused it and how to share it again (a notice, owner only);
- `unshared_at` and `unshared_field` keep it for the administrators' report.

Idempotent: a private view is never touched, so running it twice changes nothing more. It runs
every six hours for every tenant (its first run after migration 0178 finishes the clean-up, which
0178 starts with the sealed fields), whenever a field access rule changes, and when an
administrator asks for it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules import metadata
from app.modules.identity_access import restricted_fields
from app.modules.work_items.domain import field_access as field_rules
from app.modules.work_items.domain.lists import ViewVisibility
from app.modules.work_items.domain.types import PERMISSION_TYPES, WorkItemType
from app.modules.work_items.events import WorkItemViewChanged, WorkItemViewUnshared
from app.modules.work_items.infra.models import WorkItemView, WorkItemViewFavourite
from app.shared.events import ConsumerSpec, EventEnvelope, record_event
from app.shared.history import Change, record_changes
from app.shared.notifications.ports import (
    EventDefault,
    LabelRef,
    Localised,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

RESTRICTED = "restricted_field"
SEALED = "sealed_field"
RECORD_TYPE = "work_item_view"
UNSHARED = "work_item_view.unshared"
OWNER = "view_owner"
FIELD_ACCESS_CHANGED = "identity_access.field_access.changed"
# Lane C (#549): a field turning sensitive starts the check at once, not at the next tick.
SEAL_CHANGED = "metadata.custom_field.seal_changed"


@dataclass(frozen=True)
class Unshared:
    """One view the audit made private."""

    view_id: uuid.UUID
    owner_id: uuid.UUID
    field_key: str
    reason: str


async def _withheld(session: AsyncSession, wtype: WorkItemType) -> tuple[frozenset[str], ...]:
    restricted = await restricted_fields(session, wtype.code.value)
    sealed = frozenset(
        f"{field_rules.CUSTOM}{m.key}"
        for m in await metadata.field_marks(session, wtype.code.value, retired=True)
        if m.sensitive or m.seal_state != "plain"
    )
    return restricted, sealed


async def audit_type(session: AsyncSession, wtype: WorkItemType, now: datetime) -> list[Unshared]:
    """Make the type's offending shared views private (the tenant of the session)."""
    restricted, sealed = await _withheld(session, wtype)
    withheld = restricted | sealed
    if not withheld:
        return []
    rows = await session.scalars(
        select(WorkItemView)
        .where(
            WorkItemView.type == wtype.code.value,
            WorkItemView.deleted_at.is_(None),
            WorkItemView.visibility != ViewVisibility.PRIVATE.value,
        )
        .order_by(WorkItemView.id)
        .with_for_update()
    )
    done: list[Unshared] = []
    for row in rows:
        found = field_rules.withheld_in_filter(row.filter, withheld)
        if not found:
            continue
        field = found[0]
        reason = SEALED if field in sealed else RESTRICTED
        before = (row.visibility, [str(g) for g in row.group_ids])
        row.visibility = ViewVisibility.PRIVATE.value
        row.group_ids = []
        row.unshared_at = now
        row.unshared_field = field
        row.version += 1
        row.updated_at = now
        await session.flush()
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=row.id,
            version=row.version,
            kind="updated",
            changes=[
                Change("visibility", before[0], ViewVisibility.PRIVATE.value),
                *([Change("group_ids", before[1], [])] if before[1] else []),
            ],
            source="system",
        )
        await session.execute(
            delete(WorkItemViewFavourite).where(
                WorkItemViewFavourite.view_id == row.id,
                WorkItemViewFavourite.user_id != row.owner_id,
            )
        )
        await record_event(
            session,
            WorkItemViewChanged(
                view_id=row.id, type=row.type, owner_id=row.owner_id, visibility=row.visibility
            ),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
        await record_event(
            session,
            WorkItemViewUnshared(
                view_id=row.id, type=row.type, owner_id=row.owner_id, field_key=field, reason=reason
            ),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
        done.append(Unshared(row.id, row.owner_id, field, reason))
    return done


async def audit_all(session: AsyncSession, now: datetime | None = None) -> list[Unshared]:
    """Every type of the session's tenant."""
    when = now or datetime.now(UTC)
    found: list[Unshared] = []
    for wtype in PERMISSION_TYPES:  # the types that have saved views and share rights
        found.extend(await audit_type(session, wtype, when))
    return found


async def unshared_views(
    session: AsyncSession, wtype: WorkItemType, *, limit: int = 200
) -> list[WorkItemView]:
    """The administrators' report: views the audit made private, newest first."""
    rows = await session.scalars(
        select(WorkItemView)
        .where(
            WorkItemView.type == wtype.code.value,
            WorkItemView.deleted_at.is_(None),
            WorkItemView.unshared_at.is_not(None),
        )
        .order_by(WorkItemView.unshared_at.desc(), WorkItemView.id)
        .limit(limit)
    )
    return list(rows)


async def on_field_access_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: a field rule or seal changed, so shared views are checked again (idempotent)."""
    del envelope
    if session is None:
        return
    await audit_all(session)


VIEW_AUDIT = ConsumerSpec(
    name="work_items__view_audit",
    event_types=(FIELD_ACCESS_CHANGED, SEAL_CHANGED),
    handler=on_field_access_changed,
)

AUDIT_EVERY_SECONDS = 6 * 3600


async def audit_schedule(database: Database, settings: Settings) -> None:
    """Every six hours, every tenant (as the drafts purge): the backstop and 0178's finish."""
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    now = datetime.now(UTC)
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            await audit_all(session, now)


# --- the owner's notice --------------------------------------------------------------------------

_VARIABLES = (
    Variable("record.title", "notification_variable.saved_view.name"),
    Variable("view.field", "notification_variable.saved_view.field"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


async def _field_name(session: AsyncSession, record_type: str, field: str) -> VariableValue:
    """The field by its name in each reader's language, never its key (rule d)."""
    if field.startswith(field_rules.CUSTOM):
        key = field[len(field_rules.CUSTOM) :]
        for mark in await metadata.field_marks(session, record_type, retired=True):
            if mark.key == key:
                return Localised(mark.labels, fallback="work_item.field.custom")
        return LabelRef("work_item.field.custom")
    label = field_rules.BUILTIN.get(record_type, {}).get(field)
    return LabelRef(label or f"work_item.field.{field}")


class SavedViewNotifications:
    """The notification source of saved views: the owner hears their view was made private."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = "users"
    events: ClassVar[tuple[NotificationEvent, ...]] = (
        NotificationEvent(
            UNSHARED,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(OWNER,), notify_actor=True),
            required=True,
            locked=True,
        ),
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (OWNER,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (WorkItemViewUnshared.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notice per view made private."""
        return (UNSHARED,) if envelope.event_type == WorkItemViewUnshared.event_type else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The view by name, the field by name, its owner only."""
        del event_code
        notice = WorkItemViewUnshared.model_validate(envelope.payload)
        row = await session.get(WorkItemView, notice.view_id)
        if row is None or row.deleted_at is not None:
            return None
        wtype = next((t for t in PERMISSION_TYPES if t.code.value == row.type), None)
        link = f"/{wtype.path}?view=custom:{row.id}" if wtype is not None else "/"
        values: dict[str, VariableValue] = {
            "record.title": row.name,
            "view.field": await _field_name(session, row.type, notice.field_key),
            "record.link": link,
        }
        return RecordContext(
            record_id=row.id,
            display_id=row.name,
            link=link,
            variables=values,
            public_variables=values,
            relatives={OWNER: frozenset({row.owner_id})},
            conditions={},
            urgent=False,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for the view's owner (checked at send time), nobody else."""
        row = await session.get(WorkItemView, record_id)
        return (
            RecordAccess.FULL if row is not None and row.owner_id == user_id else RecordAccess.NONE
        )


SOURCE = SavedViewNotifications()


def register() -> None:
    """Make the audit notify (idempotent; called when work_items is imported)."""
    register_record_source(SOURCE)
