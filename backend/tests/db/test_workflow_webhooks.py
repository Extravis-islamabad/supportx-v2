"""The webhook node on a real incident (WP-048b S2; REQ-WF-020; ADR-043 §8).

- The node never calls out from the request: it writes a request to the outbox and waits.
- The worker's consumer makes one call through the shared guarded client (stubbed here: the
  client has its own tests), with the record's chosen fields read now, the node's headers and
  an idempotency key per instance and command; a 2xx continues the node, its status kept.
- A refused or failed call takes the node's error output, with a stable code.
"""

import json
import uuid
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import WorkflowInstance
from app.modules.automation.service import workflow_events
from app.shared import egress
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import World, world
from tests.db.test_workflow_events import _node, _start, _status, _workflow

__all__ = ["world"]  # the fixture, re-used

URL = "https://hooks.example.test/supportx"

FLOW: dict[str, Any] = {
    "format": 1,
    "nodes": [
        _node("s", "start"),
        _node(
            "call",
            "webhook",
            url=URL,
            headers={"X-Team": "network"},
            fields=["subject", "priority"],
            status_variable="answer",
        ),
        _node("e", "end"),
        _node("bad", "end"),
    ],
    "links": [
        {"from": "s", "port": "next", "to": "call"},
        {"from": "call", "port": "next", "to": "e"},
        {"from": "call", "port": "error", "to": "bad"},
    ],
    "variables": [{"name": "answer", "kind": "number"}],
}


class Sent:
    """What the stubbed client was asked, and what it answers."""

    def __init__(self, *, refuse: str | None = None) -> None:
        self.requests: list[egress.OutboundRequest] = []
        self.refuse = refuse

    async def __call__(
        self,
        request: egress.OutboundRequest,
        **_bounds: Any,  # noqa: ANN401 - the client's own keywords
    ) -> egress.OutboundResponse:
        self.requests.append(request)
        if self.refuse is not None:
            raise egress.EgressError(self.refuse)
        return egress.OutboundResponse(status=202, headers=(), body=b"")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Sent:
    found = Sent()
    monkeypatch.setattr(egress, "send", found)
    return found


async def _deliver(world: World, event_type: str, instance_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = $1 AND aggregate_id = $2"
        " ORDER BY id",
        event_type,
        str(instance_id),  # the outbox keeps aggregate ids as text
    )
    handler = {
        "automation.workflow.webhook_requested": workflow_events.on_webhook_requested,
        "automation.workflow.command_finished": workflow_events.on_command_finished,
    }[event_type]
    payloads = []
    for row in rows:
        envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
        async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
            await handler(envelope, session)
        payloads.append(dict(envelope.payload))
    return payloads


async def test_req_wf_020_the_worker_makes_the_call_and_the_node_keeps_its_status(
    world: World, sent: Sent
) -> None:
    a = world.a
    item = await world.create(a, a.admin, subject="VPN down")
    instance = await _start(world, await _workflow(world, FLOW), item["id"])
    assert sent.requests == []  # nothing left the platform during the request
    assert await _status(world, instance) == "waiting"

    [asked] = await _deliver(world, "automation.workflow.webhook_requested", instance)
    assert asked["fields"] == ["subject", "priority"]  # names only in the outbox
    [request] = sent.requests
    assert (request.method, request.url) == ("POST", URL)
    assert request.headers["X-Team"] == "network"
    assert request.headers["Idempotency-Key"] == f"{instance}:{asked['command']}"
    body = json.loads(request.body)
    assert body["record"] == {"type": "incident", "id": item["id"]}
    assert body["fields"]["subject"] == "VPN down"
    assert set(body["fields"]) == {"subject", "priority"}

    [finished] = await _deliver(world, "automation.workflow.command_finished", instance)
    assert finished["outputs"] == {"answer": 202}
    assert await _status(world, instance) == "finished"
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        found = await session.get(WorkflowInstance, instance)
        assert found is not None
        assert found.state["variables"]["answer"] == 202


async def test_a_refused_call_takes_the_error_output_with_a_stable_code(
    world: World, sent: Sent
) -> None:
    sent.refuse = "blocked"  # e.g. an address the installation does not allow
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, FLOW), item["id"])
    await _deliver(world, "automation.workflow.webhook_requested", instance)
    [finished] = await _deliver(world, "automation.workflow.command_finished", instance)
    assert (finished["ok"], finished["error"]) == (False, "webhook_blocked")
    steps = await world.sql(
        "SELECT node, result FROM workflow_steps WHERE instance_id = $1", instance
    )
    assert ("call", "error") in {(s["node"], s["result"]) for s in steps}
