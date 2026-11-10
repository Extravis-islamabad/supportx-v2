"""Running workflow instances (WP-048b S1, ADR-043 §3-6).

PostgreSQL holds an instance's state; this service moves it on, in the caller's transaction:
- `start` makes an instance of a workflow's published version on one record (REQ-WF-010);
- `run` applies one event (a record change, a timer, None to just continue), runs the
  interpreter, carries out the commands it asks for through the record type's `run_command`
  (the owning module's public services, as the workflow's own identity) and feeds their results
  back, until nothing more can move. It writes the steps, the state and the outbox event in the
  same transaction.

Temporal and the outbox consumer only decide *when* `run` is called (ADR-043 §5): it is safe to
call twice, since a step already written is never written again and a command result already
applied changes nothing.

A workflow without its run-as identity (ADR-043 §6) runs no command at all: each one fails with
`workflow_identity_missing`, so nothing ever happens with more rights than the workflow holds.
"""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict, NotFound
from app.modules.automation.domain.interpreter import (
    Clock,
    Command,
    CommandDone,
    CommandKind,
    Event,
    Failure,
    Group,
    InstanceStatus,
    State,
    Token,
    TokenState,
    advance,
)
from app.modules.automation.domain.rules import JsonValue
from app.modules.automation.domain.workflows import Definition, TimeBasis, parse
from app.modules.automation.events import WorkflowInstanceChanged
from app.modules.automation.infra.models import (
    Workflow,
    WorkflowInstance,
    WorkflowStep,
    WorkflowVersion,
)
from app.modules.automation.service.registry import CommandResult
from app.modules.automation.service.registry import record_type as registered
from app.modules.identity_access import Subject, subject_for
from app.modules.sla import record_calendar
from app.shared.events import caused_by, record_event

LIVE = (InstanceStatus.RUNNING.value, InstanceStatus.WAITING.value, InstanceStatus.FAILED.value)
_ENDED = {InstanceStatus.FINISHED, InstanceStatus.CANCELLED}
# Commands one `run` may carry out before it stops to let the waker call again: a guard against a
# definition that loops through actions without waiting (the step limit catches the rest).
COMMANDS_PER_RUN = 200


def _token_json(token: Token) -> dict[str, Any]:
    return {
        "id": token.id,
        "node": token.node,
        "state": token.state.value,
        "groups": [[g.split, g.run, g.branch] for g in token.groups],
        "rounds": token.rounds,
        "wake_at": token.wake_at.isoformat() if token.wake_at else None,
        "command": token.command,
        "attempts": token.attempts,
        "retrying": token.retrying,
    }


def dump(state: State) -> dict[str, Any]:
    """The interpreter's state as stored JSON."""
    return {
        "tokens": [_token_json(t) for t in state.tokens],
        "variables": state.variables,
        "steps": state.steps,
        "next_id": state.next_id,
        "split_runs": state.split_runs,
        "joins": state.joins,
    }


def load(raw: Mapping[str, Any], status: str, failure: Mapping[str, Any] | None) -> State:
    """The stored JSON back as the interpreter's state."""
    tokens = [
        Token(
            id=str(t["id"]),
            node=str(t["node"]),
            state=TokenState(t["state"]),
            groups=tuple(Group(str(g[0]), int(g[1]), str(g[2])) for g in t.get("groups", [])),
            rounds={str(k): int(v) for k, v in dict(t.get("rounds", {})).items()},
            wake_at=datetime.fromisoformat(t["wake_at"]) if t.get("wake_at") else None,
            command=t.get("command"),
            attempts=int(t.get("attempts", 0)),
            retrying=bool(t.get("retrying", False)),
        )
        for t in raw.get("tokens", [])
    ]
    return State(
        tokens=tokens,
        variables=dict(raw.get("variables", {})),
        steps=int(raw.get("steps", 0)),
        status=InstanceStatus(status),
        failure=Failure(str(failure["node"]), str(failure["code"]), dict(failure.get("params", {})))
        if failure
        else None,
        next_id=int(raw.get("next_id", 1)),
        split_runs=int(raw.get("split_runs", 0)),
        joins={str(k): [str(x) for x in v] for k, v in dict(raw.get("joins", {})).items()},
    )


def _uses_business_time(definition: Definition) -> bool:
    return any(n.config.get("basis") == TimeBasis.BUSINESS.value for n in definition.nodes)


async def _clock(session: AsyncSession, definition: Definition, record_id: uuid.UUID) -> Clock:
    """Calendar time, and business time on the record's own calendar (sla, REQ-WF-013 AC2)."""
    calendar = (
        await record_calendar(session, record_id) if _uses_business_time(definition) else None
    )

    def clock(start: datetime, seconds: int, basis: TimeBasis) -> datetime:
        if basis == TimeBasis.BUSINESS and calendar is not None:
            return calendar.add(start, seconds)
        return start + timedelta(seconds=seconds)

    return clock


async def _subject(session: AsyncSession, workflow: Workflow) -> Subject | None:
    if workflow.service_identity_id is None:
        return None
    return await subject_for(session, workflow.tenant_id, workflow.service_identity_id)


