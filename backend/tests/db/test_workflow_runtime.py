"""Running workflow instances against real PostgreSQL (WP-048b S1, ADR-043 §3-6).

The record type's facts and `run_command` are stand-ins here (the work_items side has its own
tests); the runtime's own behaviour is real:
- a start runs the instance as far as it goes, logs every step and writes the outbox event in the
  same transaction (rule b);
- a second start while one is live is refused with a reason (REQ-WF-010 AC2); a disabled
  workflow starts nothing (AC3);
- a refused command takes the node's error output, and without one the instance stops there
  (REQ-WF-024);
- a waiting instance moves on when its record changes (REQ-WF-012 AC1);
- without its run-as identity a workflow runs no command at all (ADR-043 §6);
- calling `run` again changes nothing (ADR-043 §5).
"""

import dataclasses
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.errors import Conflict
from app.core.tenancy import TenantContext
from app.modules.automation.domain.interpreter import RecordChanged
from app.modules.automation.domain.workflows import WaitEvent
from app.modules.automation.infra.models import (
    Workflow,
    WorkflowInstance,
    WorkflowStep,
    WorkflowVersion,
)
from app.modules.automation.service import registry, workflow_runtime
from app.modules.automation.service.registry import CommandResult
from tests.db.test_incidents_api import World, world

__all__ = ["world"]  # the fixture, re-used


class FakeRecords:
    """Facts per record and a log of commands; refuses the actions it is told to refuse."""

    def __init__(self) -> None:
        self.facts: dict[uuid.UUID, dict[str, Any]] = {}
        self.ran: list[tuple[uuid.UUID, str, dict[str, Any], dict[str, Any]]] = []
        self.refuse: set[str] = set()

    async def read(self, _session: Any, record_id: uuid.UUID) -> Mapping[str, Any] | None:  # noqa: ANN401 - the port's session
        return self.facts.get(record_id)

    async def command(
        self,
        _session: Any,  # noqa: ANN401 - the port's session
        _subject: Any,  # noqa: ANN401 - the port's subject
        record_id: uuid.UUID,
        kind: str,
        payload: Mapping[str, Any],
        ref: Mapping[str, Any],
    ) -> CommandResult:
        self.ran.append((record_id, kind, dict(payload), dict(ref)))
        if payload.get("action") in self.refuse:
            return CommandResult(ok=False, error="transition_not_allowed")
        if kind == "move":
            self.facts[record_id] = {**self.facts[record_id], "status": "in_progress"}
        return CommandResult(ok=True)


@pytest_asyncio.fixture
async def records() -> AsyncIterator[FakeRecords]:
    fake = FakeRecords()
    current = registry.record_type("incident")
    assert current is not None
    registry.register_record_type(
        dataclasses.replace(current, facts=fake.read, run_command=fake.command)
    )
    yield fake
    registry.register_record_type(current)


def _node(node_id: str, kind: str, **config: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"id": node_id, "type": kind, "config": config, "position": {"x": 0, "y": 0}}


MOVE_THEN_WAIT = {
    "format": 1,
    "nodes": [
        _node("s", "start"),
        _node("mv", "set_status", action="start_work"),
        _node(
            "w",
            "wait",
            events=["field_changed"],
            condition={"field": "priority", "op": "eq", "value": "p1"},
        ),
        _node("e", "end"),
        _node("over", "end"),
    ],
    "links": [
        {"from": "s", "port": "next", "to": "mv"},
        {"from": "mv", "port": "next", "to": "w"},
        {"from": "w", "port": "next", "to": "e"},
        {"from": "w", "port": "overtaken", "to": "over"},
    ],
    "variables": [],
}


async def _workflow(
    world: World,
    definition: dict[str, Any],
    *,
    enabled: bool = True,
    identity: bool = True,
) -> uuid.UUID:
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        workflow = Workflow(
            tenant_id=a.tenant,
            record_type="incident",
            name=f"Flow {uuid.uuid4().hex[:6]}",
            draft=definition,
            enabled=enabled,
            service_identity_id=a.admin if identity else None,
            published_version=1,
        )
        session.add(workflow)
        await session.flush()
        session.add(
            WorkflowVersion(
                tenant_id=a.tenant, workflow_id=workflow.id, number=1, definition=definition
            )
        )
        return workflow.id


