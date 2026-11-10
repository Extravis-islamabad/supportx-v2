"""A trigger's "start a workflow" action (WP-048b S1; REQ-WF-010, REQ-RUL-010, REQ-RUL-028).

Real PostgreSQL and Valkey, the incidents world; committed events go to the trigger consumer as
the worker delivers them (`drain`). Proves: the action is checked when the trigger is saved; it
starts the workflow as the workflow's run-as identity; a workflow already running is logged on
the run, never raised, and the trigger's other actions still run; a change the workflow itself
made never starts it again.
"""

import uuid
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import Workflow, WorkflowVersion
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_automation_triggers_api import add_trigger, drain, note, runs
from tests.db.test_incidents_api import Org, World

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used
pytestmark = [pytest.mark.db, pytest.mark.valkey, MODULE_LOOP]


def _node(node_id: str, kind: str, **config: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"id": node_id, "type": kind, "config": config, "position": {"x": 0, "y": 0}}


def _flow(*nodes: dict[str, Any], links: list[tuple[str, str, str]]) -> dict[str, Any]:
    return {
        "format": 1,
        "nodes": list(nodes),
        "links": [{"from": a, "port": p, "to": b} for a, p, b in links],
        "variables": [],
    }


NOTE_THEN_END = _flow(
    _node("s", "start"),
    _node("n", "note", text={"en": "Noted by the workflow"}, private=True),
    _node("e", "end"),
    links=[("s", "next", "n"), ("n", "next", "e")],
)
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


async def _workflow(
    world: World,
    org: Org,
    definition: dict[str, Any],
    *,
    run_as: uuid.UUID,
    record_type: str = "incident",
    enabled: bool = True,
    published: bool = True,
) -> uuid.UUID:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        flow = Workflow(
            tenant_id=org.tenant,
            record_type=record_type,
            name=f"Flow {uuid.uuid4().hex[:6]}",
            draft=definition,
            enabled=enabled,
            service_identity_id=run_as,
            published_version=1 if published else None,
        )
        session.add(flow)
        await session.flush()
        if published:
            session.add(
                WorkflowVersion(
                    tenant_id=org.tenant, workflow_id=flow.id, number=1, definition=definition
                )
            )
        return flow.id


def _start(workflow_id: uuid.UUID) -> dict[str, str]:
    return {"kind": "start_workflow", "workflow_id": str(workflow_id)}


async def _instances(world: World, record_id: str) -> list[tuple[str, str]]:
    rows = await world.sql(
        "SELECT started_how, status FROM workflow_instances WHERE record_id = $1 ORDER BY id",
        uuid.UUID(record_id),
    )
    return [(r["started_how"], r["status"]) for r in rows]


async def test_the_workflow_is_checked_when_the_trigger_is_saved(world: World) -> None:
    org = world.a
    other_type = await _workflow(
        world, org, NOTE_THEN_END, run_as=org.tech_a, record_type="problem"
    )
    off = await _workflow(world, org, NOTE_THEN_END, run_as=org.tech_a, enabled=False)
    unpublished = await _workflow(world, org, NOTE_THEN_END, run_as=org.tech_a, published=False)
    bad = await world.call(
        "POST",
        "/automation/triggers",
        org,
        org.admin,
        json={
            "record_type": "incident",
            "name": "Start",
            "state": "enabled",
            "events": ["created"],
            "actions": [
                _start(uuid.uuid4()),
                _start(other_type),
                _start(off),
                _start(unpublished),
            ],
        },
    )
    assert bad.status_code == 422, bad.text
    assert {(e["field"], e["code"]) for e in bad.json()["errors"]} == {
        ("body.actions.0.workflow_id", "workflow_not_found"),
        ("body.actions.1.workflow_id", "workflow_wrong_record_type"),
        ("body.actions.2.workflow_id", "workflow_disabled"),
        ("body.actions.3.workflow_id", "workflow_not_published"),
    }
    # A draft trigger may be prepared with its workflow before both are switched on.
    draft = await add_trigger(
        world, org, state="draft", events=["created"], actions=[_start(off), _start(unpublished)]
    )
    assert [a["workflow_id"] for a in draft["actions"]] == [str(off), str(unpublished)]

    elsewhere = await _workflow(world, world.b, NOTE_THEN_END, run_as=world.b.tech_a)
    other_tenant = await world.call(
        "POST",
        "/automation/triggers",
        org,
        org.admin,
        json={
            "record_type": "incident",
            "name": "Theirs",
            "state": "draft",
            "events": ["created"],
            "actions": [_start(elsewhere)],
        },
    )
    assert other_tenant.status_code == 422  # another tenant's workflow is not found (RLS)
    assert other_tenant.json()["errors"][0]["code"] == "workflow_not_found"


async def test_a_trigger_starts_the_workflow_and_its_own_change_never_starts_it_again(
    world: World,
) -> None:
    org = world.a
    flow = await _workflow(world, org, NOTE_THEN_END, run_as=org.tech_a)
    # The workflow adds a note; a trigger on notes would start it again without the guard.
    await add_trigger(world, org, events=["created", "note_added"], actions=[_start(flow)])
    item = await world.create(org, org.admin)
    await drain(world, org)  # raises if the chain keeps going

    assert await _instances(world, item["id"]) == [("trigger", "finished")]
    trigger_runs = [r for r in await runs(world, org, item) if r["kind"] == "trigger"]
    actions = [a for r in trigger_runs for a in r["detail"]["actions"]]
    assert sorted((a["outcome"], a.get("reason") or "") for a in actions) == [
        ("applied", ""),  # the person's create
        ("kept", "own_change"),  # the workflow's note, made as its run-as identity
    ]
    assert {a["workflow_id"] for a in actions} == {str(flow)}
    notes = await world.sql(
        "SELECT body FROM work_item_conversations WHERE work_item_id = $1 AND kind = 'note'",
        uuid.UUID(item["id"]),
    )
    assert len(notes) == 1  # the workflow ran once: its own note started nothing more


async def test_an_already_running_workflow_is_logged_and_the_other_actions_still_run(
    world: World,
) -> None:
    org = world.a
    flow = await _workflow(world, org, WAIT_FOR_P1, run_as=org.tech_a)
    await add_trigger(
        world,
        org,
        events=["created"],
        actions=[_start(flow), _start(flow), note("After the workflow.")],
    )
    item = await world.create(org, org.admin)
    await drain(world, org)

    assert await _instances(world, item["id"]) == [("trigger", "waiting")]
    (run,) = [r for r in await runs(world, org, item) if r["kind"] == "trigger"]
    assert run["outcome"] == "partial"
    assert [(a["kind"], a["outcome"], a.get("reason")) for a in run["detail"]["actions"]] == [
        ("start_workflow", "applied", None),
        ("start_workflow", "failed", "workflow_already_running"),
        ("note", "applied", None),
    ]
