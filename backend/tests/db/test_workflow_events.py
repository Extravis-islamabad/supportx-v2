"""What wakes a waiting workflow, on a real incident (WP-048b S1, ADR-043 §5; REQ-WF-012, -013).

- A person's change, committed and read back from the outbox, completes a wait for it.
- The minute sweep runs an instance whose timer is due.
The record type's run_command is the real work_items one; the run-as identity is the admin.
"""

import copy
import json
import uuid
from datetime import timedelta
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import Workflow, WorkflowInstance, WorkflowVersion
from app.modules.automation.service import workflow_events, workflow_runtime
from app.shared.clock import system_clock
from app.shared.events import EventEnvelope
from conftest import make_settings
from tests.db.test_incidents_api import CONSOLE, World, world

__all__ = ["world"]  # the fixture, re-used


def _node(node_id: str, kind: str, **config: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"id": node_id, "type": kind, "config": config, "position": {"x": 0, "y": 0}}


def _flow(*nodes: dict[str, Any], links: list[tuple[str, str, str]]) -> dict[str, Any]:
    return {
        "format": 1,
        "nodes": list(nodes),
        "links": [{"from": a, "port": p, "to": b} for a, p, b in links],
        "variables": [],
    }


WAIT_FOR_P1 = _flow(
    _node("s", "start"),
    _node(
        "w",
        "wait",
        events=["field_changed"],
        condition={"field": "priority", "op": "eq", "value": "p1"},
    ),
    _node("e", "end"),
    _node("over", "end"),
    links=[("s", "next", "w"), ("w", "next", "e"), ("w", "overtaken", "over")],
)
TIMER = _flow(
    _node("s", "start"),
    _node("t", "timer", seconds=60),
    _node("e", "end"),
    links=[("s", "next", "t"), ("t", "next", "e")],
)


async def _workflow(world: World, definition: dict[str, Any]) -> uuid.UUID:
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        flow = Workflow(
            tenant_id=a.tenant,
            record_type="incident",
            name=f"Flow {uuid.uuid4().hex[:6]}",
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


async def _status(world: World, instance_id: uuid.UUID) -> str:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        found = await session.get(WorkflowInstance, instance_id)
        assert found is not None
        return str(found.status)


async def test_req_wf_012_a_person_s_committed_change_completes_the_wait(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)  # the default priority, not P1
    instance = await _start(world, await _workflow(world, WAIT_FOR_P1), item["id"])
    assert await _status(world, instance) == "waiting"

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
    assert await _status(world, instance) == "finished"


async def test_req_wf_013_the_sweep_runs_an_instance_whose_timer_is_due(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    instance = await _start(world, await _workflow(world, TIMER), item["id"])
    assert await _status(world, instance) == "waiting"
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        found = await session.get(WorkflowInstance, instance)
        assert found is not None
        found.wake_at = system_clock.now() - timedelta(seconds=5)  # as if a minute had passed
        state = copy.deepcopy(found.state)  # a new value, so the change is saved
        for token in state["tokens"]:
            token["wake_at"] = found.wake_at.isoformat()
        found.state = state
    await workflow_events.wake_due(world.app.state.db, make_settings())
    assert await _status(world, instance) == "finished"
