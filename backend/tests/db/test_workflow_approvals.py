"""The approval node on a real release (WP-048b S2; REQ-WF-014; migration 0106).

- The node opens one level of approvals on the record, purpose "workflow", naming the instance
  and the command; the instance waits.
- The approver decides through the record's own approvals API; the decision reaches the
  workflow through the outbox (automation.workflow.command_finished), and the node leaves by
  "approved" or "rejected".
"""

import json
import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import Workflow, WorkflowInstance, WorkflowVersion
from app.modules.automation.service import workflow_events, workflow_runtime
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import CONSOLE, World, world
from tests.db.test_releases_api import new_release
from tests.db.test_workflow_events import _flow, _node

__all__ = ["world"]  # the fixture, re-used


def _approval(approver: uuid.UUID) -> dict[str, Any]:
    return _flow(
        _node("s", "start"),
        _node("ask", "approval", approvers={"user_ids": [str(approver)]}, rule="any"),
        _node("yes", "end"),
        _node("no", "end"),
        links=[("s", "next", "ask"), ("ask", "approved", "yes"), ("ask", "rejected", "no")],
    )


async def _release_flow(world: World, definition: dict[str, Any]) -> uuid.UUID:
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        flow = Workflow(
            tenant_id=a.tenant,
            record_type="release",
            name=f"Approval {uuid.uuid4().hex[:6]}",
            draft=definition,
            enabled=True,
            service_identity_id=a.admin,
            published_version=1,
        )
        session.add(flow)
        await session.flush()
        session.add(
            WorkflowVersion(
                tenant_id=a.tenant, workflow_id=flow.id, number=1, definition=definition
            )
        )
        return flow.id


async def _started(world: World, flow: uuid.UUID) -> tuple[dict[str, Any], uuid.UUID]:
    a = world.a
    made = await new_release(world, a, a.admin)
    assert made.status_code == 201, made.text
    release = dict(made.json())
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        instance = await workflow_runtime.start(
            session,
            workflow_id=flow,
            record_type="release",
            record_id=uuid.UUID(release["id"]),
            how="manual",
        )
        return release, instance.id


async def _decide(world: World, release: dict[str, Any], decision: str) -> None:
    a = world.a
    listed = await world.call("GET", f"/releases/{release['id']}/approvals", a, a.tech_a)
    assert listed.status_code == 200, listed.text
    [row] = [r for r in listed.json()["items"] if r["state"] == "pending"]
    done = await world.call(
        "POST",
        f"/releases/{release['id']}/approvals/{row['id']}/decision",
        a,
        a.tech_a,
        json={"decision": decision, "comment": "No" if decision == "reject" else None},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert done.status_code == 200, done.text


async def _deliver_result(world: World, instance_id: uuid.UUID) -> dict[str, Any]:
    """The outbox event the decision wrote, handed to automation's consumer, as the worker does."""
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = $1 AND aggregate_id = $2",
        "automation.workflow.command_finished",
        str(instance_id),  # the outbox keeps aggregate ids as text
    )
    assert len(rows) == 1  # one result, written with the deciding vote
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        await workflow_events.on_command_finished(envelope, session)
        await workflow_events.on_command_finished(envelope, session)  # redelivered: no-op
    return dict(envelope.payload)


async def _instance(world: World, instance_id: uuid.UUID) -> tuple[str, list[str]]:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        found = await session.get(WorkflowInstance, instance_id)
        assert found is not None
        status = str(found.status)
    steps = await world.sql(
        "SELECT node, result FROM workflow_steps WHERE instance_id = $1 ORDER BY seq",
        instance_id,
    )
    return status, [f"{s['node']}:{s['result']}" for s in steps]


async def test_req_wf_014_the_node_opens_an_approval_and_its_approval_continues_it(
    world: World,
) -> None:
    a = world.a
    flow = await _release_flow(world, _approval(a.tech_a))
    release, instance_id = await _started(world, flow)

    rows = await world.sql(
        "SELECT approver_id, purpose, workflow_instance_id, workflow_command, origin, state"
        " FROM work_item_approvals WHERE work_item_id = $1",
        uuid.UUID(release["id"]),
    )
    assert len(rows) == 1
    [row] = rows
    assert (row["approver_id"], row["purpose"], row["origin"], row["state"]) == (
        a.tech_a,
        "workflow",
        "named",
        "pending",
    )
    assert row["workflow_instance_id"] == instance_id
    assert row["workflow_command"]  # the node's own command
    assert (await _instance(world, instance_id))[0] == "waiting"

    await _decide(world, release, "approve")
    result = await _deliver_result(world, instance_id)
    assert (result["ok"], result["port"]) == (True, "approved")
    status, steps = await _instance(world, instance_id)
    assert status == "finished"
    assert "ask:approved" in steps
    assert "no:finished" not in steps


async def test_req_wf_014_a_rejection_takes_the_rejected_output(world: World) -> None:
    a = world.a
    flow = await _release_flow(world, _approval(a.tech_a))
    release, instance_id = await _started(world, flow)
    await _decide(world, release, "reject")
    result = await _deliver_result(world, instance_id)
    assert result["port"] == "rejected"
    status, steps = await _instance(world, instance_id)
    assert status == "finished"
    assert "ask:rejected" in steps
    assert "no:finished" in steps


async def test_an_approver_who_cannot_be_named_sends_the_level_to_the_administrators(
    world: World,
) -> None:
    """Never a silent dead end: an unknown or inactive approver means the administrators decide."""
    flow = await _release_flow(world, _approval(uuid.uuid4()))  # nobody in this tenant
    release, instance_id = await _started(world, flow)
    rows = await world.sql(
        "SELECT approver_id, origin, route_reason FROM work_item_approvals WHERE work_item_id = $1",
        uuid.UUID(release["id"]),
    )
    assert [(r["approver_id"], r["origin"]) for r in rows] == [(None, "administrators")]
    assert rows[0]["route_reason"] in {"approver_inactive", "no_holder"}
    assert (await _instance(world, instance_id))[0] == "waiting"
