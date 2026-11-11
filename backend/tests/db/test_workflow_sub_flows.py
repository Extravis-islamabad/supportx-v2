"""Sub-flows on a real incident (WP-048b S2; REQ-WF-017; migration 0106).

- A parent's sub-flow node starts the child on the same record, and waits.
- When the child ends later (here: its wait completes), the parent continues.
- A child that cannot start (switched off) takes the parent's error output.
- On save, a sub-flow that leads back to its own workflow is refused, named by its node.
"""

import json
import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import Workflow
from app.modules.automation.service import workflow_admin, workflow_events, workflow_runtime
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import CONSOLE, World, world
from tests.db.test_workflow_events import WAIT_FOR_P1, _flow, _node, _workflow

__all__ = ["world"]  # the fixture, re-used


def _parent(child: uuid.UUID) -> dict[str, Any]:
    return _flow(
        _node("s", "start"),
        _node("sub", "sub_flow", workflow_id=str(child)),
        _node("e", "end"),
        _node("bad", "end"),
        links=[("s", "next", "sub"), ("sub", "next", "e"), ("sub", "error", "bad")],
    )


async def _instances(world: World, record: str) -> dict[uuid.UUID, tuple[str, uuid.UUID | None]]:
    rows = await world.sql(
        "SELECT workflow_id, status, parent_instance_id FROM workflow_instances"
        " WHERE record_id = $1",
        uuid.UUID(record),
    )
    return {r["workflow_id"]: (r["status"], r["parent_instance_id"]) for r in rows}


async def _start(world: World, flow: uuid.UUID, record: str) -> uuid.UUID:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        instance = await workflow_runtime.start(
            session,
            workflow_id=flow,
            record_type="incident",
            record_id=uuid.UUID(record),
            how="manual",
        )
        return instance.id


async def test_req_wf_017_the_parent_waits_for_its_child_and_continues_when_it_ends(
    world: World,
) -> None:
    a = world.a
    child = await _workflow(world, WAIT_FOR_P1)
    parent = await _workflow(world, _parent(child))
    item = await world.create(a, a.admin)
    parent_instance = await _start(world, parent, item["id"])
    found = await _instances(world, item["id"])
    assert found[parent] == ("waiting", None)
    assert found[child] == ("waiting", parent_instance)

    changed = await world.call(
        "PATCH",
        f"/incidents/{item['id']}",
        a,
        a.admin,
        json={"priority": "p1", "priority_reason": "Outage"},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = 'work_items.work_item.updated'"
        " AND aggregate_id = $1 ORDER BY id DESC LIMIT 1",
        item["id"],
    )
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await workflow_events.on_record_event(envelope, session)
    found = await _instances(world, item["id"])
    assert found[child][0] == "finished"
    assert found[parent][0] == "finished"
    steps = await world.sql(
        "SELECT node, result FROM workflow_steps WHERE instance_id = $1 ORDER BY seq",
        parent_instance,
    )
    assert [(r["node"], r["result"]) for r in steps][-2:] == [("sub", "next"), ("e", "finished")]


async def test_a_child_that_cannot_start_takes_the_error_output(world: World) -> None:
    a = world.a
    child = await _workflow(world, WAIT_FOR_P1)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        off = await session.get(Workflow, child)
        assert off is not None
        off.enabled = False
    parent = await _workflow(world, _parent(child))
    item = await world.create(a, a.admin)
    await _start(world, parent, item["id"])
    found = await _instances(world, item["id"])
    assert found == {parent: ("finished", None)}  # by the error output; no child was made
    steps = await world.sql(
        "SELECT s.node, s.result FROM workflow_steps s JOIN workflow_instances i"
        " ON i.id = s.instance_id WHERE i.record_id = $1 ORDER BY s.seq",
        uuid.UUID(item["id"]),
    )
    assert ("sub", "error") in [(r["node"], r["result"]) for r in steps]


async def test_req_wf_017_a_sub_flow_back_to_its_own_workflow_is_refused_on_save(
    world: World,
) -> None:
    a = world.a
    child = await _workflow(world, WAIT_FOR_P1)
    parent = await _workflow(world, _parent(child))
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        # The child (published) is changed to run the parent: parent → child → parent.
        problems = await workflow_admin.problems_of(session, "incident", _parent(parent), child)
        assert ("node:sub", "sub_flow_recursion") in [(w, c) for w, c, _ in problems]
        itself = await workflow_admin.problems_of(session, "incident", _parent(parent), parent)
        assert ("node:sub", "sub_flow_recursion") in [(w, c) for w, c, _ in itself]
        missing = await workflow_admin.problems_of(
            session, "incident", _parent(uuid.uuid4()), parent
        )
        assert ("node:sub", "workflow_not_found") in [(w, c) for w, c, _ in missing]
