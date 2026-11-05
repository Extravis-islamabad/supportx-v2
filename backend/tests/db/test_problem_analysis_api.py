"""A problem's analysis, impact and evidence (WP-044b s1; REQ-PRB-030, -032, -033, -070).

D-140 Q7. Real Postgres.

Root cause and symptoms are rich text, sanitised. Changing them needs `problems.edit_analysis`.
The root cause is read only with `problems.view_root_cause`: without it, the record says
`root_cause_hidden` and the history leaves the change out. Technicians hold both for their
groups' problems. The impact counts only the caused incidents the reader may see.
"""

import uuid
from typing import Any

from app.modules.work_items.service.bulk import run_bulk_jobs
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
    assert body["open_seconds"] >= 0
    assert len(body["weekly"]) == 8  # every week, oldest first, zero when none
    assert body["weekly"][-1]["count"] == 3  # all reported this week

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


async def _merge_refusals(
    merge: Any,  # noqa: ANN401 - the test's own merge call
    a: Org,
    duplicate: dict[str, Any],
    survivor: dict[str, Any],
) -> None:
    """An old version, another group's technician, itself, and an unknown problem."""
    stale = await merge(a.tech_a, {**duplicate, "version": duplicate["version"] - 1}, survivor)
    assert problem(stale) == (409, "version_conflict")
    assert problem(await merge(a.tech_b, duplicate, survivor))[0] == 403  # GA's problems
    assert problem(await merge(a.tech_a, duplicate, duplicate))[0] == 422
    assert problem(await merge(a.tech_a, duplicate, {"id": str(uuid.uuid4())}))[0] == 404


