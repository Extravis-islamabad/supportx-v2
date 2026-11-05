"""Known errors (WP-044b s3; REQ-PRB-034, -036, -037, -038, -042). Real Postgres.

The workaround needs problems.edit_solution. Marking needs problems.mark_known_error and a
workaround or root cause written; removing needs a reason. Resolving retires it. The database
searches subject, symptoms and workaround, never the root cause. Suggestions match an incident's
words to open known errors the technician may see.
"""

import uuid
from datetime import datetime
from typing import Any

from app.modules.work_items.service.bulk import run_bulk_jobs
from tests.db.test_incidents_api import CONSOLE, Org, World, field_codes, problem, role, world
from tests.db.test_knowledge_api import _new, _topic
from tests.db.test_problems_api import PRB, new_problem

__all__ = ["world"]  # the fixture, re-used


async def fresh(world: World, org: Org, user: uuid.UUID, record: dict[str, Any]) -> dict[str, Any]:
    return dict((await world.call("GET", f"{PRB}/{record['id']}", org, user)).json())


async def post(
    world: World,
    org: Org,
    user: uuid.UUID,
    record: dict[str, Any],
    path: str,
    body: dict[str, Any],
) -> Any:  # noqa: ANN401 - an httpx response
    return await world.call(
        "POST",
        f"{PRB}/{record['id']}/{path}",
        org,
        user,
        json=body,
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )


