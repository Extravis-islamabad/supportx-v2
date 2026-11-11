"""Stop, restart and retry a workflow on a record (WP-048b S3a; REQ-WF-025 AC2, REQ-WF-026).

- Stop asks for a reason, keeps the log, is audited, and closes the workflow's open approvals.
- Restart runs from the start or from a chosen node, on the instance's own version.
- Retry runs a failed instance's failed node again.
- Each needs workflows.run and the right to edit the record (ADR-043 §10).
- A cancelled record's workflows stop with it.
"""

import json
import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.automation.service import workflow_events
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import CONSOLE, Org, World, role, world
from tests.db.test_releases_api import moved
from tests.db.test_workflow_approvals import _approval, _release_flow, _started
from tests.db.test_workflow_events import WAIT_FOR_P1, _node, _start, _status, _workflow

__all__ = ["world"]  # the fixture, re-used

WF = "/automation/workflows/instances"


async def _instance(world: World, instance: uuid.UUID) -> dict[str, Any]:
    [row] = await world.sql(
        "SELECT status, version, stopped_reason, failure FROM workflow_instances WHERE id = $1",
        instance,
    )
    return dict(row)


async def _steps(world: World, instance: uuid.UUID) -> list[str]:
    rows = await world.sql(
        "SELECT node, result FROM workflow_steps WHERE instance_id = $1 ORDER BY seq", instance
    )
    return [f"{r['node']}:{r['result']}" for r in rows]


async def _post(
    world: World,
    org: Org,
    user: uuid.UUID,
    instance: uuid.UUID,
    verb: str,
    **body: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - an httpx response
    version = (await _instance(world, instance))["version"]
    return await world.call(
        "POST",
        f"{WF}/{instance}/{verb}",
        org,
        user,
        json=body,
        headers={"If-Match": f'"{version}"', **CONSOLE},
    )


async def test_req_wf_026_stop_asks_for_a_reason_keeps_the_log_and_is_audited(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, WAIT_FOR_P1), item["id"])
    before = await _steps(world, instance)
    assert (await _post(world, a, a.admin, instance, "stop", reason="")).status_code == 422
    stopped = await _post(world, a, a.admin, instance, "stop", reason="Raised by mistake")
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "cancelled"
    assert stopped.json()["stopped_reason"] == "Raised by mistake"
    after = await _steps(world, instance)
    assert after[: len(before)] == before  # nothing cleared (ServiceDesk Plus's revoke does)
    assert after[-1].endswith(":stopped")
    audited = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = $2"
        " AND object_id = $3 AND outcome = 'done'",  # the refused empty reason is logged apart
        a.tenant,
        "automation.workflow_stopped",
        str(instance),
    )
    assert audited[0]["n"] == 1
    again = await _post(world, a, a.admin, instance, "stop", reason="Twice")
    assert again.status_code == 409
    assert again.json()["code"] == "instance_not_running"


async def test_stop_refuses_a_stale_version(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, WAIT_FOR_P1), item["id"])
    stale = await world.call(
        "POST",
        f"{WF}/{instance}/stop",
        a,
        a.admin,
        json={"reason": "Late"},
        headers={"If-Match": '"999"', **CONSOLE},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "workflow_instance_changed"


async def test_req_wf_026_restart_from_a_chosen_node_runs_from_there_and_history_says_so(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, _waiting_then_set()), item["id"])
    assert (
        await _post(world, a, a.admin, instance, "stop", reason="Wrong time")
    ).status_code == 200
    unknown = await _post(world, a, a.admin, instance, "restart", node="nowhere")
    assert unknown.status_code == 409
    assert unknown.json()["code"] == "node_not_found"
    again = await _post(world, a, a.admin, instance, "restart", node="set")
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "finished"  # the field step ran, then the end
    assert "set:restarted" in await _steps(world, instance)
    fresh = await world.fresh(a, item)
    assert fresh["impact"] == "team"
    entries = [
        h for h in await world.history(a, item) if (h["automation"] or {}).get("kind") == "workflow"
    ]
    assert entries  # history names the workflow that set it


def _waiting_then_set() -> dict[str, Any]:
    return {
        "format": 1,
        "nodes": [
            _node("s", "start"),
            _node("wait", "wait", event="record_changed", condition=_P1),
            _node("set", "field_update", values={"impact": "team"}),
            _node("e", "end"),
        ],
        "links": [
            {"from": "s", "port": "next", "to": "wait"},
            {"from": "wait", "port": "next", "to": "set"},
            {"from": "set", "port": "next", "to": "e"},
        ],
        "variables": [],
    }