async def test_merge_moves_the_incidents_and_undo_puts_them_back(world: World) -> None:
    """REQ-PRB-046 (WP-044b s2): merge duplicates with undo; both problems need edit."""
    a, b = world.a, world.b

    async def made(**values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
        done = await new_problem(world, a, a.tech_a, group_id=str(a.ga), **values)
        assert done.status_code == 201, done.text
        return dict(done.json())

    duplicate = await made(subject="Mail drops at 9")
    survivor = await made(subject="Mail relay drops messages")
    elsewhere = await made(subject="Another cause")
    first = await world.create(a, a.admin, group_id=str(a.ga))
    second = await world.create(a, a.admin, group_id=str(a.ga))
    for incident in (first, second):
        linked = await world.call(
            "POST",
            f"{PRB}/{duplicate['id']}/incidents",
            a,
            a.tech_a,
            json={"incident_id": incident["id"]},
        )
        assert linked.json() == {"linked": True}, linked.text

    async def fresh(record: dict[str, Any], user: uuid.UUID = a.tech_a) -> dict[str, Any]:
        return dict((await world.call("GET", f"{PRB}/{record['id']}", a, user)).json())

    async def merge(user: uuid.UUID, record: dict[str, Any], into: dict[str, Any]) -> Any:  # noqa: ANN401
        return await world.call(
            "POST",
            f"{PRB}/{record['id']}/merge",
            a,
            user,
            json={"into_id": into["id"]},
            headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
        )

    duplicate = await fresh(duplicate)
    await _merge_refusals(merge, a, duplicate, survivor)

    done = await merge(a.tech_a, duplicate, survivor)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "merged"
    assert set(body["moved_incident_ids"]) == {first["id"], second["id"]}
    links = (await world.call("GET", f"{PRB}/{survivor['id']}/links", a, a.tech_a)).json()
    assert {(link["relation"], link["other_id"]) for link in links} >= {
        ("causes", first["id"]),
        ("causes", second["id"]),
        ("merged_from", duplicate["id"]),
    }
    mine = (await world.call("GET", f"{PRB}/{duplicate['id']}/links", a, a.tech_a)).json()
    assert [(link["relation"], link["other_id"]) for link in mine] == [
        ("merged_into", survivor["id"])
    ]
    merged = await fresh(duplicate)
    again = await merge(a.tech_a, merged, survivor)
    assert problem(again) == (409, "problem_closed")  # a merged problem is closed
    assert problem(await merge(a.tech_a, await fresh(elsewhere), merged)) == (
        409,
        "problem_closed",
    )

    # Since the merge, one incident went to another problem: the undo leaves it there.
    moved = await world.call(
        "POST",
        f"{PRB}/{elsewhere['id']}/incidents",
        a,
        a.tech_a,
        json={"incident_id": second["id"], "move": True},
    )
    assert moved.json() == {"linked": True}, moved.text
    merged = await fresh(duplicate)
    undo = await world.call(
        "POST",
        f"{PRB}/{duplicate['id']}/undo-merge",
        a,
        a.tech_a,
        headers={"If-Match": f'"{merged["version"]}"', **CONSOLE},
    )
    assert undo.status_code == 200, undo.text
    back = undo.json()
    assert back["status"] == "new"  # the status it had
    assert back["moved_incident_ids"] == [first["id"]]
    assert back["stayed_incident_ids"] == [second["id"]]
    mine = (await world.call("GET", f"{PRB}/{duplicate['id']}/links", a, a.tech_a)).json()
    assert {(link["relation"], link["other_id"]) for link in mine} == {("causes", first["id"])}
    restored = await fresh(duplicate)
    nothing = await world.call(
        "POST",
        f"{PRB}/{duplicate['id']}/undo-merge",
        a,
        a.tech_a,
        headers={"If-Match": f'"{restored["version"]}"', **CONSOLE},
    )
    assert problem(nothing) == (409, "not_merged")
    history = await world.call("GET", f"{PRB}/{duplicate['id']}/history", a, a.tech_a)
    assert "merge" in {c["field"] for e in history.json()["items"] for c in e["changes"]}
    # Another tenant never reaches it.
    assert problem(await world.call("GET", f"{PRB}/{duplicate['id']}", b, b.admin))[0] == 404


async def test_unlinking_incidents_one_or_in_bulk(world: World) -> None:
    """REQ-PRB-043 (WP-044b s2): unlink with history on both; the incident's edit counts."""
    a = world.a
    prb = (await new_problem(world, a, a.tech_a, group_id=str(a.ga))).json()
    incidents = [await world.create(a, a.admin, group_id=str(a.ga)) for _ in range(3)]
    for incident in incidents:
        linked = await world.call(
            "POST",
            f"{PRB}/{prb['id']}/incidents",
            a,
            a.admin,
            json={"incident_id": incident["id"]},
        )
        assert linked.json() == {"linked": True}, linked.text
    # The generic link delete never removes a cause: that needs the incident's edit right.
    causes = (await world.call("GET", f"{PRB}/{prb['id']}/links", a, a.admin)).json()
    cause = next(link for link in causes if link["relation"] == "causes")
    generic = await world.call(
        "DELETE",
        f"{PRB}/{prb['id']}/links/{cause['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{cause["version"]}"', **CONSOLE},
    )
    assert problem(generic) == (409, "link_has_own_route")
    path = f"{PRB}/{prb['id']}/incidents/{incidents[0]['id']}"
    # tech_b cannot see GA's incident at all: 404, never a hint that it exists.
    assert problem(await world.call("DELETE", path, a, a.tech_b))[0] == 404
    gone = await world.call("DELETE", path, a, a.tech_a)
    assert gone.json() == {"unlinked": True}, gone.text
    again = await world.call("DELETE", path, a, a.tech_a)
    assert again.json() == {"unlinked": False}
    history = await world.call("GET", f"{PRB}/{prb['id']}/history", a, a.tech_a)
    removed = [
        c
        for e in history.json()["items"]
        for c in e["changes"]
        if c["field"] == "link" and c["new"] is None
    ]
    assert [c["old"]["id"] for c in removed] == [incidents[0]["id"]]

    started = await world.call(
        "POST",
        "/incidents/bulk",
        a,
        a.tech_a,
        json={
            "action": "unlink_problem",
            "record_ids": [i["id"] for i in incidents[1:]],
            "changes": {"problem_id": prb["id"]},
        },
    )
    assert started.status_code in {200, 202}, started.text
    await run_bulk_jobs(world.app.state.db, world.app.state.settings)
    left = (await world.call("GET", f"{PRB}/{prb['id']}/links", a, a.tech_a)).json()
    assert [link for link in left if link["relation"] == "causes"] == []
    on_problem = await world.call(
        "POST",
        f"{PRB}/bulk",
        a,
        a.tech_a,
        json={"action": "unlink_problem", "record_ids": [prb["id"]]},
    )
    assert problem(on_problem)[0] == 422  # only incidents have a cause