async def test_marking_needs_something_written_and_removing_needs_a_reason(world: World) -> None:
    a = world.a
    record = (await new_problem(world, a, a.tech_a, group_id=str(a.ga))).json()
    empty = await post(world, a, a.tech_a, record, "known-error", {})
    assert field_codes(empty) == {
        "workaround": "required_for_known_error",
        "root_cause": "required_for_known_error",
    }
    # Another group's technician may read it but not write the solution or mark it.
    patched = await world.call(
        "PATCH",
        f"{PRB}/{record['id']}",
        a,
        a.tech_b,
        json={"workaround": "<p>Restart the relay.</p>"},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert problem(patched)[0] == 403
    done = await world.call(
        "PATCH",
        f"{PRB}/{record['id']}",
        a,
        a.tech_a,
        json={"workaround": "<p>Restart the relay.</p>"},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert done.status_code == 200, done.text
    record = done.json()
    assert problem(await post(world, a, a.tech_b, record, "known-error", {}))[0] == 403
    marked = await post(world, a, a.tech_a, record, "known-error", {"comment": "Seen 3 times"})
    assert marked.status_code == 200, marked.text
    record = marked.json()
    assert record["known_error_at"] is not None
    assert problem(await post(world, a, a.tech_a, record, "known-error", {})) == (
        409,
        "already_known_error",
    )
    no_reason = await post(world, a, a.tech_a, record, "known-error/remove", {"reason": ""})
    assert problem(no_reason)[0] == 422
    removed = await post(
        world, a, a.tech_a, record, "known-error/remove", {"reason": "Not a known error"}
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["known_error_at"] is None
    history = await world.call("GET", f"{PRB}/{record['id']}/history", a, a.tech_a)
    reasons = {e["reason"] for e in history.json()["items"]}
    assert {"Seen 3 times", "Not a known error"} <= reasons


async def test_database_search_retire_on_resolve_and_suggestions(world: World) -> None:
    a, b = world.a, world.b
    record = (
        await new_problem(
            world,
            a,
            a.tech_a,
            group_id=str(a.ga),
            subject="Mail relay drops messages",
            symptoms="<p>Error 4.4.2 connection dropped</p>",
            workaround="<p>Restart the relay service.</p>",
            root_cause="<p>Secret cert expired</p>",
        )
    ).json()
    record = (await post(world, a, a.tech_a, record, "known-error", {})).json()

    async def search(q: str, user: uuid.UUID = a.tech_a, org: Org = a) -> list[dict[str, Any]]:
        found = await world.call("GET", f"{PRB}/known-errors?q={q}", org, user)
        assert found.status_code == 200, found.text
        return list(found.json())

    hits = await search("4.4.2")  # only in the symptoms (REQ-PRB-037 AC1)
    assert [h["display_id"] for h in hits] == [record["display_id"]]
    assert "root_cause" not in hits[0]
    assert await search("Secret") == []  # never searched in the root cause (D-140 Q7)
    assert await search("4.4.2", b.admin, b) == []  # another tenant

    incident = await world.create(
        a,
        a.admin,
        group_id=str(a.ga),
        subject="Mail keeps failing",
        description="<p>Users see Error 4.4.2 when sending</p>",
    )
    suggested = await world.call(
        "GET", f"{PRB}/known-errors/suggestions?incident_id={incident['id']}", a, a.tech_a
    )
    assert [s["display_id"] for s in suggested.json()] == [record["display_id"]]
    assert suggested.json()[0]["workaround"] == "<p>Restart the relay service.</p>"
    linked = await world.call(
        "POST", f"{PRB}/{record['id']}/incidents", a, a.admin, json={"incident_id": incident["id"]}
    )
    assert linked.json() == {"linked": True}, linked.text
    links = (await world.call("GET", f"/incidents/{incident['id']}/links", a, a.admin)).json()
    assert [(link["relation"], link["other_known_error"]) for link in links] == [
        ("caused_by", True)
    ]  # REQ-PRB-036 AC3: the incident shows the marker

    # Resolving it retires it; it stays in the database, marked, and leaves the suggestions.
    record = await fresh(world, a, a.tech_a, record)
    for action, body in (
        ("investigate", {}),
        ("confirm_root_cause", {}),
        ("resolve", {"resolution": "<p>New certificate.</p>"}),
    ):
        moved = await post(world, a, a.tech_a, record, f"actions/{action}", body)
        assert moved.status_code == 200, moved.text
        record = moved.json()
    assert record["known_error_retired_at"] is not None
    retired = await search("4.4.2")
    assert retired[0]["retired_at"] is not None
    live_only = await world.call(
        "GET", f"{PRB}/known-errors?q=4.4.2&include_retired=false", a, a.tech_a
    )
    assert live_only.json() == []
    gone = await world.call(
        "GET", f"{PRB}/known-errors/suggestions?incident_id={incident['id']}", a, a.tech_a
    )
    assert gone.json() == []
    history = await world.call("GET", f"{PRB}/{record['id']}/history", a, a.tech_a)
    fields = {c["field"] for e in history.json()["items"] for c in e["changes"]}
    assert "known_error_retired_at" in fields


async def test_a_role_without_the_rights_cannot_write_the_workaround(world: World) -> None:
    a = world.a
    viewer = await role(
        world, a, "Problem viewer", [("problems.view", "all"), ("problems.edit", "all")]
    )
    await world.call("PUT", f"/users/{a.requester2}/roles/{viewer}", a, a.admin)
    record = (await new_problem(world, a, a.admin)).json()
    refused = await world.call(
        "PATCH",
        f"{PRB}/{record['id']}",
        a,
        a.requester2,
        json={"workaround": "<p>x</p>"},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert problem(refused)[0] == 403
    ops = {
        o["action"]: o["allowed"]
        for o in (await fresh(world, a, a.requester2, record))["operations"]
    }
    assert (ops["edit_solution"], ops["mark_known_error"]) == (False, False)


async def test_a_problem_resolution_saves_as_knowledge(world: World) -> None:
    """REQ-PRB-041: a draft from the problem's title and resolution, linked to it."""
    a = world.a
    topic = await _topic(world, a, "Problems")
    record = (await new_problem(world, a, a.tech_a, group_id=str(a.ga))).json()
    for action, body in (
        ("investigate", {}),
        ("resolve", {"resolution": "<p>Renew the relay certificate.</p>"}),
    ):
        moved = await post(world, a, a.tech_a, record, f"actions/{action}", body)
        assert moved.status_code == 200, moved.text
        record = moved.json()
    body = {"record_type": "problem", "record_id": record["id"], "topic_id": topic["id"]}
    made = await world.call(
        "POST", "/knowledge/articles/from-record", a, a.tech_a, json=body, headers=_new()
    )
    assert made.status_code == 201, made.text
    draft = made.json()["article"]["drafts"]["en"]
    assert draft["title"] == record["subject"]
    assert "Renew the relay certificate" in draft["body_html"]
    links = await world.call(
        "GET", f"/knowledge/records/problem/{record['id']}/articles", a, a.tech_a
    )
    assert [i["source"] for i in links.json()["items"]] == ["created_from"]
    # Someone who cannot see problems: not found, and nothing is made.
    hidden = await world.call(
        "POST", "/knowledge/articles/from-record", a, a.requester, json=body, headers=_new()
    )
    assert problem(hidden)[0] in {403, 404}


async def _closed_attempt(
    world: World, org: Org, user: uuid.UUID, priority_impact: tuple[str, str]
) -> tuple[dict[str, Any], Any]:
    """A resolved problem of that impact and urgency, and its first close attempt."""
    impact, urgency = priority_impact
    record = (
        await new_problem(world, org, user, group_id=str(org.ga), impact=impact, urgency=urgency)
    ).json()
    for action, body in (
        ("investigate", {}),
        ("resolve", {"resolution": "<p>Fixed.</p>"}),
    ):
        moved = await post(world, org, user, record, f"actions/{action}", body)
        assert moved.status_code == 200, moved.text
        record = moved.json()
    closing = await post(world, org, user, record, "actions/close", {"closure_code": "fixed"})
    return record, closing


async def test_the_review_is_a_closure_rule_for_p1_and_the_listed_priorities(
    world: World,
) -> None:
    """REQ-PRB-053, D-140 Q4: P1 (and major) need the review; P2 only when the admin lists it."""
    a = world.a
    p1, refused = await _closed_attempt(world, a, a.tech_a, ("organisation", "critical"))
    assert p1["priority"] == "p1", p1["priority"]
    assert p1["review_required"] is True
    assert field_codes(refused) == {"review_summary": "required_to_close"}
    close = {o["action"]: o for o in p1["actions"]}["close"]
    assert "review_summary" in close["missing"]
    reviewed = await world.call(
        "PATCH",
        f"{PRB}/{p1['id']}",
        a,
        a.tech_a,
        json={"review_summary": "<p>Cert monitoring added.</p>"},
        headers={"If-Match": f'"{p1["version"]}"', **CONSOLE},
    )
    assert reviewed.status_code == 200, reviewed.text
    closed = await post(
        world, a, a.tech_a, reviewed.json(), "actions/close", {"closure_code": "fixed"}
    )
    assert closed.status_code == 200, closed.text

    low, done = await _closed_attempt(world, a, a.tech_a, ("one_person", "low"))
    assert low["review_required"] is False
    assert done.status_code == 200, done.text  # no review needed

    settings = (await world.call("GET", f"{PRB}/settings", a, a.admin)).json()
    assert settings["review_required_priorities"] == ["p1"]


async def test_problem_approvals_decide_and_accept_a_known_error_without_a_fix(
    world: World,
) -> None:
    """WP-044b s4 (REQ-PRB-050): ad hoc approvals on a problem; acceptance sets a review date."""
    a = world.a
    record = (
        await new_problem(
            world, a, a.tech_a, group_id=str(a.ga), workaround="<p>Restart the relay.</p>"
        )
    ).json()

    async def ask(rec: dict[str, Any], purpose: str) -> Any:  # noqa: ANN401 - an httpx response
        return await post(
            world,
            a,
            a.tech_a,
            rec,
            "approvals",
            {"approver_ids": [str(a.tech_b)], "purpose": purpose},
        )

    not_known = await ask(record, "accept_without_fix")
    assert problem(not_known) == (409, "not_known_error")
    record = (await post(world, a, a.tech_a, record, "known-error", {})).json()
    asked = await ask(record, "accept_without_fix")
    assert asked.status_code == 200, asked.text
    record = asked.json()
    assert record["approval_status"] == "pending"
    assert problem(await ask(record, "record")) == (409, "approval_pending")

    inbox = (await world.call("GET", f"{PRB}/my-approvals", a, a.tech_b)).json()
    mine = [p for p in inbox["items"] if p["record_id"] == record["id"]]
    assert len(mine) == 1, inbox
    rows = (await world.call("GET", f"{PRB}/{record['id']}/approvals", a, a.tech_b)).json()
    row = rows["items"][0] if isinstance(rows, dict) else rows[0]
    decided = await world.call(
        "POST",
        f"{PRB}/{record['id']}/approvals/{row['id']}/decision",
        a,
        a.tech_b,
        json={"decision": "approve", "comment": "Too costly to fix now"},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert decided.status_code == 200, decided.text
    after = await fresh(world, a, a.tech_a, record)
    assert after["approval_status"] == "approved"
    assert after["status"] == record["status"]  # a decision never moves a problem
    assert after["accepted_at"] is not None
    days = (
        datetime.fromisoformat(after["accept_review_at"])
        - datetime.fromisoformat(after["accepted_at"])
    ).days
    assert days == 90


async def test_messages_go_to_sets_and_to_each_linked_incident(world: World) -> None:
    """REQ-PRB-052: recipients by set, and requesters reached through their incidents."""
    a = world.a
    prb = (await new_problem(world, a, a.tech_a, group_id=str(a.ga))).json()
    one = await world.create(
        a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a), requester_id=str(a.requester)
    )
    two = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    for incident in (one, two):
        linked = await world.call(
            "POST", f"{PRB}/{prb['id']}/incidents", a, a.admin, json={"incident_id": incident["id"]}
        )
        assert linked.json() == {"linked": True}, linked.text

    async def people(which: str) -> set[str]:
        got = await world.call(
            "GET", f"{PRB}/{prb['id']}/message-recipients?set={which}", a, a.tech_a
        )
        assert got.status_code == 200, got.text
        return {r["user_id"] for r in got.json()}

    assert await people("incident_requesters") == {str(a.requester), str(a.requester2)}
    assert await people("incident_technicians") == {str(a.tech_a)}

    sent = await world.call(
        "POST",
        f"{PRB}/{prb['id']}/messages/incident-requesters",
        a,
        a.tech_a,
        json={"body": "<p>We found the cause; a fix is on its way.</p>"},
        headers=CONSOLE,
    )
    assert sent.status_code == 200, sent.text
    assert sorted(sent.json()["sent_to"]) == sorted([one["display_id"], two["display_id"]])
    for incident in (one, two):
        timeline = await world.call("GET", f"/incidents/{incident['id']}/conversation", a, a.tech_a)
        assert timeline.status_code == 200, timeline.text
        bodies = [e["body"] for e in timeline.json()["items"]]
        assert any("a fix is on its way" in b for b in bodies)
    history = await world.call("GET", f"{PRB}/{prb['id']}/history", a, a.tech_a)
    fields = {c["field"] for e in history.json()["items"] for c in e["changes"]}
    assert "requester_message" in fields


async def test_follow_up_resolves_the_chosen_linked_incidents(world: World) -> None:
    """REQ-PRB-055, D-140 Q1: preview, untick, then each incident resolved by its own rules."""
    a = world.a
    record = (await new_problem(world, a, a.tech_a, group_id=str(a.ga))).json()
    incidents = [await world.create(a, a.admin, group_id=str(a.ga)) for _ in range(3)]
    for incident in incidents:
        linked = await world.call(
            "POST",
            f"{PRB}/{record['id']}/incidents",
            a,
            a.admin,
            json={"incident_id": incident["id"]},
        )
        assert linked.json() == {"linked": True}, linked.text
    record = await fresh(world, a, a.tech_a, record)
    for action, body in (("investigate", {}), ("resolve", {"resolution": "<p>New cert.</p>"})):
        moved = await post(world, a, a.tech_a, record, f"actions/{action}", body)
        assert moved.status_code == 200, moved.text
        record = moved.json()

    preview = (await world.call("GET", f"{PRB}/{record['id']}/follow-up", a, a.tech_a)).json()
    assert {i["id"] for i in preview["incidents"]} == {i["id"] for i in incidents}
    assert (preview["has_resolution"], preview["has_workaround"]) == (True, False)
    chosen = [incidents[0]["id"], incidents[1]["id"]]  # the third is unticked (AC1)
    started = await world.call(
        "POST",
        f"{PRB}/{record['id']}/follow-up",
        a,
        a.tech_a,
        json={"incident_ids": chosen, "copy_text": "resolution"},
        headers=CONSOLE,
    )
    assert started.status_code == 202, started.text
    await run_bulk_jobs(world.app.state.db, world.app.state.settings)

    async def read(item: dict[str, Any]) -> dict[str, Any]:
        return dict((await world.call("GET", f"/incidents/{item['id']}", a, a.admin)).json())

    for item in incidents[:2]:
        done = await read(item)
        assert done["status_category"] == "resolved", done["status"]  # the requester confirms
        assert "New cert." in (done["resolution"] or "")
        history = await world.call("GET", f"/incidents/{item['id']}/history", a, a.admin)
        named = [
            c["new"]
            for e in history.json()["items"]
            for c in e["changes"]
            if c["field"] == "follow_up_of"
        ]
        assert named == [record["display_id"]]  # AC4
    assert (await read(incidents[2]))["status_category"] != "resolved"  # left as it was
    nothing = await world.call(
        "POST",
        f"{PRB}/{record['id']}/follow-up",
        a,
        a.tech_a,
        json={"incident_ids": [incidents[0]["id"]], "copy_text": "workaround"},
        headers=CONSOLE,
    )
    assert problem(nothing)[0] == 422  # resolved already, and no workaround written


async def test_a_problem_waiting_for_approval_cannot_close(world: World) -> None:
    """REQ-PRB-054: approvals must be decided before closing."""
    a = world.a
    record = (await new_problem(world, a, a.tech_a, group_id=str(a.ga))).json()
    for action, body in (("investigate", {}), ("resolve", {"resolution": "<p>Fixed.</p>"})):
        record = (await post(world, a, a.tech_a, record, f"actions/{action}", body)).json()
    asked = await post(world, a, a.tech_a, record, "approvals", {"approver_ids": [str(a.tech_b)]})
    assert asked.status_code == 200, asked.text
    refused = await post(
        world, a, a.tech_a, asked.json(), "actions/close", {"closure_code": "fixed"}
    )
    assert problem(refused) == (409, "approval_pending")
