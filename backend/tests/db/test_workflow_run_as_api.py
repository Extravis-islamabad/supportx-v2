"""A workflow's run-as identity and its roles (ADR-043 §6; the coordinator's plan, 2026-11-11).

- Publishing makes the identity with no role: nothing is ever given without an admin choosing.
- Its roles are given and taken only through identity_access's guarded path: never tenant
  administration, nor a role that manages identities, roles or API keys. The picker's list is
  the server's own rule.
- A step that changes the record while the identity holds no right fails with
  `workflow_identity_not_permitted`, never a "not found"; given a role, the same step runs.
- Another tenant's admin sees nothing of it (RLS).
"""

import uuid
from typing import Any

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, World, problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

BASE = "/automation/workflows"


def _new() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4()), **CONSOLE}


def _match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"', **CONSOLE}


def _node(node_id: str, kind: str, **config: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"id": node_id, "type": kind, "config": config, "position": {"x": 0, "y": 0}}


NOTE: dict[str, Any] = {
    "format": 1,
    "nodes": [
        _node("start", "start"),
        _node("note", "note", text={"en": "Seen by the workflow"}, private=True),
        _node("end", "end"),
    ],
    "links": [
        {"from": "start", "port": "next", "to": "note"},
        {"from": "note", "port": "next", "to": "end"},
    ],
    "variables": [],
}


async def _role_id(world: World, key: str) -> str:
    rows = await world.sql(
        "SELECT id FROM roles WHERE key = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        key,
        world.a.tenant,
    )
    return str(rows[0]["id"])


async def _notes_role(world: World) -> str:
    """A role that sees every incident and adds notes: a technician's role reaches only its own
    groups' records, and a run-as identity has no group."""
    a = world.a
    role = await world.call(
        "POST",
        "/roles",
        a,
        a.admin,
        json={
            "name": f"Workflow notes {uuid.uuid4().hex[:6]}",
            "permissions": [
                {"permission": "incidents.view", "scope": "all"},
                {"permission": "incidents.add_note", "scope": "all"},
            ],
        },
    )
    assert role.status_code == 201, role.text
    return str(role.json()["id"])


async def _published(world: World) -> dict[str, Any]:
    a = world.a
    made = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"record_type": "incident", "name": "Note it"},
        headers=_new(),
    )
    assert made.status_code == 201, made.text
    flow = made.json()
    saved = await world.call(
        "PUT",
        f"{BASE}/{flow['id']}/draft",
        a,
        a.admin,
        json={"definition": NOTE},
        headers=_match(flow["version"]),
    )
    assert saved.status_code == 200, saved.text
    version = saved.json()["version"]
    run_as = await world.call("GET", f"{BASE}/{flow['id']}/run-as", a, a.admin)
    assert run_as.json()["made"] is False  # nothing before the first publish
    refused = await world.call(
        "PUT",
        f"{BASE}/{flow['id']}/run-as/roles/{await _role_id(world, 'technician')}",
        a,
        a.admin,
        headers=CONSOLE,
    )
    assert problem(refused) == (409, "workflow_not_published")
    published = await world.call(
        "POST", f"{BASE}/{flow['id']}/publish", a, a.admin, headers=_match(version)
    )
    assert published.status_code == 200, published.text
    on = await world.call(
        "PUT",
        f"{BASE}/{flow['id']}/enabled",
        a,
        a.admin,
        json={"enabled": True},
        headers=_match(published.json()["version"]),
    )
    assert on.status_code == 200, on.text
    return dict(on.json())


async def _run(world: World, flow: dict[str, Any]) -> dict[str, Any]:
    a = world.a
    item = await world.create(a, a.admin)
    started = await world.call(
        "POST",
        f"{BASE}/{flow['id']}/instances",
        a,
        a.admin,
        json={"record_id": item["id"]},
        headers=_new(),
    )
    assert started.status_code == 201, started.text
    return dict(started.json())


async def test_publishing_makes_the_identity_with_no_role_and_a_step_says_why_it_fails(
    world: World,
) -> None:
    a = world.a
    flow = await _published(world)
    run_as = (await world.call("GET", f"{BASE}/{flow['id']}/run-as", a, a.admin)).json()
    assert (run_as["made"], run_as["active"], run_as["roles"]) == (True, True, [])
    assert run_as["name"]
    instance = await _run(world, flow)
    assert instance["status"] == "failed"
    # The identity's missing right, in words: never a "not found" about the record.
    assert instance["failure"]["node"] == "note"
    assert instance["failure"]["code"] == "workflow_identity_not_permitted"


async def test_a_role_given_lets_the_same_step_run_and_reaches_open_designers(
    world: World,
) -> None:
    a = world.a
    flow = await _published(world)
    notes = await _notes_role(world)
    given = await world.call(
        "PUT", f"{BASE}/{flow['id']}/run-as/roles/{notes}", a, a.admin, headers=CONSOLE
    )
    assert given.status_code == 204, given.text
    run_as = (await world.call("GET", f"{BASE}/{flow['id']}/run-as", a, a.admin)).json()
    assert [r["id"] for r in run_as["roles"]] == [notes]
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = 'automation.workflow.run_as_changed'"
        " AND aggregate_id = $1 AND tenant_id = $2",
        flow["id"],
        a.tenant,
    )
    assert len(events) == 1
    assert "Workflow notes" not in str(events[0]["envelope"])  # IDs and codes only
    instance = await _run(world, flow)
    assert instance["status"] == "finished", instance["failure"]
    taken = await world.call(
        "DELETE", f"{BASE}/{flow['id']}/run-as/roles/{notes}", a, a.admin, headers=CONSOLE
    )
    assert taken.status_code == 204, taken.text
    run_as = (await world.call("GET", f"{BASE}/{flow['id']}/run-as", a, a.admin)).json()
    assert run_as["roles"] == []


async def test_tenant_administration_is_never_offered_nor_given(world: World) -> None:
    a = world.a
    flow = await _published(world)
    admin_role = await _role_id(world, "tenant_admin")
    run_as = (await world.call("GET", f"{BASE}/{flow['id']}/run-as", a, a.admin)).json()
    offered = {r["key"] for r in run_as["offered"]}
    assert "tenant_admin" not in offered
    assert "technician" in offered
    refused = await world.call(
        "PUT", f"{BASE}/{flow['id']}/run-as/roles/{admin_role}", a, a.admin, headers=CONSOLE
    )
    assert problem(refused) == (403, "service_identity_role_not_allowed")


async def test_only_workflow_admins_of_the_same_tenant_reach_it(world: World) -> None:
    a, b = world.a, world.b
    flow = await _published(world)
    technician = await _role_id(world, "technician")
    by_tech = await world.call("GET", f"{BASE}/{flow['id']}/run-as", a, a.tech_a)
    assert by_tech.status_code == 403
    tech_gives = await world.call(
        "PUT", f"{BASE}/{flow['id']}/run-as/roles/{technician}", a, a.tech_a, headers=CONSOLE
    )
    assert tech_gives.status_code == 403
    other_tenant = await world.call("GET", f"{BASE}/{flow['id']}/run-as", b, b.admin)
    assert other_tenant.status_code == 404
