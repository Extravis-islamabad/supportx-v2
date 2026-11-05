"""Release roles in the role editor's duty preview (REQ-REL-024 AC2, lane B's #223 port).

Real PostgreSQL with RLS, the real policy layer and lane B's preview endpoint:
- removing the permission a release role requires lists the holder's open release, with the
  role as the duty;
- a person the role also accepts by name is not stranded;
- closed releases and roles the change cannot strand are not listed.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import Org, World, role, world
from tests.db.test_release_parts_api import patch_role_def, put_role
from tests.db.test_releases_api import a_release

__all__ = ["world"]  # the fixture, re-used

NEEDED = "releases.delete"  # a permission the release manager role is set to require


async def _keeper(world: World, org: Org) -> uuid.UUID:
    """A role giving the release's view and the permission the manager role requires."""
    made = await role(world, org, "Release keepers", [("releases.view", "own"), (NEEDED, "all")])
    assigned = await world.call("PUT", f"/users/{org.requester2}/roles/{made}", org, org.admin)
    assert assigned.status_code == 204, assigned.text
    return made


async def _preview(world: World, org: Org, keeper: uuid.UUID) -> list[dict[str, Any]]:
    answer = await world.call(
        "POST",
        f"/roles/{keeper}/change-preview",
        org,
        org.admin,
        json={"remove_permissions": [NEEDED]},
    )
    assert answer.status_code == 200, answer.text
    return list(answer.json()["affected"])


async def test_req_rel_024_ac2_removing_the_role_s_permission_lists_the_open_release(
    world: World,
) -> None:
    a = world.a
    ruled = await patch_role_def(world, a, "release_manager", eligibility={"permissions": [NEEDED]})
    assert ruled.status_code == 200, ruled.text
    keeper = await _keeper(world, a)
    item = await a_release(world, a)
    held = await put_role(world, a, item, "release_manager", users=[a.requester2])
    assert held.status_code == 200, held.text

    affected = await _preview(world, a, keeper)
    assert [p["user_id"] for p in affected] == [str(a.requester2)]
    duties = affected[0]["duties"]
    assert [(d["display_id"], d["duty"], d["record_type"]) for d in duties] == [
        (item["display_id"], "release_role.release_manager", "release")
    ]


async def test_a_person_the_role_names_is_not_stranded(world: World) -> None:
    a = world.a
    ruled = await patch_role_def(
        world,
        a,
        "release_manager",
        eligibility={"permissions": [NEEDED], "user_ids": [str(a.requester2)]},
    )
    assert ruled.status_code == 200, ruled.text
    keeper = await _keeper(world, a)
    item = await a_release(world, a)
    held = await put_role(world, a, item, "release_manager", users=[a.requester2])
    assert held.status_code == 200, held.text
    assert await _preview(world, a, keeper) == []  # still eligible by name


async def test_a_role_the_change_cannot_strand_is_not_listed(world: World) -> None:
    a = world.a
    # The role accepts two permissions; removing one of them leaves the other.
    ruled = await patch_role_def(
        world, a, "release_manager", eligibility={"permissions": [NEEDED, "releases.edit"]}
    )
    assert ruled.status_code == 200, ruled.text
    keeper = await _keeper(world, a)
    item = await a_release(world, a)
    held = await put_role(world, a, item, "release_manager", users=[a.requester2])
    assert held.status_code == 200, held.text
    assert await _preview(world, a, keeper) == []
