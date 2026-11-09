"""An incident's causing problem, as incident technicians see it (WP-044c D14; REQ-PRB-071)."""

from tests.db.test_incidents_api import CONSOLE, World, problem, role, world
from tests.db.test_problems_api import PRB, new_problem

__all__ = ["world"]  # the fixture, re-used

WORKAROUND = "<p>Restart the mail relay.</p>"
ROOT_CAUSE = "<p>The relay's queue fills at nine.</p>"


async def test_req_prb_071_incident_technicians_see_the_problem_narrowly(world: World) -> None:
    a, b = world.a, world.b
    incident = await world.create(a, a.admin)
    made = await new_problem(
        world, a, a.admin, group_id=str(a.ga), workaround=WORKAROUND, root_cause=ROOT_CAUSE
    )
    assert made.status_code == 201, made.text
    cause = made.json()
    linked = await world.call(
        "POST",
        f"{PRB}/{cause['id']}/incidents",
        a,
        a.admin,
        json={"incident_id": incident["id"], "move": False},
        headers=CONSOLE,
    )
    assert linked.status_code in {200, 201}, linked.text
    # Someone who works incidents but has no problem rights at all.
    incidents_only = await role(world, a, "Incidents only", [("incidents.view", "all")])
    granted = await world.call("PUT", f"/users/{a.requester2}/roles/{incidents_only}", a, a.admin)
    assert granted.status_code in {200, 204}, granted.text
    path = f"/incidents/{incident['id']}/causing-problem"

    seen = await world.call("GET", path, a, a.requester2)
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert (body["display_id"], body["subject"], body["may_open"]) == (
        cause["display_id"],
        cause["subject"],
        False,
    )
    assert body["workaround"] == WORKAROUND
    assert body["known_error"] is False
    # Q7: never the root cause, the analysis or the people.
    assert "root_cause" not in body
    assert "queue fills" not in seen.text.lower()
    # The problem itself stays closed to them.
    assert problem(await world.call("GET", f"{PRB}/{cause['id']}", a, a.requester2))[0] in {
        403,
        404,
    }
    # Who may see problems is told so.
    assert (await world.call("GET", path, a, a.tech_a)).json()["may_open"] is True
    # Another tenant never learns of it (RLS: the incident is not found there).
    assert problem(await world.call("GET", path, b, b.admin))[0] == 404


async def test_req_prb_071_no_cause_reads_as_null(world: World) -> None:
    a = world.a
    incident = await world.create(a, a.admin)
    found = await world.call("GET", f"/incidents/{incident['id']}/causing-problem", a, a.tech_a)
    assert found.status_code == 200, found.text
    assert found.json() is None


async def test_req_prb_075_the_requester_is_told_it_is_known_never_the_problem(
    world: World,
) -> None:
    a = world.a
    incident = await world.create(a, a.admin)  # the requester's own (world.create's default)
    made = await new_problem(world, a, a.admin, group_id=str(a.ga), root_cause=ROOT_CAUSE)
    cause = made.json()
    portal = f"/portal/incidents/{incident['id']}"
    before = (await world.call("GET", portal, a, a.requester)).json()
    assert "known_problem" not in before or before["known_problem"] is None
    linked = await world.call(
        "POST",
        f"{PRB}/{cause['id']}/incidents",
        a,
        a.admin,
        json={"incident_id": incident["id"], "move": False},
        headers=CONSOLE,
    )
    assert linked.status_code in {200, 201}, linked.text
    seen = await world.call("GET", portal, a, a.requester)
    assert seen.status_code == 200, seen.text
    assert seen.json()["known_problem"] == "being_worked_on"
    # Never the problem itself: its ID, title or root cause.
    for leak in (cause["id"], cause["display_id"], cause["subject"], "queue fills"):
        assert leak.lower() not in seen.text.lower()
    listed = await world.call("GET", "/portal/incidents", a, a.requester)
    row = next(r for r in listed.json()["items"] if r["id"] == incident["id"])
    assert row["known_problem"] == "being_worked_on"