async def _start(world: World, workflow_id: uuid.UUID, record_id: uuid.UUID) -> uuid.UUID:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        instance = await workflow_runtime.start(
            session,
            workflow_id=workflow_id,
            record_type="incident",
            record_id=record_id,
            how="manual",
        )
        return instance.id


async def _instance(world: World, instance_id: uuid.UUID) -> tuple[WorkflowInstance, list[str]]:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        instance = await session.get(WorkflowInstance, instance_id)
        assert instance is not None
        steps = await session.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.instance_id == instance_id)
            .order_by(WorkflowStep.seq)
        )
        return instance, [f"{s.node}:{s.result}" for s in steps]


async def test_a_start_runs_until_it_waits_logs_its_steps_and_writes_the_outbox(
    world: World, records: FakeRecords
) -> None:
    record = uuid.uuid4()
    records.facts[record] = {"status": "open", "priority": "p3"}
    flow = await _workflow(world, MOVE_THEN_WAIT)
    instance_id = await _start(world, flow, record)
    instance, steps = await _instance(world, instance_id)
    assert instance.status == "waiting"
    assert steps == ["s:next", "mv:command", "mv:next", "w:waiting"]
    [(_record, kind, payload, ref)] = records.ran
    assert (kind, payload) == ("move", {"action": "start_work"})
    assert ref == {
        "kind": "workflow",
        "workflow_id": str(flow),
        "instance_id": str(instance_id),
    }
    events = await world.sql(  # the relay's table: read as the superuser (the app may only add)
        "SELECT count(*) AS n FROM outbox_events WHERE event_type = "
        "'automation.workflow_instance.changed' AND aggregate_id = $1",
        str(instance_id),
    )
    assert events[0]["n"] == 1


async def test_req_wf_010_a_second_start_is_refused_and_a_disabled_workflow_starts_nothing(
    world: World, records: FakeRecords
) -> None:
    record = uuid.uuid4()
    records.facts[record] = {"status": "open", "priority": "p3"}
    flow = await _workflow(world, MOVE_THEN_WAIT)
    await _start(world, flow, record)
    with pytest.raises(Conflict) as again:
        await _start(world, flow, record)
    assert again.value.instance_code == "workflow_already_running"
    off = await _workflow(world, MOVE_THEN_WAIT, enabled=False)
    with pytest.raises(Conflict) as disabled:
        await _start(world, off, record)
    assert disabled.value.instance_code == "workflow_disabled"


async def test_req_wf_012_ac1_a_waiting_instance_moves_on_when_its_record_changes(
    world: World, records: FakeRecords
) -> None:
    record = uuid.uuid4()
    records.facts[record] = {"status": "open", "priority": "p3"}
    instance_id = await _start(world, await _workflow(world, MOVE_THEN_WAIT), record)
    records.facts[record] = {**records.facts[record], "priority": "p1"}
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await workflow_runtime.run(session, instance_id, RecordChanged(WaitEvent.FIELD_CHANGED))
    instance, steps = await _instance(world, instance_id)
    assert instance.status == "finished"
    assert steps[-2:] == ["w:next", "e:finished"]
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await workflow_runtime.run(session, instance_id, None) is None  # ended: no-op
    assert (await _instance(world, instance_id))[1] == steps


async def test_req_wf_024_a_refused_move_without_an_error_output_stops_the_instance(
    world: World, records: FakeRecords
) -> None:
    record = uuid.uuid4()
    records.facts[record] = {"status": "open", "priority": "p3"}
    records.refuse.add("start_work")
    instance_id = await _start(world, await _workflow(world, MOVE_THEN_WAIT), record)
    instance, steps = await _instance(world, instance_id)
    assert instance.status == "failed"
    assert instance.failure == {"node": "mv", "code": "transition_not_allowed", "params": {}}
    assert steps[-1] == "mv:failed"


async def test_without_its_run_as_identity_a_workflow_runs_no_command(
    world: World, records: FakeRecords
) -> None:
    record = uuid.uuid4()
    records.facts[record] = {"status": "open", "priority": "p3"}
    flow = await _workflow(world, MOVE_THEN_WAIT, identity=False)
    instance, _steps = await _instance(world, await _start(world, flow, record))
    assert records.ran == []
    assert instance.status == "failed"
    assert instance.failure is not None
    assert instance.failure["code"] == "workflow_identity_missing"
