"""A release's manager and engineer, kept in two places, stay equal (WP-058b S5a; the
coordinator's condition after F-02 on changes).

Until the two are one (PROGRESS, a later cleanup), each is written with the other in the same
transaction, whichever path writes it:
- the Roles tab (PUT /roles/{code});
- the details panel (PATCH /details), checked as a role (only eligible people);
- bulk assign_role.
Take joins in its own step (the take marker).
"""

from typing import Any

from tests.db.test_incidents_api import CONSOLE, Org, World, world
from tests.db.test_release_bulk_api import _bulk
from tests.db.test_release_guards_api import release_workers
from tests.db.test_release_parts_api import patch_role_def, put_role
from tests.db.test_releases_api import REL, a_release

__all__ = ["world"]  # the fixture, re-used

PEOPLE = {"release_manager": "release_manager_id", "release_engineer": "release_engineer_id"}


async def _both(world: World, org: Org, item: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Per role: (its holders' people, the details field)."""
    roles = (await world.call("GET", f"{REL}/{item['id']}/roles", org, org.admin)).json()
    details = (await world.call("GET", f"{REL}/{item['id']}/details", org, org.admin)).json()
    held = {r["code"]: r["user_ids"] for r in roles["roles"]}
    return {role: (held.get(role, []), details.get(field)) for role, field in PEOPLE.items()}


def _equal(both: dict[str, tuple[Any, Any]]) -> None:
    for role, (holders, field) in both.items():
        assert holders == ([field] if field is not None else []), (role, holders, field)


async def _current(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    return dict((await world.call("GET", f"{REL}/{item['id']}", org, org.admin)).json())


async def test_the_roles_tab_writes_the_details_too(world: World) -> None:
    a = world.a
    await release_workers(world, a)
    item = await a_release(world, a)
    saved = await put_role(world, a, item, "release_manager", users=[a.tech_a])
    assert saved.status_code == 200, saved.text
    both = await _both(world, a, item)
    assert both["release_manager"] == ([str(a.tech_a)], str(a.tech_a))
    _equal(both)
    cleared = await put_role(world, a, await _current(world, a, item), "release_manager", users=[])
    assert cleared.status_code == 200, cleared.text
    _equal(await _both(world, a, item))


async def test_the_details_panel_writes_the_role_too_and_only_for_eligible_people(
    world: World,
) -> None:
    a = world.a
    await release_workers(world, a)
    item = await a_release(world, a)
    saved = await world.call(
        "PATCH",
        f"{REL}/{item['id']}/details",
        a,
        a.admin,
        json={"release_engineer_id": str(a.tech_b)},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert saved.status_code == 200, saved.text
    both = await _both(world, a, item)
    assert both["release_engineer"] == ([str(a.tech_b)], str(a.tech_b))
    _equal(both)
    # Only those who may edit releases may be its engineer: the requester is refused on the
    # field, the role's own rule (REQ-REL-024), and nothing changes.
    ruled = await patch_role_def(
        world, a, "release_engineer", eligibility={"permissions": ["releases.edit"]}
    )
    assert ruled.status_code == 200, ruled.text
    refused = await world.call(
        "PATCH",
        f"{REL}/{item['id']}/details",
        a,
        a.admin,
        json={"release_engineer_id": str(a.requester)},
        headers={"If-Match": f'"{saved.json()["version"]}"', **CONSOLE},
    )
    assert refused.status_code == 422, refused.text
    assert {(e["field"], e["code"]) for e in refused.json()["errors"]} == {
        ("body.release_engineer_id", "not_eligible")
    }
    assert await _both(world, a, item) == both


async def test_bulk_assign_role_writes_the_details_too(world: World) -> None:
    a = world.a
    await release_workers(world, a)
    first, second = await a_release(world, a), await a_release(world, a)
    done = await _bulk(
        world, a, "assign_role", [first, second], role="release_manager", user_ids=[str(a.tech_a)]
    )
    assert done["done_count"] == 2, done["results"]
    for item in (first, second):
        both = await _both(world, a, item)
        assert both["release_manager"] == ([str(a.tech_a)], str(a.tech_a))
        _equal(both)


def test_people_roles_cover_both_fields() -> None:
    from app.modules.work_items.domain.releases import PEOPLE_ROLES  # noqa: PLC0415

    assert PEOPLE_ROLES == PEOPLE


async def _take(world: World, org: Org, item: dict[str, Any], user: Any) -> Any:  # noqa: ANN401
    current = await _current(world, org, item)
    return await world.call(
        "POST",
        f"{REL}/{item['id']}/take",
        org,
        user,
        json={},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )


async def test_req_rel_057_ac2_take_makes_you_the_engineer_or_the_marked_role(
    world: World,
) -> None:
    a = world.a
    await release_workers(world, a)
    item = await a_release(world, a)
    taken = await _take(world, a, item, a.admin)
    assert taken.status_code == 200, taken.text
    both = await _both(world, a, item)
    assert both["release_engineer"] == ([str(a.admin)], str(a.admin))  # the default role
    _equal(both)
    again = await _take(world, a, item, a.admin)
    assert (again.status_code, again.json()["code"]) == (409, "already_yours")
    # The tenant says Take makes you the manager (Appendix A): the marker moves there.
    settings = (await world.call("GET", f"{REL}/settings", a, a.admin)).json()
    marked = await world.call(
        "PATCH",
        f"{REL}/settings/roles/release_manager",
        a,
        a.admin,
        json={"take": True},
        headers={"If-Match": f'"{settings["version"]}"', **CONSOLE},
    )
    assert marked.status_code == 200, marked.text
    roles = (await world.call("GET", f"{REL}/settings/roles", a, a.admin)).json()
    assert [r["code"] for r in roles if r["take"]] == ["release_manager"]
    other = await a_release(world, a)
    assert (await _take(world, a, other, a.admin)).status_code == 200
    both = await _both(world, a, other)
    assert both["release_manager"] == ([str(a.admin)], str(a.admin))
    assert both["release_engineer"] == ([], None)
    _equal(both)


async def test_only_a_release_role_can_be_take_s_role(world: World) -> None:
    a = world.a
    release_settings = (await world.call("GET", f"{REL}/settings", a, a.admin)).json()
    requester = await world.call(
        "PATCH",
        f"{REL}/settings/roles/requester",
        a,
        a.admin,
        json={"take": True},
        headers={"If-Match": f'"{release_settings["version"]}"', **CONSOLE},
    )
    assert requester.status_code == 422, requester.text  # who asked never takes it
    settings = (await world.call("GET", "/changes/settings", a, a.admin)).json()
    roles = (await world.call("GET", "/changes/settings/roles", a, a.admin)).json()
    refused = await world.call(
        "PATCH",
        f"/changes/settings/roles/{roles[0]['code']}",
        a,
        a.admin,
        json={"take": True},
        headers={"If-Match": f'"{settings["version"]}"', **CONSOLE},
    )
    assert refused.status_code == 422, refused.text
