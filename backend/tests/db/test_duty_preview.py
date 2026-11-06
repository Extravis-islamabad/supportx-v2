"""The role editor's duty preview (REQ-REL-024 AC2): open duties a role change would strand.

- Only people who really lose a permission are listed: one still granted by another role, or
  by the same role through a group, is kept.
- A role change, a group no longer carrying the role, and a person's own role removal all count.
- Lookups are asked only about permissions they answer for; whatever they return is filtered to
  what the person really loses.
- The preview changes nothing and needs roles.manage (or users.manage for a person).
"""

import uuid
from collections.abc import Iterator, Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import OpenDuty, register_duties
from app.modules.identity_access.service.duties import unregister_duties
from tests.db.test_access_api import World, world  # noqa: F401 - the fixture, reused

PERMISSION = "audit.view"


class FakeLookup:
    """Every person asked about holds one open duty per permission asked."""

    def __init__(self, permissions: frozenset[str] | None) -> None:
        self.permissions = permissions
        self.asked: list[frozenset[str]] = []

    async def open_duties(
        self,
        session: AsyncSession,  # noqa: ARG002 - the port's signature
        user_ids: Sequence[uuid.UUID],
        permissions: frozenset[str],
        *,
        limit: int,
    ) -> Sequence[OpenDuty]:
        self.asked.append(permissions)
        found = [
            OpenDuty(
                user_id=user,
                permission=permission,
                record_type="release",
                record_id=uuid.UUID(int=n),
                display_id=f"REL-{n}",
                duty="release_role.release_manager",
            )
            for n, (user, permission) in enumerate(
                (u, p) for u in user_ids for p in sorted(permissions)
            )
        ]
        # A careless lookup: also a duty for a permission nobody loses.
        found.append(
            OpenDuty(user_ids[0], "incidents.view", "release", uuid.uuid4(), "REL-99", "x")
        )
        return found[:limit]


@pytest.fixture
def lookup() -> Iterator[FakeLookup]:
    found = FakeLookup(None)
    register_duties(found)
    yield found
    unregister_duties(found)


async def _role(world: World, name: str) -> uuid.UUID:  # noqa: F811 - the fixture's name
    a = world.a
    made = await world.create_role(a, a.admin, name, [{"permission": PERMISSION, "scope": "all"}])
    assert made.status_code == 201, made.text
    return uuid.UUID(made.json()["id"])


async def _preview(world: World, role: uuid.UUID, **body: list[str]) -> dict:  # type: ignore[type-arg]  # noqa: F811 - JSON
    a = world.a
    answer = await world.call("POST", f"/roles/{role}/change-preview", a, a.admin, json=body)
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]  # JSON


async def test_a_lost_permission_lists_the_person_s_open_duties(
    world: World,  # noqa: F811
    lookup: FakeLookup,
) -> None:
    a = world.a
    role = await _role(world, "Release keepers")
    await world.call("PUT", f"/users/{a.tech}/roles/{role}", a, a.admin)
    found = await _preview(world, role, remove_permissions=[PERMISSION])
    assert [p["user_id"] for p in found["affected"]] == [str(a.tech)]
    person = found["affected"][0]
    assert person["name"]
    assert person["lost_permissions"] == [PERMISSION]
    # The careless extra row (a permission not lost) is dropped.
    assert [d["display_id"] for d in person["duties"]] == ["REL-0"]
    assert person["duties"][0]["duty"] == "release_role.release_manager"
    assert found["truncated"] is False
    assert lookup.asked == [frozenset({PERMISSION})]


async def test_a_permission_another_role_grants_is_not_lost(
    world: World,  # noqa: F811
    lookup: FakeLookup,
) -> None:
    a = world.a
    role = await _role(world, "Release keepers")
    auditor = await world.role_id(a, "auditor")  # also grants audit.view
    await world.call("PUT", f"/users/{a.tech}/roles/{role}", a, a.admin)
    await world.call("PUT", f"/users/{a.tech}/roles/{auditor}", a, a.admin)
    found = await _preview(world, role, remove_permissions=[PERMISSION])
    assert found["affected"] == []
    assert lookup.asked == []  # nobody loses anything: no lookup is asked


async def test_a_group_dropping_the_role_counts_unless_the_person_holds_it_directly(
    world: World,  # noqa: F811
    lookup: FakeLookup,
) -> None:
    a = world.a
    role = await _role(world, "Release keepers")
    made = await world.call("POST", "/organization/groups", a, a.admin, json={"name": "Rel"})
    group = made.json()["id"]
    await world.call("PUT", f"/roles/{role}/groups/{group}", a, a.admin)
    await world.call("PUT", f"/organization/groups/{group}/members/{a.tech}", a, a.admin)
    found = await _preview(world, role, remove_groups=[group])
    assert [p["user_id"] for p in found["affected"]] == [str(a.tech)]
    await world.call("PUT", f"/users/{a.tech}/roles/{role}", a, a.admin)
    found = await _preview(world, role, remove_groups=[group])
    assert found["affected"] == []
    assert lookup.asked == [frozenset({PERMISSION})]


async def test_removing_a_person_s_own_role_previews_their_duties(
    world: World,  # noqa: F811
    lookup: FakeLookup,
) -> None:
    a = world.a
    role = await _role(world, "Release keepers")
    await world.call("PUT", f"/users/{a.tech}/roles/{role}", a, a.admin)
    answer = await world.call(
        "POST", f"/users/{a.tech}/role-preview", a, a.admin, json={"remove_roles": [str(role)]}
    )
    assert answer.status_code == 200, answer.text
    person = answer.json()["affected"][0]
    assert person["user_id"] == str(a.tech)
    assert PERMISSION in person["lost_permissions"]
    # The preview changed nothing: the person still holds the role.
    again = await world.call(
        "POST", f"/users/{a.tech}/role-preview", a, a.admin, json={"remove_roles": [str(role)]}
    )
    assert again.json()["affected"] == answer.json()["affected"]
    assert len(lookup.asked) == 2


async def test_a_lookup_is_asked_only_about_its_own_permissions(world: World) -> None:  # noqa: F811
    a = world.a
    elsewhere = FakeLookup(frozenset({"releases.manage"}))
    register_duties(elsewhere)
    try:
        role = await _role(world, "Release keepers")
        await world.call("PUT", f"/users/{a.tech}/roles/{role}", a, a.admin)
        found = await _preview(world, role, remove_permissions=[PERMISSION])
    finally:
        unregister_duties(elsewhere)
    assert elsewhere.asked == []
    assert found["affected"] == []


async def test_the_previews_need_the_admin_permissions(world: World) -> None:  # noqa: F811
    a = world.a
    role = await _role(world, "Release keepers")
    refused = await world.call(
        "POST", f"/roles/{role}/change-preview", a, a.tech, json={"remove_permissions": []}
    )
    assert refused.status_code == 403
    refused = await world.call(
        "POST", f"/users/{a.admin}/role-preview", a, a.tech, json={"remove_roles": [str(role)]}
    )
    assert refused.status_code == 403
    missing = await world.call("POST", f"/roles/{uuid.uuid4()}/change-preview", a, a.admin, json={})
    assert missing.status_code == 404
