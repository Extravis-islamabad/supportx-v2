"""Test mode (WP-048b S3e; REQ-WF-022): a workflow's draft runs, and nothing is applied.

- An approval node waits for the admin's answer; choosing "approved" shows the path (AC1).
- A test run writes nothing to the record, sends no notification and touches no outbox (AC2).
- Timers move on when the admin moves the run's own clock forward (AC3).
- One live call per run, for a webhook or notify node, on a record, audited with the node and
  the record; a webhook still goes from the worker, and its result answers the run.
"""

import json
import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.automation.service import workflow_events
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import CONSOLE, World, role, world
from tests.db.test_workflow_approvals import _approval, _release_flow
from tests.db.test_workflow_events import TIMER, _node, _workflow
from tests.db.test_workflow_webhooks import FLOW as WEBHOOK
from tests.db.test_workflow_webhooks import Sent, sent

__all__ = ["sent", "world"]  # the fixtures, re-used

BASE = "/automation/workflows"


async def _start_test(world: World, flow: uuid.UUID, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    made = await world.call(
        "POST",
        f"{BASE}/{flow}/test-runs",
        world.a,
        world.a.admin,
        json=body,
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _post(world: World, run: dict[str, Any], verb: str, **body: Any) -> Any:  # noqa: ANN401 - response
    return await world.call(
        "POST",
        f"{BASE}/test-runs/{run['id']}/{verb}",
        world.a,
        world.a.admin,
        json=body,
        headers={"If-Match": f'"{run["version"]}"', **CONSOLE},
    )


async def _outbox_count(world: World) -> int:
    rows = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1", world.a.tenant
    )
    return int(rows[0]["n"])


async def test_req_wf_022_ac1_the_admin_answers_an_approval_and_sees_the_path(world: World) -> None:
    a = world.a
    flow = await _release_flow(world, _approval(a.tech_a))
    run = await _start_test(world, flow, sample={"status": "planning"})
    [shown] = run["pending"]
    assert shown["kind"] == "open_approval"
    answered = await _post(world, run, "answer", command_id=shown["id"], ok=True, port="approved")
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert (body["status"], body["pending"]) == ("finished", [])
    assert ("ask", "approved") in {(s["node"], s["result"]) for s in body["steps"]}
    rows = await world.sql(
        "SELECT count(*) AS n FROM work_item_approvals WHERE tenant_id = $1", a.tenant
    )
    assert rows[0]["n"] == 0  # nothing was opened on any record


def _notify_and_set() -> dict[str, Any]:
    return {
        "format": 1,
        "nodes": [
            _node("s", "start"),
            _node(
                "tell",
                "notify",
                audience={"relatives": ["requester"]},
                subject={"en": "Hi"},
                body={"en": "Hello"},
            ),
            _node("set", "field_update", values={"impact": "team"}),
            _node("e", "end"),
        ],
        "links": [
            {"from": "s", "port": "next", "to": "tell"},
            {"from": "tell", "port": "next", "to": "set"},
            {"from": "set", "port": "next", "to": "e"},
        ],
        "variables": [],
    }


async def test_req_wf_022_ac2_a_test_run_writes_nothing_and_sends_nothing(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    before_history = await world.history(a, item)
    before_outbox = await _outbox_count(world)
    flow = await _workflow(world, _notify_and_set())
    run = await _start_test(world, flow, record_id=item["id"])
    [notice] = run["pending"]
    assert notice["kind"] == "notify"
    run = (await _post(world, run, "answer", command_id=notice["id"], ok=True)).json()
    [field_step] = run["pending"]
    assert field_step["kind"] == "update_fields"
    done = (await _post(world, run, "answer", command_id=field_step["id"], ok=True)).json()
    assert done["status"] == "finished"
    fresh = await world.fresh(a, item)
    assert fresh["impact"] != "team"  # shown, never applied
    assert await world.history(a, item) == before_history
    assert await _outbox_count(world) == before_outbox  # no notice, no event, nothing


async def test_req_wf_022_ac3_timers_move_on_with_the_run_s_own_clock(world: World) -> None:
    flow = await _workflow(world, TIMER)
    run = await _start_test(world, flow, sample={})
    assert run["status"] == "waiting"
    early = await _post(world, run, "answer", fast_forward_seconds=30)
    assert early.json()["status"] == "waiting"  # not due yet
    late = await _post(world, early.json(), "answer", fast_forward_seconds=40)
    assert late.json()["status"] == "finished"


async def test_the_one_live_call_goes_through_the_worker_and_answers_the_run(
    world: World, sent: Sent
) -> None:
    a = world.a
    item = await world.create(a, a.admin, subject="VPN down")
    flow = await _workflow(world, WEBHOOK)
    run = await _start_test(world, flow, record_id=item["id"])
    [call] = run["pending"]
    assert call["kind"] == "call_webhook"
    assert call["payload"]["headers"] == {"X-Team": "•••"}  # never a header's value
    live = await _post(world, run, "live-call", command_id=call["id"])
    assert live.status_code == 200, live.text
    assert sent.requests == []  # never from the request
    again = await _post(world, live.json(), "live-call", command_id=call["id"])
    assert again.status_code == 409
    assert again.json()["code"] == "live_call_used"
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = $1 AND aggregate_id = $2",
        "automation.workflow.webhook_requested",
        run["id"],
    )
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    assert envelope.payload["test_run"] is True
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await workflow_events.on_webhook_requested(envelope, session)
    [request] = sent.requests
    assert request.headers["X-Team"] == "network"  # the real value, from the definition
    got = await world.call("GET", f"{BASE}/test-runs/{run['id']}", a, a.admin)
    assert (got.json()["status"], got.json()["variables"]) == ("finished", {"answer": 202})
    audited = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        "automation.workflow_test_live_call",
    )
    details = (
        json.loads(audited[0]["details"])
        if isinstance(audited[0]["details"], str)
        else audited[0]["details"]
    )
    assert (details["node"], details["record_id"]) == ("call", item["id"])


