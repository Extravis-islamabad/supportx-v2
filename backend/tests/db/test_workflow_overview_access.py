"""Who sees what in the runs overview (WP-048b S5a; REQ-WF-025; the coordinator's S5 terms).

- workflows.manage lists every run of the tenant (ADR-043 §10).
- A run's record is named (display ID, subject) only for a viewer who may see that record, by
  its type's own view rule; for anyone else the run is listed without its record's ID or subject.
"""

from tests.db.test_incidents_api import World, role, world
from tests.db.test_workflow_events import WAIT_FOR_P1, _start, _workflow

__all__ = ["world"]  # the fixture, re-used

BASE = "/automation/workflows"


async def test_a_run_names_its_record_only_for_those_who_may_see_it(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, subject="Core switch down", group_id=str(a.ga))
    flow = await _workflow(world, WAIT_FOR_P1)
    instance = await _start(world, flow, item["id"])
    query = {"workflow_id": str(flow)}

    admin = await world.call("GET", f"{BASE}/instances", a, a.admin, params=query)
    assert admin.status_code == 200, admin.text
    [run] = admin.json()["items"]
    assert run["record"] == {"display_id": item["display_id"], "subject": "Core switch down"}

    designer = await role(world, a, "Workflow designer", [("workflows.manage", "all")])
    assigned = await world.call("PUT", f"/users/{a.tech_b}/roles/{designer}", a, a.admin)
    assert assigned.status_code in {200, 204}, assigned.text
    outside = await world.call("GET", f"{BASE}/instances", a, a.tech_b, params=query)
    assert outside.status_code == 200, outside.text
    [theirs] = outside.json()["items"]
    assert theirs["id"] == str(instance)  # the run is listed (workflows.manage) ...
    assert theirs["record"] is None  # ... its record is not named (tech_b is outside GA)
    assert "Core switch down" not in outside.text
    assert item["display_id"] not in outside.text
