"""What wakes a waiting workflow instance (WP-048b S1, ADR-043 §5).

- `on_record_event`, a consumer: a committed change of a record (read by the owning module's
  event reader, as triggers read it) moves on every instance waiting on that record. Requests
  never call the runtime; the outbox carries the change here (CLAUDE.md rule b).
- `wake_due`, a schedule every minute: instances whose timer is due run once more. Temporal is the
  quick waker (its interpreter workflow follows); this sweep is the net when it is down, as the
  SLA clocks have (ADR-037). Running an instance twice is harmless: `run` applies only what is
  new (ADR-043 §5).
"""

import uuid

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.automation.domain.interpreter import InstanceStatus, RecordChanged, TimerFired
from app.modules.automation.domain.triggers import TriggerEvent
from app.modules.automation.domain.workflows import WaitEvent
from app.modules.automation.infra.models import WorkflowInstance
from app.modules.automation.service import workflow_runtime
from app.modules.automation.service.registry import event_reader
from app.shared.clock import system_clock
from app.shared.events import EventEnvelope

log = structlog.get_logger(__name__)

# The record events a wait node can listen for, from what the owning modules' readers say.
# Approval decisions, task completions and worklogs join with session 2's people nodes.
_WAITS = {
    TriggerEvent.CREATED: WaitEvent.FIELD_CHANGED,
    TriggerEvent.UPDATED: WaitEvent.FIELD_CHANGED,
    TriggerEvent.ASSIGNED: WaitEvent.FIELD_CHANGED,
    TriggerEvent.STATUS_CHANGED: WaitEvent.STATUS_CHANGED,
    TriggerEvent.NOTE_ADDED: WaitEvent.NOTE_ADDED,
    TriggerEvent.REQUESTER_REPLIED: WaitEvent.REQUESTER_REPLIED,
}


async def on_record_event(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: the instances waiting on this record hear what happened to it."""
    if session is None:  # transactional consumer: the registry always gives one
        msg = "workflow events need the consumer's session"
        raise RuntimeError(msg)
    reader = event_reader(envelope.event_type)
    happened = await reader(session, envelope) if reader is not None else None
    if happened is None or happened.event is None:
        return
    kind = _WAITS.get(happened.event)
    if kind is None:
        return
    waiting = list(
        await session.scalars(
            select(WorkflowInstance.id).where(
                WorkflowInstance.record_type == happened.record_type,
                WorkflowInstance.record_id == happened.record_id,
                WorkflowInstance.status == InstanceStatus.WAITING.value,
            )
        )
    )
    for instance_id in waiting:
        await workflow_runtime.run(session, instance_id, RecordChanged(kind))


async def _due(session: AsyncSession) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            select(WorkflowInstance.id).where(
                WorkflowInstance.status == InstanceStatus.WAITING.value,
                WorkflowInstance.wake_at.is_not(None),
                WorkflowInstance.wake_at <= system_clock.now(),
            )
        )
    )


async def wake_due(database: Database, settings: Settings) -> None:
    """Every minute: run every instance whose timer is due, one transaction each."""
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            due = await _due(session)
        for instance_id in due:
            async with database.tenant_session(TenantContext(tenant)) as session:
                await workflow_runtime.run(session, instance_id, TimerFired())
            log.info("workflow_woken", tenant_id=str(tenant), instance_id=str(instance_id))
