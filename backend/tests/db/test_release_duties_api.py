"""Release roles in the role editor's duty preview (REQ-REL-024 AC2, lane B's #223 port).

Real PostgreSQL with RLS, the real policy layer and lane B's preview endpoint:
- removing the permission a release role requires lists the holder's open release, with the
  role as the duty;
- a role accepting A or B: a holder of only A who loses A is listed; one who also holds B is
  not (lane B's review);
- a person the role also accepts by name is not stranded.
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


OTHER = "releases.edit"  # the role's second accepted permission


async def test_a_holder_of_only_the_lost_one_of_two_accepted_permissions_is_listed(
    world: World,
) -> None:
    a = world.a
    ruled = await patch_role_def(
        world, a, "release_manager", eligibility={"permissions": [NEEDED, OTHER]}
    )
    assert ruled.status_code == 200, ruled.text
    keeper = await _keeper(world, a)  # gives NEEDED, never OTHER
    item = await a_release(world, a)
    held = await put_role(world, a, item, "release_manager", users=[a.requester2])
    assert held.status_code == 200, held.text
    affected = await _preview(world, a, keeper)
    assert [p["user_id"] for p in affected] == [str(a.requester2)]
    assert [d["display_id"] for d in affected[0]["duties"]] == [item["display_id"]]


async def test_a_holder_who_keeps_the_other_accepted_permission_is_not_listed(
    world: World,
) -> None:
    a = world.a
    ruled = await patch_role_def(
        world, a, "release_manager", eligibility={"permissions": [NEEDED, OTHER]}
    )
    assert ruled.status_code == 200, ruled.text
    keeper = await _keeper(world, a)
    editor = await role(world, a, "Release editors", [(OTHER, "all")])
    given = await world.call("PUT", f"/users/{a.requester2}/roles/{editor}", a, a.admin)
    assert given.status_code == 204, given.text
    item = await a_release(world, a)
    held = await put_role(world, a, item, "release_manager", users=[a.requester2])
    assert held.status_code == 200, held.text
    assert await _preview(world, a, keeper) == []  # still eligible through OTHER
