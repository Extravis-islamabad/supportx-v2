"""Search never finds a value someone may not see (ADR-047 §6; slice b2).

A custom field with any field access rule stays out of a record's search text (`custom_text`),
whoever searches. When a custom field gains or loses rules, every record of that type needs its
search text rebuilt, and until that is done search **fails closed**: it ignores custom text for
that type, for everyone (fewer matches for a while, never a leak).

- `on_field_access_changed` marks the type (`custom_text_rebuilding_since`, migration 0162) in
  the event's transaction.
- `rebuild_schedule` passes over the marked types' records in committed pages, writing only the
  rows whose search text changes (never the version or the time a person changed it), and
  clears the mark when a pass ends with no newer rule change since it started.
- `rebuilding(session, wtype)` tells search to match the subject and description only.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access import restricted_fields
from app.modules.work_items.domain.field_access import CUSTOM
from app.modules.work_items.domain.types import TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemTypeSettings
from app.shared.events import ConsumerSpec, EventEnvelope

log = get_logger(__name__)
PAGE = 500


async def withheld_keys(session: AsyncSession, record_type: str) -> frozenset[str]:
    """The record type's custom keys any role restricts: never in its search text."""
    return frozenset(
        f[len(CUSTOM) :]
        for f in await restricted_fields(session, record_type)
        if f.startswith(CUSTOM)
    )


async def rebuilding(session: AsyncSession, wtype: WorkItemType) -> bool:
    """Whether the type's search text is being rebuilt (search then ignores custom text)."""
    since = await session.scalar(
        select(WorkItemTypeSettings.custom_text_rebuilding_since).where(
            WorkItemTypeSettings.type == wtype.code.value
        )
    )
    return since is not None


async def on_field_access_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """A custom field's rules changed: the type's search text is rebuilt, closed meanwhile."""
    field = str(envelope.payload.get("field", ""))
    record_type = str(envelope.payload.get("record_type", ""))
    if (
        session is None
        or not field.startswith(CUSTOM)
        or record_type not in {c.value for c in TYPES}
    ):
        return
    await session.execute(
        update(WorkItemTypeSettings)
        .where(WorkItemTypeSettings.type == record_type)
        .values(custom_text_rebuilding_since=datetime.now(UTC))
    )


FIELD_ACCESS_CHANGED = ConsumerSpec(
    name="work_items__search_text_rebuild",
    event_types=("identity_access.field_access.changed",),
    handler=on_field_access_changed,
)


async def _page(
    session: AsyncSession, wtype: WorkItemType, after: uuid.UUID | None
) -> tuple[int, uuid.UUID | None]:
    """One page of the type's records: their search text written again where it changed."""
    from app.modules.work_items.service.work_items import custom_text_for  # noqa: PLC0415 - a cycle

    query = (
        select(WorkItem.id, WorkItem.custom, WorkItem.custom_text, WorkItem.updated_at)
        .where(WorkItem.type == wtype.code.value)
        .order_by(WorkItem.id)
        .limit(PAGE)
    )
    if after is not None:
        query = query.where(WorkItem.id > after)
    rows = (await session.execute(query)).all()
    changed = 0
    for row in rows:
        fresh = await custom_text_for(session, wtype, row.custom or {}, row.id)
        if fresh != row.custom_text:
            # Derived text only: neither the version nor the time a person last changed it.
            await session.execute(
                update(WorkItem)
                .where(WorkItem.id == row.id)
                .values(custom_text=fresh, updated_at=row.updated_at)
            )
            changed += 1
    return changed, (rows[-1].id if len(rows) == PAGE else None)


async def rebuild(database: Database, tenant: uuid.UUID, wtype: WorkItemType) -> bool:
    """One full pass over a marked type; True when the mark could be cleared."""
    context = TenantContext(tenant)
    async with database.tenant_session(context) as session:
        started = await session.scalar(
            select(WorkItemTypeSettings.custom_text_rebuilding_since).where(
                WorkItemTypeSettings.type == wtype.code.value
            )
        )
    if started is None:
        return True
    after: uuid.UUID | None = None
    while True:
        async with database.tenant_session(context) as session:
            _, after = await _page(session, wtype, after)
        if after is None:
            break
    async with database.tenant_session(context) as session:
        # Cleared only if no rule changed while the pass ran: a newer change asks for another.
        result = await session.execute(
            update(WorkItemTypeSettings)
            .where(
                WorkItemTypeSettings.type == wtype.code.value,
                WorkItemTypeSettings.custom_text_rebuilding_since == started,
            )
            .values(custom_text_rebuilding_since=None)
        )
    return bool(getattr(result, "rowcount", 0))


async def rebuild_schedule(database: Database, settings: Settings) -> None:
    """Every tenant's marked types, rebuilt (a periodic job of the consumers worker)."""
    del settings
    from sqlalchemy import text  # noqa: PLC0415 - one platform query

    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            marked = list(
                (
                    await session.scalars(
                        select(WorkItemTypeSettings.type).where(
                            WorkItemTypeSettings.custom_text_rebuilding_since.is_not(None)
                        )
                    )
                ).all()
            )
        for code in marked:
            wtype = TYPES.get(WorkItemTypeCode(code))
            if wtype is not None and not await rebuild(database, tenant, wtype):
                log.info("search_text_rebuild_again", tenant_id=str(tenant), type=code)


__all__ = [
    "FIELD_ACCESS_CHANGED",
    "rebuild",
    "rebuild_schedule",
    "rebuilding",
    "withheld_keys",
]
