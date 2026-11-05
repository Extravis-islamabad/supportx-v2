"""A problem's analysis, impact and evidence (WP-044b s1; REQ-PRB-030, -032, -033, -070).

D-140 Q7. Real Postgres.

Root cause and symptoms are rich text, sanitised. Changing them needs `problems.edit_analysis`.
The root cause is read only with `problems.view_root_cause`: without it, the record says
`root_cause_hidden` and the history leaves the change out. Technicians hold both for their
groups' problems. The impact counts only the caused incidents the reader may see.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import CONSOLE, Org, World, problem, role, world
from tests.db.test_problems_api import PRB, new_problem

__all__ = ["world"]  # the fixture, re-used


async def patch(
    world: World,
    org: Org,
    user: uuid.UUID,
    record: dict[str, Any],
    **values: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - an httpx response
    return await world.call(
        "PATCH",
        f"{PRB}/{record['id']}",
        org,
        user,
        json=values,
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )


async def test_the_root_cause_is_for_problem_roles_only(world: World) -> None:
    a = world.a
    made = await new_problem(
        world,
        a,
        a.tech_a,
        group_id=str(a.ga),
        symptoms="<p>Mail times out at 9.</p>",
        root_cause="<p>Expired cert on the relay<script>alert(1)</script></p>",
    )
    assert made.status_code == 201, made.text
    record = made.json()
    assert record["root_cause"] == "<p>Expired cert on the relay</p>"  # sanitised
    assert record["root_cause_hidden"] is False
    ops = {o["action"]: o["allowed"] for o in record["operations"]}
    assert ops["edit_analysis"] is True

    # tech_b sees every problem but works only GB's: no root cause, symptoms still shown.
    seen = await world.call("GET", f"{PRB}/{record['id']}", a, a.tech_b)
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert (body["root_cause"], body["root_cause_hidden"]) == (None, True)
    assert body["symptoms"] == "<p>Mail times out at 9.</p>"
    assert {o["action"]: o["allowed"] for o in body["operations"]}["edit_analysis"] is False
    refused = await patch(world, a, a.tech_b, body, root_cause="<p>Guess</p>")
    assert problem(refused)[0] == 403
    refused = await patch(world, a, a.tech_b, body, symptoms="<p>More</p>")
    assert problem(refused)[0] == 403

    # A change is in the history for tech_a, and left out for tech_b.
    changed = await patch(world, a, a.tech_a, record, root_cause="<p>Relay cert expired</p>")
    assert changed.status_code == 200, changed.text

    async def fields(user: uuid.UUID) -> set[str]:
        page = await world.call("GET", f"{PRB}/{record['id']}/history", a, user)
        assert page.status_code == 200, page.text
        return {c["field"] for e in page.json()["items"] for c in e["changes"]}

    assert {"root_cause", "symptoms"} <= await fields(a.tech_a)
    # Who last changed each field, and when (REQ-PRB-030); the hidden one is left out.
    mine = (await world.call("GET", f"{PRB}/{record['id']}", a, a.tech_a)).json()
    last = {c["field"]: c["changed_by"] for c in mine["analysis_changes"]}
    assert last == {"root_cause": str(a.tech_a), "symptoms": str(a.tech_a)}
    assert str(a.tech_a) in mine["people"]
    theirs = (await world.call("GET", f"{PRB}/{record['id']}", a, a.tech_b)).json()
    assert {c["field"] for c in theirs["analysis_changes"]} == {"symptoms"}
    hidden = await fields(a.tech_b)
    assert "root_cause" not in hidden
    assert "symptoms" in hidden

    # An admin can widen it: a role with view_root_cause for all reads it.
    reader = await role(
        world,
        a,
        "Root cause reader",
        [("problems.view", "all"), ("problems.view_root_cause", "all")],
    )
    granted = await world.call("PUT", f"/users/{a.tech_b}/roles/{reader}", a, a.admin)
    assert granted.status_code in {200, 204}, granted.text
    widened = await world.call("GET", f"{PRB}/{record['id']}", a, a.tech_b)
    assert widened.json()["root_cause"] == "<p>Relay cert expired</p>"


async def test_analysis_fields_are_for_problems_and_need_the_right_on_create(
    world: World,
) -> None:
    a = world.a
    on_incident = await world.call(
        "POST",
        "/incidents",
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "root_cause": "<p>x</p>"},
        headers=CONSOLE,
    )
    assert {e["field"]: e["code"] for e in on_incident.json()["errors"]} == {
        "body.root_cause": "not_allowed"
    }
    # A role that creates problems but holds no analysis right may not fill it in.
    maker = await role(
        world, a, "Problem maker", [("problems.view", "all"), ("problems.create", "all")]
    )
    granted = await world.call("PUT", f"/users/{a.requester2}/roles/{maker}", a, a.admin)
    assert granted.status_code in {200, 204}, granted.text
    refused = await new_problem(world, a, a.requester2, symptoms="<p>x</p>")
    assert problem(refused)[0] == 403
    assert (await new_problem(world, a, a.requester2)).status_code == 201


async def test_impact_and_evidence_count_only_incidents_you_may_see(world: World) -> None:
    a, b = world.a, world.b
    prb = (await new_problem(world, a, a.admin, group_id=str(a.ga))).json()
    in_ga = await world.create(a, a.admin, group_id=str(a.ga))
    in_ga2 = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    in_gb = await world.create(a, a.admin, group_id=str(a.gb))
    for incident in (in_ga, in_ga2, in_gb):
        linked = await world.call(
            "POST", f"{PRB}/{prb['id']}/incidents", a, a.admin, json={"incident_id": incident["id"]}
        )
        assert linked.json() == {"linked": True}, linked.text

    full = await world.call("GET", f"{PRB}/{prb['id']}/impact", a, a.admin)
    assert full.status_code == 200, full.text
    body = full.json()
    assert (body["incidents"], body["open_incidents"], body["partial"]) == (3, 3, False)
    assert sum(p["count"] for p in body["by_priority"]) == 3
    assert body["people"] == 2  # requester and requester2

    # Someone who sees GA's incidents only gets GA's figures, marked partial.
    narrow = await role(
        world, a, "GA incidents", [("problems.view", "all"), ("incidents.view", "group")]
    )
    await world.call("PUT", f"/users/{a.requester2}/roles/{narrow}", a, a.admin)
    await world.call("PUT", f"/organization/groups/{a.ga}/members/{a.requester2}", a, a.admin)
    part = (await world.call("GET", f"{PRB}/{prb['id']}/impact", a, a.requester2)).json()
    assert (part["incidents"], part["partial"]) == (2, True)

    other = await world.call("GET", f"{PRB}/{prb['id']}/impact", b, b.admin)
    assert problem(other)[0] == 404  # RLS

    # The evidence timeline: oldest report first, the same records left out, and what's pending.
    full_ev = (await world.call("GET", f"{PRB}/{prb['id']}/evidence", a, a.admin)).json()
    assert [i["id"] for i in full_ev["incidents"]] == [in_ga["id"], in_ga2["id"], in_gb["id"]]
    assert full_ev["left_out"] is False
    assert full_ev["pending_sources"] == ["changes", "releases", "same_items"]
    part_ev = (await world.call("GET", f"{PRB}/{prb['id']}/evidence", a, a.requester2)).json()
    assert {i["id"] for i in part_ev["incidents"]} == {in_ga["id"], in_ga2["id"]}
    assert part_ev["left_out"] is True
    gone = await world.call("GET", f"{PRB}/{prb['id']}/evidence", b, b.admin)
    assert problem(gone)[0] == 404
