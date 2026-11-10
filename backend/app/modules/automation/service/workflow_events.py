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
from collections.abc import Mapping

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.errors import Conflict
from app.core.tenancy import TenantContext
from app.modules.automation.domain.interpreter import (
    CommandDone,
    InstanceStatus,
    RecordChanged,
    TimerFired,
)
from app.modules.automation.domain.rules import JsonValue
from app.modules.automation.domain.triggers import TriggerEvent
from app.modules.automation.domain.workflows import WaitEvent
from app.modules.automation.events import WorkflowCommandFinished, WorkflowFunctionRequested
from app.modules.automation.infra.models import Workflow, WorkflowInstance
from app.modules.automation.service import functions, workflow_runtime
from app.modules.automation.service.registry import event_reader
from app.modules.automation.service.registry import record_type as registered
from app.shared.clock import system_clock
from app.shared.events import EventEnvelope, record_event

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
    if happened.event == TriggerEvent.CREATED:
        await _start_from_template(session, happened.record_type, happened.record_id)
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


async def command_finished(  # noqa: PLR0913 - the result, explicit
    session: AsyncSession,
    *,
    instance_id: uuid.UUID,
    command: str,
    ok: bool,
    port: str | None = None,
    error: str | None = None,
    outputs: Mapping[str, JsonValue] | None = None,
) -> None:
    """An owning module's later result for a workflow command, in its own transaction (rule b).

    The approval node's decision: the outbox carries it, and `on_command_finished` continues the
    instance after the commit, so a decision never runs a workflow inside the person's request.
    """
    await record_event(
        session,
        WorkflowCommandFinished(
            instance_id=instance_id,
            command=command,
            ok=ok,
            port=port,
            error=error,
            outputs=dict(outputs or {}),
        ),
        aggregate_id=instance_id,
    )


async def on_command_finished(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: the waiting node hears its result; one seen twice changes nothing."""
    if session is None:  # transactional consumer: the registry always gives one
        msg = "workflow command results need the consumer's session"
        raise RuntimeError(msg)
    done = WorkflowCommandFinished.model_validate(envelope.payload)
    # The interpreter ignores a result for a command no token waits on (activities run at least
    # once): a redelivered event is a no-op.
    await workflow_runtime.run(
        session,
        done.instance_id,
        CommandDone(done.command, done.ok, error=done.error, outputs=done.outputs, port=done.port),
    )


async def on_function_requested(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer (a worker, never the API, §6.7): run the node's function, report its result."""
    if session is None:  # transactional consumer: the registry always gives one
        msg = "workflow functions need the consumer's session"
        raise RuntimeError(msg)
    asked = WorkflowFunctionRequested.model_validate(envelope.payload)
    tenant_id = session.info[SESSION_TENANT_KEY].tenant_id
    runner = functions.function_runner()
    if runner is None or not await functions.offered(tenant_id):
        await command_finished(
            session,
            instance_id=asked.instance_id,
            command=asked.command,
            ok=False,
            error=functions.NOT_OFFERED,
        )
        return
    kind = registered(asked.record_type)
    facts = await kind.facts(session, asked.record_id) if kind and kind.facts else None
    inputs = {
        name: (facts or {}).get(str(value["field"]))
        if isinstance(value, dict) and "field" in value
        else (value.get("value") if isinstance(value, dict) else value)
        for name, value in asked.inputs.items()
    }
    outcome = await runner.run(
        tenant_id=tenant_id,
        function=asked.function,
        inputs=inputs,
        timeout_seconds=asked.timeout_seconds,
    )
    await command_finished(
        session,
        instance_id=asked.instance_id,
        command=asked.command,
        ok=outcome.ok,
        error=outcome.error,
        # Only the outputs the node keeps, as its variables (by the names it chose).
        outputs={variable: outcome.outputs.get(name) for name, variable in asked.assign.items()},
    )


async def _start_from_template(
    session: AsyncSession, record_type: str, record_id: uuid.UUID
) -> None:
    """A record made from a template starts the enabled workflows set on it (REQ-WF-010 AC1)."""
    kind = registered(record_type)
    facts = await kind.facts(session, record_id) if kind and kind.facts else None
    template = (facts or {}).get("template_id")
    if template is None:
        return
    starting = await session.scalars(
        select(Workflow.id).where(
            Workflow.record_type == record_type,
            Workflow.enabled.is_(True),
            Workflow.deleted_at.is_(None),
            Workflow.start_templates.contains([uuid.UUID(str(template))]),
        )
    )
    for workflow_id in list(starting):
        try:
            async with session.begin_nested():
                await workflow_runtime.start(
                    session,
                    workflow_id=workflow_id,
                    record_type=record_type,
                    record_id=record_id,
                    how="template",
                )
        except Conflict:
            continue  # already running (a redelivered event): one instance per record


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
