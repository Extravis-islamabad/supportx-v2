"""Search never finds a value someone may not see (ADR-047 §6; slice b2).

A custom field with any field access rule stays out of a record's search text (`custom_text`),
whoever searches. When a custom field gains or loses rules, every record of that type needs its
search text rebuilt, and until that is done search **fails closed**: it ignores custom text for
that type, for everyone (fewer matches for a while, never a leak).

- `mark` sets the type's mark (`custom_text_rebuilding_since`, migration 0162) inside the rule
  change's own transaction (an identity_access rule listener); the `field_access.changed`
  consumer sets it again as a backstop.
- `rebuild_schedule` passes over the marked types' records in committed pages, writing only the
  rows whose search text changes (never the version or the time a person changed it), and
  clears the mark when a pass ends with no newer rule change since it started.
- `rebuilding(session, wtype)` tells search to match the subject and description only.
"""

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access import register_rule_listener, restricted_fields
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


async def mark(session: AsyncSession, record_type: str, field: str) -> None:
    """A custom field's rules changed: the type's search text is rebuilt, closed meanwhile.

    Registered with identity_access as a rule listener, so the mark commits with the rule
    itself: there is no moment where the rule holds and search still matches its words.
    """
    if not field.startswith(CUSTOM) or record_type not in {c.value for c in TYPES}:
        return
    await session.execute(
        update(WorkItemTypeSettings)
        .where(WorkItemTypeSettings.type == record_type)
        .values(custom_text_rebuilding_since=datetime.now(UTC))
    )


async def on_field_access_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """The backstop: the same mark from the event (a rule changed some other way)."""
    if session is None:
        return
    await mark(
        session,
        str(envelope.payload.get("record_type", "")),
        str(envelope.payload.get("field", "")),
    )


def register() -> None:
    """The in-transaction listener (at import, like the field catalogue)."""
    register_rule_listener(mark)


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


# Where an unfinished pass stopped, per tenant and type, with the mark it was started for. In
# process only: after a restart a pass starts again from the first record (slower, never wrong).
_PROGRESS: dict[tuple[uuid.UUID, str], tuple[datetime, uuid.UUID]] = {}
BUDGET_SECONDS = 50.0  # inside the schedule's 60 s, so a big type never stacks up ticks


async def rebuild(
    database: Database,
    tenant: uuid.UUID,
    wtype: WorkItemType,
    *,
    budget_seconds: float | None = None,
) -> bool:
    """A pass over a marked type; True when the mark could be cleared.

    With a budget the pass stops after it (between pages) and the next call goes on from there;
    False then means "not finished yet". The mark stays the whole time, so search stays closed.
    """
    context = TenantContext(tenant)
    key = (tenant, wtype.code.value)
    async with database.tenant_session(context) as session:
        started = await session.scalar(
            select(WorkItemTypeSettings.custom_text_rebuilding_since).where(
                WorkItemTypeSettings.type == wtype.code.value
            )
        )
    if started is None:
        _PROGRESS.pop(key, None)
        return True
    kept = _PROGRESS.pop(key, None)
    # A newer rule change (a newer mark) starts the pass again: its rows may differ.
    after: uuid.UUID | None = kept[1] if kept is not None and kept[0] == started else None
    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
    while True:
        async with database.tenant_session(context) as session:
            _, after = await _page(session, wtype, after)
        if after is None:
            break
        if deadline is not None and time.monotonic() >= deadline:
            _PROGRESS[key] = (started, after)
            return False
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
            if wtype is not None and not await rebuild(
                database, tenant, wtype, budget_seconds=BUDGET_SECONDS
            ):
                log.info("search_text_rebuild_continues", tenant_id=str(tenant), type=code)


__all__ = [
    "FIELD_ACCESS_CHANGED",
    "mark",
    "rebuild",
    "rebuild_schedule",
    "rebuilding",
    "register",
    "withheld_keys",
]
