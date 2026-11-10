"""The team lead and changes (D-153, Haider 2026-11-10, option a).

A team lead works its own groups' changes like a technician (edit, assign, close within its
groups) and only reads the others. It runs no change advisory board, makes no emergency
override and changes nothing tenant-wide. Separation of duties still holds for it: it never
approves a change it implements or owns, nor, under the strict tenant setting, one its own
group implements (REQ-CHG-039).
"""

import uuid
from typing import Any

from tests.db.test_approvals_api import manager_of
from tests.db.test_change_approval_settings import group_implements, settings
from tests.db.test_changes_api import CHG, a_change, move
from tests.db.test_incidents_api import CONSOLE, Org, World, world

__all__ = ["world"]  # the fixture, re-used


async def _only_team_lead(world: World, org: Org, user: uuid.UUID) -> None:
    """`user` holds the built-in team lead role and nothing else."""
    roles = {r["key"]: r["id"] for r in (await world.call("GET", "/roles", org, org.admin)).json()}
    given = await world.call("PUT", f"/users/{user}/roles/{roles['team_lead']}", org, org.admin)
    assert given.status_code in {200, 204}, given.text
    taken = await world.call("DELETE", f"/users/{user}/roles/{roles['technician']}", org, org.admin)
    assert taken.status_code in {200, 204}, taken.text
    held = await world.sql(
        "SELECT r.key FROM user_roles u JOIN roles r ON r.id = u.role_id"
        " WHERE u.tenant_id = $1 AND u.user_id = $2",
        org.tenant,
        user,
    )
    assert [r["key"] for r in held] == ["team_lead"]  # the lead's rights alone, nothing inherited


async def _change_in(world: World, org: Org, group: uuid.UUID) -> dict[str, Any]:
    item = await a_change(world, org)
    moved = await world.call(
        "POST",
        f"{CHG}/{item['id']}/assign",
        org,
        org.admin,
        json={"group_id": str(group), "technician_id": None},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert moved.status_code == 200, moved.text
    return dict(moved.json())


async def _edit(world: World, org: Org, user: uuid.UUID, item: dict[str, Any]) -> int:
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", org, org.admin)).json()
    changed = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}",
        org,
        user,
        json={"subject": "Core switch firmware 9.4"},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    return changed.status_code


async def test_a_team_lead_works_its_groups_changes_and_reads_the_others(world: World) -> None:
    a = world.a
    await _only_team_lead(world, a, a.tech_a)  # tech_a is in GA, not in GB
    own = await _change_in(world, a, a.ga)
    other = await _change_in(world, a, a.gb)
    assert await _edit(world, a, a.tech_a, own) == 200
    assert (await world.call("GET", f"{CHG}/{other['id']}", a, a.tech_a)).status_code == 200
    assert await _edit(world, a, a.tech_a, other) in {403, 404}
    unchanged = (await world.call("GET", f"{CHG}/{other['id']}", a, a.admin)).json()
    assert unchanged["subject"] == other["subject"]
    # No change advisory board and no emergency override: the change manager's and admins' only.
    board = await world.call(
        "POST",
        "/change-boards",
        a,
        a.tech_a,
        json={"name": "Lead's board", "members": [{"user_id": str(a.tech_a)}]},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert board.status_code == 403, board.text
    fresh = (await world.call("GET", f"{CHG}/{own['id']}", a, a.admin)).json()
    override = await world.call(
        "POST",
        f"{CHG}/{own['id']}/emergency-override",
        a,
        a.tech_a,
        json={"reason": "Outage"},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert override.status_code == 403, override.text


async def test_a_team_lead_never_approves_a_change_it_implements(world: World) -> None:
    """REQ-CHG-039 for a lead: named the implementer after the approval opened, it is refused."""
    a = world.a
    await _only_team_lead(world, a, a.tech_a)
    await manager_of(world, a.requester, a.tech_a)  # the lead approves as the line manager
    item = await a_change(world, a)
    assert (await move(world, a, item, "submission_awaiting_acceptance")).status_code == 200
    (approval,) = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()[
        "items"
    ]
    assert approval["approver_id"] == str(a.tech_a)
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    named = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/roles/implementer",
        a,
        a.admin,
        json={"user_ids": [str(a.tech_a)]},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert named.status_code == 200, named.text
    decided = await world.call(
        "POST",
        f"{CHG}/{item['id']}/approvals/{approval['id']}/decision",
        a,
        a.tech_a,
        json={"decision": "approve", "comment": "Looks fine"},
        headers={"If-Match": f'"{approval["version"]}"', **CONSOLE},
    )
    assert decided.status_code == 403, decided.text
    assert decided.json()["code"] == "approval_segregation"
    still = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    assert [r["state"] for r in still] == ["pending"]


async def test_under_strict_a_team_lead_is_barred_when_its_group_implements(world: World) -> None:
    """Strict segregation: a lead in the implementing group is left out; the admins decide."""
    a = world.a
    await _only_team_lead(world, a, a.tech_a)  # in GA
    await manager_of(world, a.requester, a.tech_a)
    assert (await settings(world, a, segregation_strict=True))["status"] == 200
    item = await group_implements(world, a, await a_change(world, a))  # GA implements
    preview = await world.call(
        "GET", f"{CHG}/{item['id']}/approvals/preview", a, a.admin, params={"stage": "submission"}
    )
    assert preview.json()["barred"] == [
        {"user_id": str(a.tech_a), "reason": "segregation_of_duties"}
    ]
    assert (await move(world, a, item, "submission_awaiting_acceptance")).status_code == 200
    rows = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    assert [(r["approver_id"], r["route_reason"]) for r in rows] == [
        (None, "segregation_of_duties")
    ]
