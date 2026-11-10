"""Approvals at each stage of a release (WP-058a s5; REQ-REL-031) over HTTP.

Real PostgreSQL with RLS, on the work-item approval engine (WP-030):
- planning is approved in the app with no mail, and the release moves on to build (AC1);
- a second level opens only after the first is approved (AC3);
- majority rejects on an exact split (the tie case);
- the requester may not approve their own release (AC4);
- a named approver decides by being named, with no releases.approve, and only their own row;
- a role nobody holds goes to the approval administrators with the reason shown;
- canceling the release closes its open approvals.
"""

import uuid
from typing import Any

import httpx

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World, role
from tests.db.test_release_parts_api import put_role, settings_version
from tests.db.test_releases_api import REL, a_release, moved, new_release

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

APPROVER = [("releases.view", "all"), ("releases.approve", "all")]


async def approvers(world: World, org: Org, *people: uuid.UUID) -> None:
    """People who may approve releases."""
    granted = await role(world, org, f"Release approvers {uuid.uuid4().hex[:6]}", APPROVER)
    for person in people:
        assigned = await world.call("PUT", f"/users/{person}/roles/{granted}", org, org.admin)
        assert assigned.status_code == 204, assigned.text


async def planning_levels(world: World, org: Org, levels: list[dict[str, Any]]) -> None:
    response = await world.call(
        "PUT",
        f"{REL}/settings/stages/planning/approvals",
        org,
        org.admin,
        json={
            "approvals": {
                "raised_by": "planning_waiting_approval",
                "approved": "planning_plan_approved",
                "rejected": "planning_plan_rejected",
                "levels": levels,
            }
        },
        headers={"If-Match": f'"{await settings_version(world, org)}"', **CONSOLE},
    )
    assert response.status_code == 200, response.text


