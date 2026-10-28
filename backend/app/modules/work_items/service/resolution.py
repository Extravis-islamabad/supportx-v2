"""The requester answers a resolution: fixed (close) or not fixed (reopen) (REQ-INC-096).

Requesters hold no console permission (the portal, WP-028, and e-mail links, WP-023, call
these), so the check is that the signed-in person is the record's requester or the person it is
for; anyone else gets 404, as for a record they cannot see.

A requester cannot pick a closure code: when the closure rules ask for one and none was set,
confirming closes with "Confirmed by requester" (D-107), so reports tell it from a technician's
closure. When the rules ask for anything else the record still lacks, the confirmation is
recorded and the record stays resolved for a technician to close.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access import Subject
from app.modules.work_items.domain.closure import CLOSURE_CODE
from app.modules.work_items.domain.closure import auto_close_due as closure_due
from app.modules.work_items.domain.lifecycle import StatusCategory, WorkItemAction
from app.modules.work_items.domain.templates import CONFIRMED_BY_REQUESTER
from app.modules.work_items.domain.types import TYPES, WorkItemType
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import closing, conversations
from app.modules.work_items.service import work_items as items
from app.shared.history import Change, Source, record_changes
from app.shared.richtext import is_blank, sanitize_html

log = get_logger(__name__)

# Reports tell technician closure from customer confirmation (D-107).
DEFAULT_CLOSURE_CODE = CONFIRMED_BY_REQUESTER
CONFIRMED = "requester_confirmed"
REJECTED = "requester_rejected"


@dataclass(frozen=True)
class Answered:
    """What the requester's answer did."""

    record: WorkItem
    closed: bool


async def _own_resolved(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> WorkItem:
    record = await session.scalar(
        select(WorkItem).where(
            WorkItem.id == record_id,
            WorkItem.type == wtype.code,
            WorkItem.deleted_at.is_(None),
        )
    )
    if record is None or subject.user_id not in {record.requester_id, record.on_behalf_of_id}:
        raise NotFound(code=f"{wtype.code}_not_found")
    if record.status_category != StatusCategory.RESOLVED.value:
        raise Conflict(code="not_resolved", params={"status": record.status})
    return record


async def confirm(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    source: Source,
) -> Answered:
    """Fixed: the record closes with the requester as actor (REQ-INC-096 AC1)."""
    record = await _own_resolved(session, subject, wtype, record_id)
    cat = await config.load(session, wtype)
    code = record.closure_code
    if code is None and CLOSURE_CODE in cat.closure.close_requires:
        code = DEFAULT_CLOSURE_CODE
    try:
        async with session.begin_nested():
            closed = await items.system_move(
                session,
                wtype,
                cat,
                record,
                WorkItemAction.CLOSE,
                source=source,
                rule=CONFIRMED,
                given=closing.MoveInput(closure_code=code),
            )
    except (ValidationFailed, Conflict):
        # The closure rules need more than the requester can give: a technician closes it.
        await record_changes(
            session,
            record_type=items.RECORD_TYPE,
            record_id=record.id,
            version=record.version,
            kind="child_changed",
            changes=[Change(CONFIRMED, None, new=True)],
            source=source,
        )
        return Answered(record, closed=False)
    return Answered(closed, closed=True)


async def reject(  # noqa: PLR0913 - the answer and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    comment: str,
    source: Source,
) -> Answered:
    """Not fixed: reopened to in progress, the comment a public reply (REQ-INC-096 AC2)."""
    if is_blank(sanitize_html(comment or "")):
        raise items.field_errors([("comment", "required")])
    record = await _own_resolved(session, subject, wtype, record_id)
    cat = await config.load(session, wtype)
    reopened = await items.system_move(
        session, wtype, cat, record, WorkItemAction.REOPEN, source=source, rule=REJECTED
    )
    await conversations.add_requester_comment(session, reopened, comment, source=source)
    return Answered(reopened, closed=False)


AUTO_CLOSED = "auto_close"
AUTO_CLOSE_BATCH = 200


async def auto_close_due(session: AsyncSession, wtype: WorkItemType, now: datetime) -> int:
    """Close resolved records whose requester was told and did not answer (REQ-INC-096 AC3).

    Never a record whose requester was not told (`resolution_notified_at` unset), never while
    auto-close is off or no channel reaches requesters. Recorded as "auto-closed": system actor,
    source system, the rule in history. A record the closure rules still block is left resolved.
    """
    cat = await config.load(session, wtype)
    days = cat.closure.auto_close_days
    if days is None or not closing.requester_channels():
        return 0
    # Business days are at least as long as calendar days: a cheap first cut in SQL.
    rows = await session.scalars(
        select(WorkItem)
        .where(
            WorkItem.type == wtype.code,
            WorkItem.deleted_at.is_(None),
            WorkItem.status_category == StatusCategory.RESOLVED.value,
            WorkItem.resolution_notified_at.is_not(None),
            WorkItem.resolution_notified_at <= now - timedelta(days=days),
        )
        .order_by(WorkItem.resolution_notified_at)
        .limit(AUTO_CLOSE_BATCH)
    )
    closed = 0
    for record in rows.all():
        due = closure_due(record.resolution_notified_at, days)
        if due is None or due > now:
            continue
        code = record.closure_code
        if code is None and CLOSURE_CODE in cat.closure.close_requires:
            code = DEFAULT_CLOSURE_CODE
        try:
            async with session.begin_nested():
                await items.system_move(
                    session,
                    wtype,
                    cat,
                    record,
                    WorkItemAction.CLOSE,
                    source="system",
                    rule=AUTO_CLOSED,
                    given=closing.MoveInput(closure_code=code),
                )
        except (ValidationFailed, Conflict):
            log.info("auto_close_skipped", record_id=str(record.id))
            continue
        closed += 1
    return closed


async def auto_close_schedule(database: Database, settings: Settings) -> None:
    """Every tenant: close what is due (a quick, idempotent loop; Temporal later, WP-025)."""
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    now = datetime.now(UTC)
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            for wtype in TYPES.values():
                if count := await auto_close_due(session, wtype, now):
                    log.info("auto_closed", tenant_id=str(tenant), type=wtype.code, records=count)