async def start(  # noqa: PLR0913 - the workflow, the record and how it started, explicit
    session: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    record_type: str,
    record_id: uuid.UUID,
    how: str,
    now: datetime | None = None,
    parent: tuple[uuid.UUID, str] | None = None,
) -> WorkflowInstance:
    """A new instance on the record, run as far as it goes (REQ-WF-010).

    `parent` is the instance and command of the sub-flow node that starts this one (REQ-WF-017):
    if the child ends at once, the parent's own run reads that from the returned instance; if it
    ends later, its run tells the parent.
    """
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None or workflow.deleted_at is not None:
        raise NotFound(code="workflow_not_found")
    if workflow.record_type != record_type:
        raise Conflict(code="workflow_wrong_record_type", params={"type": workflow.record_type})
    if not workflow.enabled:
        raise Conflict(code="workflow_disabled")  # AC3: disabled stops new starts
    if workflow.published_version is None:
        raise Conflict(code="workflow_not_published")
    running = await session.scalar(
        select(WorkflowInstance.id).where(
            WorkflowInstance.workflow_id == workflow_id,
            WorkflowInstance.record_id == record_id,
            WorkflowInstance.status.in_(LIVE),
        )
    )
    if running is not None:  # AC2: refused with a reason
        raise Conflict(code="workflow_already_running", params={"instance_id": str(running)})
    version = await session.get(
        WorkflowVersion, (workflow.tenant_id, workflow.id, workflow.published_version)
    )
    if version is None:
        raise Conflict(code="workflow_not_published")
    definition = _definition(version)
    moment = now or datetime.now(UTC)
    instance = WorkflowInstance(
        tenant_id=workflow.tenant_id,
        workflow_id=workflow.id,
        version_number=version.number,
        record_type=record_type,
        record_id=record_id,
        status=InstanceStatus.RUNNING.value,
        state=dump(State.start(definition)),
        started_how=how,
        started_at=moment,
        parent_instance_id=parent[0] if parent else None,
        parent_command=parent[1] if parent else None,
    )
    session.add(instance)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as error:  # a start racing this one won (the partial unique index)
        raise Conflict(code="workflow_already_running") from error
    await run(session, instance.id, None, now=moment, tell_parent=parent is None)
    return instance


def _definition(version: WorkflowVersion) -> Definition:
    parsed = parse(version.definition)
    if parsed.definition is None:  # a published version always parses; anything else is a bug
        msg = f"workflow version {version.workflow_id}/{version.number} does not parse"
        raise RuntimeError(msg)
    return parsed.definition


async def run(
    session: AsyncSession,
    instance_id: uuid.UUID,
    event: Event | None,
    *,
    now: datetime | None = None,
    tell_parent: bool = True,
) -> WorkflowInstance | None:
    """Apply `event` and carry the instance as far as it goes; None: no such live instance.

    A sub-flow child that ends (or fails) here continues its parent with the result, unless the
    parent is the one starting it right now (`tell_parent=False`).
    """
    instance = await session.get(WorkflowInstance, instance_id, with_for_update=True)
    if instance is None or instance.status not in LIVE:
        return None
    moment = now or datetime.now(UTC)
    workflow = await session.get(Workflow, instance.workflow_id)
    version = await session.get(
        WorkflowVersion, (instance.tenant_id, instance.workflow_id, instance.version_number)
    )
    if workflow is None or version is None:  # the foreign keys forbid it
        msg = f"workflow instance {instance.id} without its workflow or version"
        raise RuntimeError(msg)
    definition = _definition(version)
    kind = registered(instance.record_type)
    facts = await kind.facts(session, instance.record_id) if kind and kind.facts else None
    state = load(instance.state, instance.status, instance.failure)
    if facts is None:  # the record is gone or in the trash: nothing left to run on
        state.status = InstanceStatus.CANCELLED
        await _save(session, instance, state, steps=[], wake=None, now=moment, reason="record_gone")
        return instance
    clock = await _clock(session, definition, instance.record_id)
    subject = await _subject(session, workflow)
    ref = {"kind": "workflow", "workflow_id": str(workflow.id), "instance_id": str(instance.id)}
    queue: list[Event | None] = [event]
    steps: list[Any] = []
    done = 0
    wake: datetime | None = None
    while queue:
        result = advance(definition, state, facts, queue.pop(0), now=moment, clock=clock)
        state, wake = result.state, result.wake_at
        steps += result.steps
        for command in result.commands:
            if done >= COMMANDS_PER_RUN:
                break
            done += 1
            found = await _result_of(session, instance, kind, subject, command, ref, moment)
            if found is not None:  # None: a sub-flow's child runs on; its end continues this
                queue.append(found)
        if result.commands and kind is not None and kind.facts is not None:
            facts = await kind.facts(session, instance.record_id) or facts  # the changes made
    await _save(session, instance, state, steps=steps, wake=wake, now=moment)
    if tell_parent:
        await _tell_parent(session, instance, moment)
    return instance