async def test_a_live_call_needs_a_record_and_a_webhook_or_notify_node(world: World) -> None:
    flow = await _workflow(world, WEBHOOK)
    run = await _start_test(world, flow, sample={"subject": "x"})
    [call] = run["pending"]
    refused = await _post(world, run, "live-call", command_id=call["id"])
    assert refused.status_code == 422
    assert refused.json()["code"] == "live_call_needs_record"
    other = await _workflow(world, _notify_and_set())
    run2 = await _start_test(world, other, sample={})
    [notice] = run2["pending"]
    run2 = (await _post(world, run2, "answer", command_id=notice["id"], ok=True)).json()
    [field_step] = run2["pending"]
    not_allowed = await _post(world, run2, "live-call", command_id=field_step["id"])
    assert not_allowed.status_code == 422
    assert not_allowed.json()["code"] == "live_call_not_allowed"


async def test_a_test_run_on_a_record_needs_the_right_to_see_it(world: World) -> None:
    """workflows.manage alone never shows a record's values (lane B's review of #374)."""
    a = world.a
    designer = await role(world, a, "Workflow designer", [("workflows.manage", "all")])
    assigned = await world.call("PUT", f"/users/{a.tech_b}/roles/{designer}", a, a.admin)
    assert assigned.status_code in {200, 204}, assigned.text
    item = await world.create(a, a.admin, group_id=str(a.ga))  # GA's: tech_b is in GB
    assert (await world.get(a, a.tech_b, item)).status_code == 404
    flow = await _workflow(world, _notify_and_set())
    refused = await world.call(
        "POST",
        f"{BASE}/{flow}/test-runs",
        a,
        a.tech_b,
        json={"record_id": item["id"]},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert refused.status_code == 404, refused.text
    assert refused.json()["code"] == "record_not_found"
    rows = await world.sql(
        "SELECT count(*) AS n FROM workflow_test_runs WHERE tenant_id = $1", a.tenant
    )
    assert rows[0]["n"] == 0
