"""Task reminders (WP-046a S1; REQ-INC-073 AC2, -076): a sweep that raises each one once.

Every five minutes, in every tenant (app.tenant_id set, RLS), the sweep finds open tasks with an
owner on records that are not deleted:
- `starts_soon`: the task's own reminder ("this many minutes before the scheduled start") has
  come and the start has not passed yet;
- `overdue`: the task's due time passed in the last few days.

Each is claimed once in `processed_events` (consumer `task_reminders`) on a key made of the task,
the kind and the time it is for, as the change reminders are: a second sweep raises nothing, a
moved start or due time makes a new key. Every look-back stays inside the claims' least
retention (7 days). The notification source re-reads the task at send time, so a reminder for a
time that moved, or a task done meanwhile, says nothing.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Select, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.work_items.domain.parts import OPEN_TASK_STATUSES
from app.modules.work_items.events import WorkItemTaskReminderDue
from app.modules.work_items.infra.models import WorkItem, WorkItemTask
from app.shared.clock import Clock, SystemClock
from app.shared.events import record_event
from app.shared.events.outbox import ProcessedEvent

log = get_logger(__name__)

CONSUMER = "task_reminders"
EVERY_SECONDS = 300
LOOK_BACK = timedelta(days=3)  # well inside the claims' 7-day least retention
_NAMESPACE = uuid.UUID("2b7c9e41-6d0f-5a83-b1e4-046a51000000")

STARTS_SOON = "starts_soon"
OVERDUE = "overdue"
KINDS = (STARTS_SOON, OVERDUE)


def reminder_key(task_id: uuid.UUID, kind: str, at: datetime) -> uuid.UUID:
    """The reminder's one-time key: the task, the kind and the time it is for."""
    return uuid.uuid5(_NAMESPACE, f"{task_id}|{kind}|{at.isoformat()}")


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


async def _raise(
    session: AsyncSession, task: WorkItemTask, record: WorkItem, kind: str, at: datetime
) -> bool:
    if not await _claim(session, reminder_key(task.id, kind, at)):
        return False
    await record_event(
        session,
        WorkItemTaskReminderDue(work_item_id=record.id, task_id=task.id, kind=kind, at=at),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return True


def _open_owned() -> Select[WorkItemTask, WorkItem]:
    return (
        select(WorkItemTask, WorkItem)
        .join(WorkItem, WorkItem.id == WorkItemTask.work_item_id)
        .where(
            WorkItemTask.deleted_at.is_(None),
            WorkItemTask.owner_id.is_not(None),
            WorkItemTask.status.in_(OPEN_TASK_STATUSES),
            WorkItem.deleted_at.is_(None),
        )
    )


async def sweep(session: AsyncSession, clock: Clock) -> int:
    """Raise every task reminder due now in this tenant, each once; how many were raised."""
    now = clock.now()
    raised = 0
    remind_at = WorkItemTask.scheduled_start - func.make_interval(
        0, 0, 0, 0, 0, WorkItemTask.remind_before_minutes
    )
    starting = await session.execute(
        _open_owned().where(
            WorkItemTask.remind_before_minutes.is_not(None),
            WorkItemTask.scheduled_start > now,
            remind_at <= now,
        )
    )
    for task, record in starting.all():
        assert task.scheduled_start is not None  # noqa: S101 - filtered above
        raised += await _raise(session, task, record, STARTS_SOON, task.scheduled_start)
    late = await session.execute(
        _open_owned().where(
            WorkItemTask.due_at.is_not(None),
            WorkItemTask.due_at <= now,
            WorkItemTask.due_at >= now - LOOK_BACK,
        )
    )
    for task, record in late.all():
        assert task.due_at is not None  # noqa: S101 - filtered above
        raised += await _raise(session, task, record, OVERDUE, task.due_at)
    return raised


async def reminders_schedule(database: Database, settings: Settings) -> None:
    """Every five minutes, every tenant: the task reminders due now.

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
                    log.info("task_reminders_raised", tenant_id=str(tenant), count=raised)
        except Exception:
            log.warning("task_reminders_failed", tenant_id=str(tenant), exc_info=True)


__all__ = ["KINDS", "OVERDUE", "STARTS_SOON", "reminder_key", "reminders_schedule", "sweep"]