async def _result_of(  # noqa: PLR0913, PLR0917 - one command and what it runs with
    session: AsyncSession,
    instance: WorkflowInstance,
    kind: Any,  # noqa: ANN401 - the registry's RecordType (or None)
    subject: Subject | None,
    command: Command,
    ref: Mapping[str, Any],
    now: datetime,
) -> CommandDone | None:
    if command.kind == CommandKind.START_SUB_FLOW:
        return await _start_child(session, instance, command, now)
    outcome = await _carry_out(
        session,
        kind,
        subject=subject,
        record_id=instance.record_id,
        command=command,
        # The command's own id: a result that comes later (an approval's decision) names it.
        ref={**ref, "command": command.id},
    )
    if outcome.ok and outcome.pending:
        return None  # waits, as a sub-flow does, until the owning module's event continues it
    return CommandDone(command.id, outcome.ok, error=outcome.error, outputs=outcome.outputs)


def _child_result(child: WorkflowInstance, command: str) -> CommandDone | None:
    """The parent's command result from its child's status; None while the child runs."""
    if child.status == InstanceStatus.FINISHED.value:
        return CommandDone(command, ok=True)
    if child.status in {InstanceStatus.FAILED.value, InstanceStatus.CANCELLED.value}:
        return CommandDone(command, ok=False, error="sub_flow_failed")
    return None


async def _start_child(
    session: AsyncSession, parent: WorkflowInstance, command: Command, now: datetime
) -> CommandDone | None:
    """Start a sub-flow's child on the same record (REQ-WF-017); a refusal is the result."""
    try:
        async with session.begin_nested():
            child = await start(
                session,
                workflow_id=uuid.UUID(str(command.payload.get("workflow_id"))),
                record_type=parent.record_type,
                record_id=parent.record_id,
                how="sub_flow",
                now=now,
                parent=(parent.id, command.id),
            )
    except AppError as refused:  # gone, switched off, already running ...: the node decides
        return CommandDone(command.id, ok=False, error=refused.instance_code)
    return _child_result(child, command.id)


async def _tell_parent(session: AsyncSession, child: WorkflowInstance, now: datetime) -> None:
    """A child that ended continues its parent's sub-flow node with the result."""
    if child.parent_instance_id is None or child.parent_command is None:
        return
    result = _child_result(child, child.parent_command)
    if result is not None:
        await run(session, child.parent_instance_id, result, now=now)


async def _carry_out(  # noqa: PLR0913 - the command and everything it runs with, explicit
    session: AsyncSession,
    kind: Any,  # noqa: ANN401 - the registry's RecordType (or None)
    *,
    subject: Subject | None,
    record_id: uuid.UUID,
    command: Command,
    ref: Mapping[str, Any],
) -> CommandResult:
    """One command through the owning module, in a savepoint so a refusal keeps the rest."""
    if subject is None:
        return CommandResult(ok=False, error="workflow_identity_missing")
    if kind is None or kind.run_command is None:
        return CommandResult(ok=False, error="command_not_supported")
    savepoint = await session.begin_nested()
    # The record's events name the instance as their cause: a trigger's "start a workflow"
    # then never restarts the workflow from its own change (lane A's loop guard).
    with caused_by(session, uuid.UUID(str(ref["instance_id"]))):
        result: CommandResult = await kind.run_command(
            session, subject, record_id, command.kind.value, command.payload, ref
        )
    if result.ok:
        await savepoint.commit()
    else:  # whatever the refused command wrote is undone; the refusal is the result
        await savepoint.rollback()
    return result


async def _save(  # noqa: PLR0913 - the instance and everything a run produced, explicit
    session: AsyncSession,
    instance: WorkflowInstance,
    state: State,
    *,
    steps: list[Any],
    wake: datetime | None,
    now: datetime,
    reason: str | None = None,
) -> None:
    """Steps (continuing the sequence), the state, the status and the outbox event."""
    last = await session.scalar(
        select(func.coalesce(func.max(WorkflowStep.seq), 0)).where(
            WorkflowStep.instance_id == instance.id
        )
    )
    for seq, item in enumerate(steps, start=int(last or 0) + 1):
        session.add(
            WorkflowStep(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                seq=seq,
                token=item.token,
                node=item.node,
                node_type=item.node_type.value,
                result=item.result,
                at=item.at,
                detail=_detail(item.detail),
            )
        )
    instance.state = dump(state)
    instance.status = state.status.value
    instance.failure = (
        {"node": state.failure.node, "code": state.failure.code, "params": state.failure.params}
        if state.failure
        else None
    )
    instance.wake_at = wake
    if state.status in _ENDED or state.status == InstanceStatus.FAILED:
        instance.wake_at = None
    if state.status in _ENDED:
        instance.finished_at = now
        instance.stopped_reason = reason
    instance.version += 1
    await session.flush()
    await record_event(
        session,
        WorkflowInstanceChanged(
            instance_id=instance.id,
            workflow_id=instance.workflow_id,
            record_type=instance.record_type,
            record_id=instance.record_id,
            status=state.status.value,
            version=instance.version,
        ),
        aggregate_id=instance.id,
        aggregate_version=instance.version,
    )


def _detail(detail: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    return dict(detail) if detail else None