async def to_waiting(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    """Accepted, then sent for approval: the planning approvals open."""
    planning = await moved(world, org, item, "submission_accepted")
    return await moved(world, org, planning, "planning_waiting_approval")


async def approvals(world: World, org: Org, item: dict[str, Any]) -> list[dict[str, Any]]:
    response = await world.call("GET", f"{REL}/{item['id']}/approvals", org, org.admin)
    assert response.status_code == 200, response.text
    body = response.json()
    return list(body["items"] if isinstance(body, dict) else body)


async def decide(
    world: World,
    org: Org,
    item: dict[str, Any],
    row: dict[str, Any],
    user: uuid.UUID,
    decision: str = "approve",
) -> httpx.Response:
    body: dict[str, Any] = {"decision": decision}
    if decision == "reject":
        body["comment"] = "Not ready"
    return await world.call(
        "POST",
        f"{REL}/{item['id']}/approvals/{row['id']}/decision",
        org,
        user,
        json=body,
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )


async def current(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    return dict((await world.call("GET", f"{REL}/{item['id']}", org, org.admin)).json())


async def test_ac1_planning_approved_in_the_app_moves_the_release_on(world: World) -> None:
    a = world.a
    await approvers(world, a, a.tech_a)
    item = await a_release(world, a)
    held = await put_role(world, a, item, "release_manager", users=[a.tech_a])
    waiting = await to_waiting(world, a, {**item, "version": held.json()["version"]})
    assert waiting["status"] == "planning_waiting_approval"
    rows = await approvals(world, a, waiting)
    assert [(r["record_stage"], r["stage"], r["approver_id"]) for r in rows] == [
        ("planning", 1, str(a.tech_a))
    ]
    done = await decide(world, a, waiting, rows[0], a.tech_a)
    assert done.status_code == 200, done.text
    assert (await current(world, a, item))["status"] == "build_in_progress"  # no mail needed


async def test_ac3_level_two_opens_only_after_level_one(world: World) -> None:
    a = world.a
    await approvers(world, a, a.tech_a, a.tech_b)
    await planning_levels(
        world,
        a,
        [
            {"rule": "any", "approvers": [{"user_id": str(a.tech_a)}]},
            {"rule": "any", "approvers": [{"user_id": str(a.tech_b)}]},
        ],
    )
    waiting = await to_waiting(world, a, await a_release(world, a))
    first = await approvals(world, a, waiting)
    assert [r["stage"] for r in first] == [1]  # level 2 not yet
    assert (await decide(world, a, waiting, first[0], a.tech_a)).status_code == 200
    rows = await approvals(world, a, waiting)
    second = [r for r in rows if r["stage"] == 2]
    assert [r["approver_id"] for r in second] == [str(a.tech_b)]
    assert (await current(world, a, waiting))["status"] == "planning_waiting_approval"
    assert (await decide(world, a, waiting, second[0], a.tech_b)).status_code == 200
    assert (await current(world, a, waiting))["status"] == "build_in_progress"


async def test_majority_rejects_on_an_exact_split(world: World) -> None:
    a = world.a
    four = [a.tech_a, a.tech_b, a.tech_c, a.lead]
    await approvers(world, a, *four)
    await planning_levels(
        world, a, [{"rule": "majority", "approvers": [{"user_id": str(p)} for p in four]}]
    )
    waiting = await to_waiting(world, a, await a_release(world, a))
    rows = {r["approver_id"]: r for r in await approvals(world, a, waiting)}
    for person, decision in zip(four, ["approve", "approve", "reject", "reject"], strict=True):
        response = await decide(world, a, waiting, rows[str(person)], person, decision)
        assert response.status_code == 200, response.text
        if person == a.tech_c:  # 2 approve, 1 rejects: a majority (3 of 4) is still possible
            assert (await current(world, a, waiting))["status"] == "planning_waiting_approval"
    assert (await current(world, a, waiting))["status"] == "planning_plan_rejected"


async def test_ac4_the_requester_may_not_approve_their_own_release(world: World) -> None:
    a = world.a
    await approvers(world, a, a.tech_a)
    await planning_levels(world, a, [{"rule": "any", "approvers": [{"user_id": str(a.tech_a)}]}])
    made = await new_release(world, a, a.admin, requester_id=str(a.tech_a))
    assert made.status_code == 201, made.text
    waiting = await to_waiting(world, a, made.json())
    rows = await approvals(world, a, waiting)
    # The requester is the only approver: the administrators get it, and the reason is shown.
    assert [(r["approver_id"], r["route_reason"]) for r in rows] == [
        (None, "self_approval_blocked")
    ]


async def test_a_named_approver_decides_by_being_named_and_only_their_own(world: World) -> None:
    """Named approvers need no releases.approve (as WP-030); it is for approvals one is not
    named on (the coordinator's and lane B's rule)."""
    a = world.a
    viewer = await role(world, a, "Release viewer", [("releases.view", "all")])
    for person in (a.tech_a, a.tech_b):
        await world.call("PUT", f"/users/{person}/roles/{viewer}", a, a.admin)
    await planning_levels(
        world,
        a,
        [
            {
                "rule": "all",
                "approvers": [{"user_id": str(a.tech_a)}, {"user_id": str(a.tech_b)}],
            }
        ],
    )
    waiting = await to_waiting(world, a, await a_release(world, a))
    rows = {r["approver_id"]: r for r in await approvals(world, a, waiting)}
    assert set(rows) == {str(a.tech_a), str(a.tech_b)}  # named, not routed away
    someone_elses = await decide(world, a, waiting, rows[str(a.tech_b)], a.tech_a)
    assert someone_elses.status_code == 403, someone_elses.text  # not named on it
    assert (await decide(world, a, waiting, rows[str(a.tech_a)], a.tech_a)).status_code == 200
    assert (await decide(world, a, waiting, rows[str(a.tech_b)], a.tech_b)).status_code == 200
    assert (await current(world, a, waiting))["status"] == "build_in_progress"


async def test_a_role_nobody_holds_goes_to_the_administrators(world: World) -> None:
    a = world.a
    waiting = await to_waiting(world, a, await a_release(world, a))  # no release manager set
    rows = await approvals(world, a, waiting)
    assert [(r["approver_id"], r["route_reason"]) for r in rows] == [(None, "no_holder")]
    assert (await decide(world, a, waiting, rows[0], a.tech_a)).status_code == 403
    assert (await decide(world, a, waiting, rows[0], a.admin)).status_code == 200  # approve_any
    assert (await current(world, a, waiting))["status"] == "build_in_progress"


async def test_canceling_closes_the_open_approvals(world: World) -> None:
    a = world.a
    waiting = await to_waiting(world, a, await a_release(world, a))
    assert [r["state"] for r in await approvals(world, a, waiting)] == ["pending"]
    canceled = await moved(world, a, waiting, "closure_canceled", reason_text="Not needed")
    assert canceled["status_category"] == "canceled"
    assert [r["state"] for r in await approvals(world, a, waiting)] == ["not_needed"]
