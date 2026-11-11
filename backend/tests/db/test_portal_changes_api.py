"""Requesters' changes in the portal (WP-045d S4a; REQ-CHG-109).

A requester raises a change from a form offered to requesters and follows its stage, status,
planned window and public notes; plans, risk and private notes never reach the portal API
(AC2). A requester who is an approver decides through the change's own approval route (AC3).
"""

import json
import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_changes_api import CHG, move
from tests.db.test_incidents_api import CONSOLE, Org, World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

PORTAL = "/portal/changes"
SECRET_PLAN = "Pull the core switch and restore from the 02:00 image"
PRIVATE_NOTE = "Vendor contract number 4471, do not share"


async def _raise(world: World, org: Org, user: uuid.UUID) -> dict[str, Any]:
    made = await world.call(
        "POST",
        PORTAL,
        org,
        user,
        json={"subject": "Move my team's printer", "description": "<p>To floor 3.</p>"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_req_chg_109_a_requester_raises_and_follows_a_change_without_its_internals(
    world: World,
) -> None:
    a = world.a
    offered = await world.call("GET", f"{PORTAL}/templates", a, a.requester)
    assert offered.status_code == 200, offered.text
    assert offered.json(), "a new tenant offers at least the default change form"
    raised = await _raise(world, a, a.requester)
    assert (raised["stage"], raised["requester_id"]) == ("submission", str(a.requester))
    # Staff write a plan, a private note and a public reply.
    wrote = await world.call(
        "PUT",
        f"{CHG}/{raised['id']}/plan/backout",
        a,
        a.admin,
        json={"content": f"<p>{SECRET_PLAN}</p>"},
        headers={"If-Match": '"0"', **CONSOLE},
    )
    assert wrote.status_code == 200, wrote.text
    for kind, body in (("note", PRIVATE_NOTE), ("reply", "Scheduled for Saturday night.")):
        entry = await world.call(
            "POST",
            f"{CHG}/{raised['id']}/conversation",
            a,
            a.admin,
            json={"kind": kind, "body": f"<p>{body}</p>"},
            headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
        )
        assert entry.status_code == 201, entry.text
    # The requester's view: where it is and the public conversation, nothing else (AC2).
    seen = await world.call("GET", f"{PORTAL}/{raised['id']}", a, a.requester)
    assert seen.status_code == 200, seen.text
    keys = set(seen.json())
    assert {"stage", "status", "planned_start", "planned_end"} <= keys
    assert not keys & {"risk", "plan", "plans", "outcome", "approvals", "technician_id"}
    talk = await world.call("GET", f"{PORTAL}/{raised['id']}/conversation", a, a.requester)
    assert talk.status_code == 200, talk.text
    everything = json.dumps([seen.json(), talk.json()])
    assert "Scheduled for Saturday night." in everything
    assert PRIVATE_NOTE not in everything
    assert SECRET_PLAN not in everything
    listed = await world.call("GET", PORTAL, a, a.requester)
    assert raised["id"] in {c["id"] for c in listed.json()["items"]}
    # Someone else's change is not there for another requester (404, never 403).
    other = await world.call("GET", f"{PORTAL}/{raised['id']}", a, a.requester2)
    assert other.status_code == 404, other.text


async def test_req_chg_109_ac3_a_requester_approver_decides_from_the_portal(world: World) -> None:
    from tests.db.test_approvals_api import manager_of  # noqa: PLC0415 - shared helper

    a = world.a
    await manager_of(world, a.requester, a.requester2)  # the line manager: a requester only
    raised = await _raise(world, a, a.requester)
    fresh = (await world.call("GET", f"{CHG}/{raised['id']}", a, a.admin)).json()
    asked = await move(world, a, fresh, "submission_awaiting_acceptance")
    assert asked.status_code == 200, asked.text
    mine = await world.call("GET", f"{CHG}/my-approvals", a, a.requester2)
    assert mine.status_code == 200, mine.text
    [entry] = [i for i in mine.json()["items"] if i["record_id"] == raised["id"]]
    decided = await world.call(
        "POST",
        f"{CHG}/{raised['id']}/approvals/{entry['approval_id']}/decision",
        a,
        a.requester2,
        json={"decision": "approve"},
        headers={"If-Match": f'"{entry["approval_version"]}"'},
    )
    assert decided.status_code == 200, decided.text
    after = (await world.call("GET", f"{PORTAL}/{raised['id']}", a, a.requester)).json()
    assert after["stage"] != "submission" or after["status"] != "submission_awaiting_acceptance"


async def test_req_chg_117_waiting_for_my_approval_counts_and_falls_when_decided(
    world: World,
) -> None:
    """AC1: deciding an approval lowers the approver's "waiting for my approval" counter."""
    from tests.db.test_approvals_api import manager_of  # noqa: PLC0415 - shared helper

    a = world.a
    await manager_of(world, a.requester, a.tech_a)  # tech_a approves, and sees changes

    async def waiting() -> int:
        found = await world.call("GET", f"{CHG}/counters", a, a.tech_a)
        assert found.status_code == 200, found.text
        return int(next(c["count"] for c in found.json() if c["counter"] == "pending_my_approval"))

    before = await waiting()
    raised = await _raise(world, a, a.requester)
    fresh = (await world.call("GET", f"{CHG}/{raised['id']}", a, a.admin)).json()
    assert (await move(world, a, fresh, "submission_awaiting_acceptance")).status_code == 200
    assert await waiting() == before + 1
    mine = (await world.call("GET", f"{CHG}/my-approvals", a, a.tech_a)).json()["items"]
    [entry] = [i for i in mine if i["record_id"] == raised["id"]]
    decided = await world.call(
        "POST",
        f"{CHG}/{raised['id']}/approvals/{entry['approval_id']}/decision",
        a,
        a.tech_a,
        json={"decision": "approve"},
        headers={"If-Match": f'"{entry["approval_version"]}"'},
    )
    assert decided.status_code == 200, decided.text
    assert await waiting() == before
    # Only changes have the change counters.
    incident = (await world.call("GET", "/incidents/counters", a, a.tech_a)).json()
    assert "pending_my_approval" not in {c["counter"] for c in incident}
