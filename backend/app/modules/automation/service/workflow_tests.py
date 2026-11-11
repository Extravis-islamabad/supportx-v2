"""Test mode: run a workflow's draft without touching anything (WP-048b S3e; REQ-WF-022).

The same `advance` as a real run (ADR-043 §9), against a chosen record's facts (read once, as
they are now) or sample values. Nothing is ever applied: each command the run asks for is shown
and waits for the admin's answer (approved or rejected, done or failed); waits hear a change
the admin describes; timers move on when the admin moves the run's own clock forward. The run is
stored apart (`workflow_test_runs`) and never writes to the record or its history (AC2).

One live call per run, for one webhook or notify node, by an admin who asks for it (the
coordinator's call, 2026-11-11): audited with who, which node and which record. A webhook still
goes from the worker, never the request (ADR-043 §8); a notify goes through the one
notification engine like a real one. A function never runs live from a test.
"""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.automation.domain.interpreter import (
    CommandDone,
    CommandKind,
    Event,
    RecordChanged,
    State,
    TimerFired,
    advance,
)
from app.modules.automation.domain.workflows import Definition, TimeBasis, WaitEvent, parse
from app.modules.automation.events import WorkflowWebhookRequested
from app.modules.automation.infra.models import Workflow, WorkflowTestRun
from app.modules.automation.service import workflow_runtime
from app.modules.automation.service.registry import CommandResult
from app.modules.automation.service.registry import record_type as registered
from app.modules.identity_access import Subject
from app.shared.events import record_event

LIVE_KINDS = frozenset({CommandKind.CALL_WEBHOOK, CommandKind.NOTIFY})
SAMPLE_MAX_FIELDS = 200
FAST_FORWARD_MAX = 366 * 24 * 3600  # a year at most in one step
MASK = "•••"  # a header's value is never shown back (it may be a secret)


def _calendar(start: datetime, seconds: int, basis: TimeBasis) -> datetime:
    """A test run's clock: calendar time, whatever the node's basis (no record calendar)."""
    del basis
    return start + timedelta(seconds=seconds)


def _definition(run: WorkflowTestRun) -> Definition:
    parsed = parse(run.definition)
    if parsed.definition is None:  # checked when the run started
        msg = f"test run {run.id} without a readable definition"
        raise RuntimeError(msg)
    return parsed.definition


def _shown(kind: CommandKind, payload: Mapping[str, Any]) -> dict[str, Any]:
    """A command as the admin sees it: what it would do, never a header's secret value."""
    shown = dict(payload)
    if kind is CommandKind.CALL_WEBHOOK and isinstance(shown.get("headers"), dict):
        shown["headers"] = dict.fromkeys(shown["headers"], MASK)
    return shown


async def _advance(session: AsyncSession, run: WorkflowTestRun, event: Event | None) -> None:
    definition = _definition(run)
    state = workflow_runtime.load(run.state, run.status, run.state.get("failure"))
    result = advance(definition, state, run.facts, event, now=run.clock_at, clock=_calendar)
    raw = workflow_runtime.dump(result.state)
    if result.state.failure is not None:
        raw["failure"] = {
            "node": result.state.failure.node,
            "code": result.state.failure.code,
            "params": result.state.failure.params,
        }
    run.state = raw
    run.status = result.state.status.value
    run.steps = [
        *run.steps,
        *(
            {
                "token": s.token,
                "node": s.node,
                "node_type": s.node_type.value,
                "result": s.result,
                "at": s.at.isoformat(),
                "detail": dict(s.detail),
            }
            for s in result.steps
        ),
    ]
    run.pending = [
        *run.pending,
        *(
            {"id": c.id, "node": c.node, "kind": c.kind.value, "payload": _shown(c.kind, c.payload)}
            for c in result.commands
        ),
    ]
    run.version += 1
    await session.flush()


