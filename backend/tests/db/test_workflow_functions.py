"""The function node on a real incident (WP-048b S2; REQ-WF-021; architecture.md §6.7).

- The node never runs code in the API: it writes a request to the outbox and waits.
- The worker's consumer hands it to the registered runner, with the node's inputs (fixed values
  and record fields), and the node continues with the outputs kept as variables.
- With no runner (or no SANDBOX / CUSTOM_FUNCTIONS on the plan) the request is refused with a
  stable code, so the node takes its error output.
"""

import json
import uuid
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules import licensing
from app.modules.automation import FunctionOutcome, register_function_runner
from app.modules.automation.domain.rules import JsonValue
from app.modules.automation.infra.models import WorkflowInstance
from app.modules.automation.service import workflow_events
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import World, world
from tests.db.test_workflow_events import _node, _start, _status, _workflow

__all__ = ["world"]  # the fixture, re-used


FLOW: dict[str, Any] = {
    "format": 1,
    "nodes": [
        _node("s", "start"),
        _node(
            "fn",
            "function",
            function="score_risk",
            inputs={"subject": {"field": "subject"}, "weight": {"value": 3}},
            assign={"score": "risk_score"},
            timeout_seconds=5,
        ),
        _node("e", "end"),
        _node("bad", "end"),
    ],
    "links": [
        {"from": "s", "port": "next", "to": "fn"},
        {"from": "fn", "port": "next", "to": "e"},
        {"from": "fn", "port": "error", "to": "bad"},
    ],
    "variables": [{"name": "risk_score", "kind": "number"}],
}


class FakeRunner:
    """Records what it was asked and answers with a fixed score."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        *,
        tenant_id: uuid.UUID,
        function: str,
        inputs: Mapping[str, JsonValue],
        timeout_seconds: int,
    ) -> FunctionOutcome:
        self.calls.append(
            {
                "tenant": tenant_id,
                "function": function,
                "inputs": dict(inputs),
                "t": timeout_seconds,
            }
        )
        return FunctionOutcome(ok=True, outputs={"score": 42, "ignored": "not kept"})


@pytest.fixture
def entitled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """This test's plan has SANDBOX and CUSTOM_FUNCTIONS (the entitlement interface, rule f)."""

    async def has_feature(_tenant: uuid.UUID, _feature: object) -> bool:
        return True

    monkeypatch.setattr(licensing, "has_feature", has_feature)
    yield
    register_function_runner(None)


async def _deliver(world: World, event_type: str, instance_id: uuid.UUID) -> list[dict[str, Any]]:
    """Hand each outbox event of the instance to its consumer, as the worker does."""
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = $1 AND aggregate_id = $2"
        " ORDER BY id",
        event_type,
        str(instance_id),  # the outbox keeps aggregate ids as text
    )
    handler = {
        "automation.workflow.function_requested": workflow_events.on_function_requested,
        "automation.workflow.command_finished": workflow_events.on_command_finished,
    }[event_type]
    payloads = []
    for row in rows:
        envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await handler(envelope, session)
        payloads.append(dict(envelope.payload))
    return payloads


@pytest.mark.usefixtures("entitled")
async def test_req_wf_021_the_worker_runs_the_function_and_the_node_keeps_its_outputs(
    world: World,
) -> None:
    runner = FakeRunner()
    register_function_runner(runner)
    a = world.a
    item = await world.create(a, a.admin, subject="Mail is slow")
    instance = await _start(world, await _workflow(world, FLOW), item["id"])
    assert runner.calls == []  # nothing ran in the request
    assert await _status(world, instance) == "waiting"

    [asked] = await _deliver(world, "automation.workflow.function_requested", instance)
    assert asked["function"] == "score_risk"
    [call] = runner.calls
    assert call["inputs"] == {"subject": "Mail is slow", "weight": 3}
    assert (call["function"], call["t"], call["tenant"]) == ("score_risk", 5, a.tenant)

    [finished] = await _deliver(world, "automation.workflow.command_finished", instance)
    assert finished["outputs"] == {"risk_score": 42}  # only what the node keeps
    assert await _status(world, instance) == "finished"
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        found = await session.get(WorkflowInstance, instance)
        assert found is not None
        assert found.state["variables"]["risk_score"] == 42


@pytest.mark.usefixtures("entitled")
async def test_without_a_runner_the_request_is_refused_and_the_node_takes_its_error(
    world: World,
) -> None:
    register_function_runner(None)
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, FLOW), item["id"])
    await _deliver(world, "automation.workflow.function_requested", instance)
    [finished] = await _deliver(world, "automation.workflow.command_finished", instance)
    assert (finished["ok"], finished["error"]) == (False, "function_not_offered")
    steps = await world.sql(
        "SELECT node, result FROM workflow_steps WHERE instance_id = $1", instance
    )
    assert ("fn", "error") in {(s["node"], s["result"]) for s in steps}
