"""A record's Workflows panel (WP-048b S4d; REQ-WF-023, -024; ADR-043 §10).

- The panel's endpoint gives each run on the record with its diagram, where it is now and its
  log (REQ-WF-023 AC2).
- Only for those who may see the record, by its type's own view rule (404 otherwise), and
  never for requesters (workflows.run; AC3). An instance's log has the same gate.
- Tenant isolation: another tenant's record is not found.
"""

from tests.db.test_incidents_api import World, role, world
from tests.db.test_workflow_events import WAIT_FOR_P1, _start, _workflow

__all__ = ["world"]  # the fixture, re-used

BASE = "/automation/workflows"


async def test_req_wf_023_the_panel_has_the_diagram_the_position_and_the_log(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    flow = await _workflow(world, WAIT_FOR_P1)
    instance = await _start(world, flow, item["id"])
    got = await world.call("GET", f"{BASE}/records/incident/{item['id']}", a, a.admin)
    assert got.status_code == 200, got.text
    [run] = got.json()
    assert run["instance"]["id"] == str(instance)
    assert run["instance"]["status"] == "waiting"
    assert run["current_nodes"] == ["w"]
    assert [n["id"] for n in run["definition"]["nodes"]] == [n["id"] for n in WAIT_FOR_P1["nodes"]]
    assert [s["node"] for s in run["steps"]][:1] == ["s"]  # oldest first


async def test_req_wf_023_ac3_only_those_who_see_the_record_and_never_requesters(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))  # GA's: tech_b is in GB
    instance = await _start(world, await _workflow(world, WAIT_FOR_P1), item["id"])
    runner = await role(world, a, "Workflow runner", [("workflows.run", "all")])
    for person in (a.tech_b, a.requester):
        assigned = await world.call("PUT", f"/users/{person}/roles/{runner}", a, a.admin)
        assert assigned.status_code in {200, 204}, assigned.text
    hidden = await world.call("GET", f"{BASE}/records/incident/{item['id']}", a, a.tech_b)
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "record_not_found"
    log = await world.call("GET", f"{BASE}/instances/{instance}/steps", a, a.tech_b)
    assert log.status_code == 404  # the log has the record's gate too
    requester = await world.call("GET", f"{BASE}/records/incident/{item['id']}", a, a.requester)
    assert requester.status_code in {403, 404}  # the console's API is never the portal's


async def test_another_tenant_s_record_is_not_found(world: World) -> None:
    a, b = world.a, world.b
    item = await world.create(a, a.admin)
    await _start(world, await _workflow(world, WAIT_FOR_P1), item["id"])
    theirs = await world.call("GET", f"{BASE}/records/incident/{item['id']}", b, b.admin)
    assert theirs.status_code == 404
