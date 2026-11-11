"""Changes' tasks, review and closure over HTTP (WP-045d S1; REQ-CHG-088, -090..097).

Real PostgreSQL with RLS. Tasks belong to a stage and hold the move out of it; the review is
written in its own plan sections, never a reason to approve again; closing waits for child
changes and releases; a closed change is locked, every write refused with a labelled code.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_changes_api import CHG, _approve_pending, a_change, move
from tests.db.test_incidents_api import CONSOLE, Org, World, problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def task(world: World, org: Org, item: dict[str, Any], **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "POST",
        f"{CHG}/{item['id']}/tasks",
        org,
        org.admin,
        json={"title": "Back up the switch config", **body},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def fresh(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    return dict((await world.call("GET", f"{CHG}/{item['id']}", org, org.admin)).json())


async def to_planning(world: World, org: Org) -> dict[str, Any]:
    item = await a_change(world, org)
    item = (await move(world, org, item, "submission_awaiting_acceptance")).json()
    return await _approve_pending(world, org, item)


async def closed_change(world: World, org: Org) -> dict[str, Any]:
    """A change closed on the standard path (submission, implementation, review, closure)."""
    made = await world.call(
        "POST",
        CHG,
        org,
        org.admin,
        json={
            "subject": "Patch Tuesday",
            "requester_id": str(org.requester),
            "change_type": "standard",
        },
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    item = made.json()
    item = (await move(world, org, item, "implementation_in_progress")).json()
    rows = (await world.call("GET", f"{CHG}/{item['id']}/schedule", org, org.admin)).json()
    row = next(r for r in rows if r["stage"] == "implementation")
    await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/schedule/implementation",
        org,
        org.admin,
        json={"outcome": "successful"},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    item = await fresh(world, org, item)
    item = (await move(world, org, item, "implementation_implemented")).json()
    codes = (await world.call("GET", f"{CHG}/settings", org, org.admin)).json()["closure_codes"]
    closed = await world.call(
        "POST",
        f"{CHG}/{item['id']}/moves",
        org,
        org.admin,
        json={
            "to_status": "review_complete",
            "closure_code": codes[0]["code"],
            "resolution": "<p>Rolled out to every site.</p>",
        },
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closure_closed"
    return dict(closed.json())


async def test_req_chg_088_a_task_belongs_to_the_stage_it_was_made_in(world: World) -> None:
    a = world.a
    item = await to_planning(world, a)
    made = await task(world, a, item)
    assert made.status_code == 201, made.text
    assert made.json()["stage"] == "planning"
    later = await task(world, a, item, title="Check the backout on the lab", stage="cab_review")
    assert later.json()["stage"] == "cab_review"
    wrong = await task(world, a, item, stage="build")  # not on a change's normal path
    assert "invalid_choice" in wrong.text, wrong.text


async def test_req_chg_094_a_stage_is_left_only_with_its_own_tasks_done(world: World) -> None:
    a = world.a
    item = await to_planning(world, a)
    made = (await task(world, a, item)).json()
    await world.call(
        "PUT",
        f"{CHG}/{item['id']}/plan/backout",
        a,
        a.admin,
        json={"content": "<p>Restore the saved configuration</p>"},
        headers={"If-Match": '"0"', **CONSOLE},
    )
    item = await fresh(world, a, item)
    item = (await move(world, a, item, "planning_awaiting_approval")).json()
    # The plan's approval would move the change on to the CAB: the planning task holds it.
    rows = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()
    [entry] = [r for r in rows["items"] if r["state"] == "pending"]
    held = await world.call(
        "POST",
        f"{CHG}/{item['id']}/approvals/{entry['id']}/decision",
        a,
        a.admin,
        json={"decision": "approve"},
        headers={"If-Match": f'"{entry["version"]}"', **CONSOLE},
    )
    # The approval would move the change out of planning: the open task holds it, and says so.
    assert problem(held) == (409, "stage_move_refused"), held.text
    assert held.json()["params"]["reason"] == "stage_tasks_open"
    assert (await fresh(world, a, item))["stage"] == "planning"
    done = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/tasks/{made['id']}",
        a,
        a.admin,
        json={"status": "done"},
        headers={"If-Match": f'"{made["version"]}"', **CONSOLE},
    )
    assert done.status_code == 200, done.text
    approved = await _approve_pending(world, a, await fresh(world, a, item))
    assert approved["stage"] == "cab_review", approved


async def test_req_chg_096_closing_waits_for_child_changes_and_never_loops(world: World) -> None:
    a = world.a
    parent = await a_change(world, a)
    child = await a_change(world, a)
    url = f"{CHG}/{parent['id']}/children"
    added = await world.call(
        "POST", url, a, a.admin, json={"child_id": child["id"]}, headers=CONSOLE
    )
    assert added.status_code == 201, added.text
    listed = (await world.call("GET", url, a, a.admin)).json()
    assert [c["display_id"] for c in listed] == [child["display_id"]]
    # One parent each, and never a loop.
    other = await a_change(world, a)
    again = await world.call(
        "POST",
        f"{CHG}/{other['id']}/children",
        a,
        a.admin,
        json={"child_id": child["id"]},
        headers=CONSOLE,
    )
    assert "already_linked" in again.text, again.text
    loop = await world.call(
        "POST",
        f"{CHG}/{child['id']}/children",
        a,
        a.admin,
        json={"child_id": parent["id"]},
        headers=CONSOLE,
    )
    assert "change_would_loop" in loop.text, loop.text
    # Canceling the parent is never held up by its children.
    parent = await fresh(world, a, parent)
    canceled = await move(world, a, parent, "closure_canceled", reason_text="Not needed")
    assert canceled.status_code == 200, canceled.text


async def test_req_chg_096_a_closing_move_is_refused_while_a_child_is_open(world: World) -> None:
    a = world.a
    child = await a_change(world, a)
    made = await world.call(
        "POST",
        CHG,
        a,
        a.admin,
        json={"subject": "Parent", "requester_id": str(a.requester), "change_type": "standard"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    parent = made.json()
    added = await world.call(
        "POST",
        f"{CHG}/{parent['id']}/children",
        a,
        a.admin,
        json={"child_id": child["id"]},
        headers=CONSOLE,
    )
    assert added.status_code == 201, added.text
    parent = (
        await move(world, a, await fresh(world, a, parent), "implementation_in_progress")
    ).json()
    rows = (await world.call("GET", f"{CHG}/{parent['id']}/schedule", a, a.admin)).json()
    row = next(r for r in rows if r["stage"] == "implementation")
    await world.call(
        "PATCH",
        f"{CHG}/{parent['id']}/schedule/implementation",
        a,
        a.admin,
        json={"outcome": "successful"},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    parent = (
        await move(world, a, await fresh(world, a, parent), "implementation_implemented")
    ).json()
    panel = (await world.call("GET", f"{CHG}/{parent['id']}/stages", a, a.admin)).json()
    complete = next(m for m in panel["moves"] if m["to_status"] == "review_complete")
    assert complete["lands_in"] == "closure_closed"
    codes = (await world.call("GET", f"{CHG}/settings", a, a.admin)).json()["closure_codes"]
    refused = await world.call(
        "POST",
        f"{CHG}/{parent['id']}/moves",
        a,
        a.admin,
        json={"to_status": "review_complete", "closure_code": codes[0]["code"]},
        headers={"If-Match": f'"{parent["version"]}"', **CONSOLE},
    )
    assert problem(refused) == (409, "stage_move_refused"), refused.text
    assert refused.json()["params"]["reason"] == "children_open"
    # Once the child is done (canceled here), the parent closes.
    child = await fresh(world, a, child)
    gone = await move(world, a, child, "closure_canceled", reason_text="Folded into the parent")
    assert gone.status_code == 200, gone.text
    closed = await world.call(
        "POST",
        f"{CHG}/{parent['id']}/moves",
        a,
        a.admin,
        json={"to_status": "review_complete", "closure_code": codes[0]["code"]},
        headers={"If-Match": f'"{parent["version"]}"', **CONSOLE},
    )
    assert closed.status_code == 200, closed.text


async def test_req_chg_090_the_review_is_written_without_asking_for_approval_again(
    world: World,
) -> None:
    a = world.a
    item = await to_planning(world, a)
    sections = (await world.call("GET", f"{CHG}/{item['id']}/plan", a, a.admin)).json()
    names = [s["section"] for s in sections]
    assert {"review_findings", "review_went_well", "review_went_badly"} <= set(names)
    wrote = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/plan/review_findings",
        a,
        a.admin,
        json={"content": "<p>No issues.</p>"},
        headers={"If-Match": '"0"', **CONSOLE},
    )
    assert wrote.status_code == 200, wrote.text
    since = (
        await world.call("GET", f"{CHG}/{item['id']}/approvals/changes-since", a, a.admin)
    ).json()
    assert all(not s["changes"] for s in since), since  # the review is never "changed since"


async def test_req_chg_091_the_review_date_is_kept_with_the_change(world: World) -> None:
    a = world.a
    item = await a_change(world, a)
    due = (datetime.now(UTC) + timedelta(days=14)).replace(microsecond=0)
    current = (await world.call("GET", f"{CHG}/{item['id']}/details", a, a.admin)).json()
    saved = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/details",
        a,
        a.admin,
        json={"review_due_at": due.isoformat()},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert saved.status_code == 200, saved.text
    assert datetime.fromisoformat(saved.json()["review_due_at"]) == due


async def test_req_chg_097_a_closed_change_is_locked_with_a_labelled_code(world: World) -> None:
    """The coordinator: every write refused with `record_closed`, never a raw error."""
    a = world.a
    item = await closed_change(world, a)
    assert item["resolution"] == "<p>Rolled out to every site.</p>"  # REQ-CHG-095's description
    version = {"If-Match": f'"{item["version"]}"', **CONSOLE}
    writes = [
        ("PATCH", f"{CHG}/{item['id']}", {"subject": "Changed"}, version),
        ("PATCH", f"{CHG}/{item['id']}/details", {"change_reason": None}, version),
        (
            "PUT",
            f"{CHG}/{item['id']}/plan/impact",
            {"content": "<p>x</p>"},
            {"If-Match": '"0"', **CONSOLE},
        ),
        (
            "POST",
            f"{CHG}/{item['id']}/tasks",
            {"title": "Late task"},
            {"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
        ),
        (
            "POST",
            f"{CHG}/{item['id']}/downtimes",
            {
                "starts_at": "2027-05-01T00:00:00Z",
                "ends_at": "2027-05-01T01:00:00Z",
            },
            {"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
        ),
    ]
    other = await a_change(world, a)
    writes += [
        # Lane B's review of #378: children and the freeze override are locked too.
        ("POST", f"{CHG}/{item['id']}/children", {"child_id": other["id"]}, CONSOLE),
        (
            "POST",
            f"{CHG}/{item['id']}/freeze-override",
            {"reason": "Too late", "window_ids": [str(uuid.uuid4())]},
            version,
        ),
    ]
    for method, url, body, headers in writes:
        refused = await world.call(method, url, a, a.admin, json=body, headers=headers)
        assert refused.status_code == 409, (method, url, refused.status_code, refused.text)
        assert refused.json().get("code") == "record_closed", (method, url, refused.text)
    schedule = (await world.call("GET", f"{CHG}/{item['id']}/schedule", a, a.admin)).json()
    row = next(r for r in schedule if r["stage"] == "implementation")
    late = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/schedule/implementation",
        a,
        a.admin,
        json={"scheduled_start": "2027-05-01T00:00:00Z", "scheduled_end": "2027-05-01T01:00:00Z"},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert problem(late) == (409, "record_closed"), late.text