_P1 = {"field": "priority", "op": "eq", "value": "p1"}


def _bad_set() -> dict[str, Any]:
    """A field step whose value the record refuses at run time, with no error output."""
    return {
        "format": 1,
        "nodes": [
            _node("s", "start"),
            _node("set", "field_update", values={"impact": "not_an_impact"}),
            _node("e", "end"),
        ],
        "links": [
            {"from": "s", "port": "next", "to": "set"},
            {"from": "set", "port": "next", "to": "e"},
        ],
        "variables": [],
    }


async def test_req_wf_025_retry_runs_a_failed_instance_s_failed_node_again(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, _bad_set()), item["id"])
    failed = await _instance(world, instance)
    assert failed["status"] == "failed"
    not_failed = await world.create(a, a.admin)
    waiting = await _start(world, await _workflow(world, WAIT_FOR_P1), not_failed["id"])
    refused = await _post(world, a, a.admin, waiting, "retry")
    assert refused.status_code == 409
    assert refused.json()["code"] == "instance_not_failed"
    again = await _post(world, a, a.admin, instance, "retry")
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "failed"  # the same value is refused again, honestly
    assert "set:retried" in await _steps(world, instance)


async def test_adr_043_acting_on_a_record_s_workflow_needs_the_right_to_edit_it(
    world: World,
) -> None:
    a = world.a
    runner = await role(world, a, "Workflow runner", [("workflows.run", "all")])
    assigned = await world.call("PUT", f"/users/{a.requester}/roles/{runner}", a, a.admin)
    assert assigned.status_code in {200, 204}, assigned.text
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, WAIT_FOR_P1), item["id"])
    refused = await _post(world, a, a.requester, instance, "stop", reason="Not mine")
    assert refused.status_code == 403
    assert refused.json()["code"] == "record_not_editable"
    assert (await _instance(world, instance))["status"] == "waiting"


async def test_req_wf_026_ac3_a_cancelled_record_stops_its_workflow(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, WAIT_FOR_P1), item["id"])
    cancelled = await world.act(a, a.admin, item, "cancel", "duplicate")
    assert cancelled.status_code == 200, cancelled.text
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = $2"
        " AND aggregate_id = $1 ORDER BY id DESC LIMIT 1",
        item["id"],
        "work_items.work_item.status_changed",
    )
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await workflow_events.on_record_event(envelope, session)
    assert await _status(world, instance) == "cancelled"
    assert (await _instance(world, instance))["stopped_reason"] == "record_canceled"


async def test_a_release_canceled_by_a_stage_move_stops_its_workflow(world: World) -> None:
    """Staged types cancel by a move into closure_canceled, not the cancel action (lane A)."""
    a = world.a
    release, instance = await _started(world, await _release_flow(world, WAIT_FOR_P1))
    canceled = await moved(world, a, release, "closure_canceled", reason_text="Not needed")
    assert canceled["status_category"] == "canceled"
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = $2"
        " AND aggregate_id = $1 ORDER BY id DESC LIMIT 1",
        release["id"],
        "work_items.work_item.status_changed",
    )
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    assert envelope.payload["action"] != "cancel"  # a stage move
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await workflow_events.on_record_event(envelope, session)
    assert await _status(world, instance) == "cancelled"
    assert (await _instance(world, instance))["stopped_reason"] == "record_canceled"


async def test_stopping_a_workflow_closes_its_open_approvals(world: World) -> None:
    a = world.a
    flow = await _release_flow(world, _approval(a.tech_a))
    release, instance = await _started(world, flow)
    stopped = await _post(world, a, a.admin, instance, "stop", reason="Not needed now")
    assert stopped.status_code == 200, stopped.text
    rows = await world.sql(
        "SELECT state FROM work_item_approvals WHERE work_item_id = $1",
        uuid.UUID(release["id"]),
    )
    assert [r["state"] for r in rows] == ["not_needed"]


async def test_a_trashed_record_s_workflow_cannot_be_restarted(world: World) -> None:
    """Lane A's review: a record in the trash is never editable, so nobody acts on its runs."""
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, WAIT_FOR_P1), item["id"])
    assert (await _post(world, a, a.admin, instance, "stop", reason="Moving on")).status_code == 200
    gone = await world.call(
        "DELETE",
        f"/incidents/{item['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{(await world.fresh(a, item))["version"]}"', **CONSOLE},
    )
    assert gone.status_code in {200, 204}, gone.text
    refused = await _post(world, a, a.admin, instance, "restart")
    assert refused.status_code == 403
    assert refused.json()["code"] == "record_not_editable"
