"""Change reminders (WP-045d S3; REQ-CHG-091, -105): a sweep that raises each one once.

Every few minutes, in every tenant (app.tenant_id set, RLS), the sweep finds:
- `window_start`: an open change whose implementation window starts within the hour (the
  implementer and the change owner hear of it);
- `implementation_overdue`: the window ended in the last few days and the change is still in
  implementation, not implemented (the owner and the change manager);
- `cab_waiting`: the window starts within a day and a CAB member has not decided yet (that
  member);
- `review_due`: the change is in review and its review date has come (the owner and the
  reviewer).

Each reminder is claimed once (the coordinator, 2026-11-11): a row in `processed_events` for the
consumer `change_reminders` on a key made of the change, the kind and the time it is for (and
the member). A second sweep finds the claim and raises nothing; a window moved to another time
makes a new key, so a fresh reminder is right. Every look-back stays inside the claims' least
retention (7 days), so a purged claim can never send again. Cancelled and closed changes are
never reminded (AC2), and the notification source re-reads the change at send time, so a
reminder for a window that moved meanwhile says nothing (lane B).
"""

import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.work_items.domain import approvals as approval_rules
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.types import CHANGE
from app.modules.work_items.events import ChangeReminderDue
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemApproval,
    WorkItemChangeDetails,
    WorkItemStageSchedule,
)
from app.shared.clock import Clock, SystemClock
from app.shared.events import record_event
from app.shared.events.outbox import ProcessedEvent

log = get_logger(__name__)

CONSUMER = "change_reminders"
EVERY_SECONDS = 300
IMPLEMENTATION = "implementation"
REVIEW = "review"
CAB_STAGE = "cab_review"
IMPLEMENTED = "implementation_implemented"
BEFORE_WINDOW = timedelta(hours=1)  # Appendix A: 1 hour before the window
CAB_AHEAD = timedelta(hours=24)
LOOK_BACK = timedelta(days=3)  # well inside the claims' 7-day least retention
_NAMESPACE = uuid.UUID("6f1d2c4e-0a45-5d3b-9c2e-045d53000000")

WINDOW_START = "window_start"
OVERDUE = "implementation_overdue"
CAB_WAITING = "cab_waiting"
REVIEW_DUE = "review_due"
KINDS = (WINDOW_START, OVERDUE, CAB_WAITING, REVIEW_DUE)


def reminder_key(
    record_id: uuid.UUID, kind: str, at: datetime | None, member: uuid.UUID | None = None
) -> uuid.UUID:
    """The reminder's one-time key: the change, the kind, the time it is for, the member."""
    when = at.isoformat() if at is not None else ""
    return uuid.uuid5(_NAMESPACE, f"{record_id}|{kind}|{when}|{member or ''}")


async def _claim(session: AsyncSession, key: uuid.UUID) -> bool:
    """True the first time `key` is claimed in this tenant; False ever after (until purged)."""
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    claimed = await session.scalar(
        insert(ProcessedEvent)
        .values(tenant_id=tenant, consumer=CONSUMER, event_id=key)
        .on_conflict_do_nothing()
        .returning(ProcessedEvent.event_id)
    )
    return claimed is not None


def _live() -> list[ColumnElement[bool]]:
    return [
        WorkItem.type == CHANGE.code.value,
        WorkItem.deleted_at.is_(None),
        WorkItem.status_category.in_([StatusCategory.OPEN.value, StatusCategory.PAUSED.value]),
    ]


async def _raise(  # noqa: PLR0913 - the reminder's facts, explicit
    session: AsyncSession,
    record: WorkItem,
    kind: str,
    at: datetime | None,
    *,
    window_start: datetime | None = None,
    member: uuid.UUID | None = None,
) -> bool:
    if not await _claim(session, reminder_key(record.id, kind, at, member)):
        return False
    await record_event(
        session,
        ChangeReminderDue(
            work_item_id=record.id, kind=kind, window_start=window_start, member_id=member
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return True


async def _windows(
    session: AsyncSession, low: datetime, high: datetime, *, by_end: bool = False
) -> Iterable[tuple[WorkItem, WorkItemStageSchedule]]:
    """Open changes with an implementation window starting (or ending) in [low, high)."""
    column = (
        WorkItemStageSchedule.scheduled_end if by_end else WorkItemStageSchedule.scheduled_start
    )
    rows = await session.execute(
        select(WorkItem, WorkItemStageSchedule)
        .join(WorkItemStageSchedule, WorkItemStageSchedule.work_item_id == WorkItem.id)
        .where(
            *_live(),
            WorkItemStageSchedule.stage == IMPLEMENTATION,
            WorkItemStageSchedule.scheduled_start.is_not(None),
            column >= low,
            column < high,
        )
    )
    return [(r[0], r[1]) for r in rows.all()]


async def sweep(session: AsyncSession, clock: Clock) -> int:
    """Raise every reminder due now in this tenant, each once; how many were raised."""
    now = clock.now()
    raised = 0
    for record, window in await _windows(session, now, now + BEFORE_WINDOW):
        raised += await _raise(
            session,
            record,
            WINDOW_START,
            window.scheduled_start,
            window_start=window.scheduled_start,
        )
    for record, window in await _windows(session, now - LOOK_BACK, now, by_end=True):
        if record.stage != IMPLEMENTATION or record.status == IMPLEMENTED:
            continue
        raised += await _raise(
            session, record, OVERDUE, window.scheduled_end, window_start=window.scheduled_start
        )
    for record, window in await _windows(session, now, now + CAB_AHEAD):
        waiting = await session.scalars(
            select(WorkItemApproval.approver_id).where(
                WorkItemApproval.work_item_id == record.id,
                WorkItemApproval.deleted_at.is_(None),
                WorkItemApproval.record_stage == CAB_STAGE,
                WorkItemApproval.state == approval_rules.ApprovalState.PENDING.value,
                WorkItemApproval.approver_id.is_not(None),
            )
        )
        for member in set(waiting):
            raised += await _raise(
                session,
                record,
                CAB_WAITING,
                window.scheduled_start,
                window_start=window.scheduled_start,
                member=member,
            )
    due = await session.execute(
        select(WorkItem, WorkItemChangeDetails.review_due_at)
        .join(WorkItemChangeDetails, WorkItemChangeDetails.work_item_id == WorkItem.id)
        .where(
            *_live(),
            WorkItem.stage == REVIEW,
            WorkItemChangeDetails.review_due_at >= now - LOOK_BACK,
            WorkItemChangeDetails.review_due_at <= now,
        )
    )
    for record, review_at in due.all():
        raised += await _raise(session, record, REVIEW_DUE, review_at)
    return raised


async def reminders_schedule(database: Database, settings: Settings) -> None:
    """Every five minutes, every tenant: the change reminders due now.

    Each tenant in its own session; one tenant failing never stops the others.
    """
    del settings
    clock = SystemClock()
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        try:
            async with database.tenant_session(TenantContext(tenant)) as session:
                if raised := await sweep(session, clock):
                    log.info("change_reminders_raised", tenant_id=str(tenant), count=raised)
        except Exception:
            log.warning("change_reminders_failed", tenant_id=str(tenant), exc_info=True)