async def start(
    session: AsyncSession,
    subject: Subject,
    workflow_id: uuid.UUID,
    *,
    record_id: uuid.UUID | None,
    sample: Mapping[str, Any] | None,
) -> WorkflowTestRun:
    """A new test run of the workflow's draft, on a record's facts or on sample values.

    A record's facts are shown back, so only to someone who may see the record, by its type's
    own view rule: workflows.manage alone is not enough (lane B's review of #374).
    """
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None or workflow.deleted_at is not None:
        raise NotFound(code="workflow_not_found")
    if parse(workflow.draft).definition is None:
        raise ValidationFailed(code="workflow_unreadable")
    if record_id is not None:
        kind = registered(workflow.record_type)
        visible = (
            kind is not None
            and kind.may_view is not None
            and await kind.may_view(session, subject, record_id)
        )
        facts = await kind.facts(session, record_id) if visible and kind and kind.facts else None
        if facts is None:  # gone, in the trash, another type's, or not theirs to see
            raise NotFound(code="record_not_found")
    else:
        facts = dict(sample or {})
        if len(facts) > SAMPLE_MAX_FIELDS:
            raise ValidationFailed(code="sample_too_large", params={"max": SAMPLE_MAX_FIELDS})
    definition = parse(workflow.draft).definition
    assert definition is not None  # noqa: S101 - checked just above
    run = WorkflowTestRun(
        tenant_id=workflow.tenant_id,
        workflow_id=workflow.id,
        record_type=workflow.record_type,
        record_id=record_id,
        definition=dict(workflow.draft),
        facts=dict(facts),
        state=workflow_runtime.dump(State.start(definition)),
        status="running",
        clock_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    await _advance(session, run, None)
    return run


async def _locked(
    session: AsyncSession, run_id: uuid.UUID, expected_version: int | None
) -> WorkflowTestRun:
    run = await session.get(WorkflowTestRun, run_id, with_for_update=True)
    if run is None:
        raise NotFound(code="workflow_test_run_not_found")
    if expected_version is not None and run.version != expected_version:
        raise Conflict(code="workflow_test_run_changed", params={"version": run.version})
    return run


def _take(run: WorkflowTestRun, command_id: str) -> dict[str, Any]:
    found = next((c for c in run.pending if c["id"] == command_id), None)
    if found is None:
        raise Conflict(code="command_not_pending")
    run.pending = [c for c in run.pending if c["id"] != command_id]
    return found


async def answer(  # noqa: PLR0913 - the answer, explicit
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    expected_version: int,
    command_id: str,
    ok: bool,
    port: str | None = None,
    error: str | None = None,
) -> WorkflowTestRun:
    """The admin's answer to a shown command: approved or rejected, done or failed (AC1)."""
    run = await _locked(session, run_id, expected_version)
    _take(run, command_id)
    await _advance(
        session,
        run,
        CommandDone(command_id, ok, error=error or (None if ok else "test_failed"), port=port),
    )
    return run


async def record_changed(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    expected_version: int,
    kind: WaitEvent,
    facts: Mapping[str, Any],
) -> WorkflowTestRun:
    """A change the admin describes: the run's facts take it, and its waits hear it."""
    run = await _locked(session, run_id, expected_version)
    run.facts = {**run.facts, **facts}
    await _advance(session, run, RecordChanged(kind))
    return run


async def fast_forward(
    session: AsyncSession, run_id: uuid.UUID, *, expected_version: int, seconds: int
) -> WorkflowTestRun:
    """Move the run's own clock on; the timers now due fire (AC3)."""
    if not 0 < seconds <= FAST_FORWARD_MAX:
        raise ValidationFailed(code="fast_forward_range", params={"max": FAST_FORWARD_MAX})
    run = await _locked(session, run_id, expected_version)
    run.clock_at = run.clock_at + timedelta(seconds=seconds)
    await _advance(session, run, TimerFired())
    return run


async def live_call(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    expected_version: int,
    command_id: str,
    by: uuid.UUID,
) -> WorkflowTestRun:
    """The one live call of the run, for a webhook or notify node (audited by the route)."""
    run = await _locked(session, run_id, expected_version)
    if run.live_call is not None:
        raise Conflict(code="live_call_used")
    found = next((c for c in run.pending if c["id"] == command_id), None)
    if found is None:
        raise Conflict(code="command_not_pending")
    kind = CommandKind(found["kind"])
    if kind not in LIVE_KINDS:
        raise ValidationFailed(code="live_call_not_allowed", params={"kind": kind.value})
    if run.record_id is None:  # a live call acts on a real record
        raise ValidationFailed(code="live_call_needs_record")
    run.live_call = {
        "command": command_id,
        "node": found["node"],
        "kind": kind.value,
        "by": str(by),
        "at": datetime.now(UTC).isoformat(),
    }
    # The command as the interpreter asked for it (what a real run would send); only the
    # headers, masked in `pending`, come back from the definition (lane B's review of #374).
    payload = dict(found["payload"])
    if kind is CommandKind.CALL_WEBHOOK:
        config = _definition(run).node(found["node"]).config
        payload["headers"] = dict(config.get("headers", {}))
    if kind is CommandKind.CALL_WEBHOOK:
        await record_event(
            session,
            WorkflowWebhookRequested(
                instance_id=run.id,
                command=command_id,
                record_type=run.record_type,
                record_id=run.record_id,
                url=str(payload.get("url")),
                method=str(payload.get("method", "POST")),
                headers={str(k): str(v) for k, v in dict(payload.get("headers", {})).items()},
                fields=[str(f) for f in payload.get("fields", [])],
                status_variable=payload.get("status_variable"),
                test_run=True,
            ),
            aggregate_id=run.id,
        )
        run.version += 1
        await session.flush()
        return run  # the worker's result answers the command (`apply_live_result`)
    result = await _notify_now(session, run, command_id, payload)
    _take(run, command_id)
    await _advance(
        session, run, CommandDone(command_id, result.ok, error=result.error, outputs=result.outputs)
    )
    return run


async def _notify_now(
    session: AsyncSession, run: WorkflowTestRun, command_id: str, payload: Mapping[str, Any]
) -> CommandResult:
    workflow = await session.get(Workflow, run.workflow_id)
    kind = registered(run.record_type)
    if workflow is None or kind is None or kind.run_command is None or run.record_id is None:
        return CommandResult(ok=False, error="command_not_supported")
    subject = await workflow_runtime.subject_of(session, workflow)
    if subject is None:
        return CommandResult(ok=False, error="workflow_identity_missing")
    ref = {
        "kind": "workflow",
        "workflow_id": str(workflow.id),
        "instance_id": str(run.id),
        "command": command_id,
        "test_run": True,
    }
    return await kind.run_command(
        session, subject, run.record_id, CommandKind.NOTIFY.value, payload, ref
    )


async def apply_live_result(  # noqa: PLR0913 - the worker's report, explicit
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    command: str,
    ok: bool,
    error: str | None,
    outputs: Mapping[str, Any],
) -> None:
    """The worker's report on a live webhook call answers its command in the run."""
    run = await _locked(session, run_id, None)
    if not any(c["id"] == command for c in run.pending):
        return  # already answered (at least once delivery)
    _take(run, command)
    await _advance(session, run, CommandDone(command, ok, error=error, outputs=dict(outputs)))
