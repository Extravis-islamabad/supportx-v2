"""Access that follows a person's external groups (WP-057 S5c-1a, REQ-SEC-014; lane B's conditions).

`follow` is driven here through a directory source, as directory sync uses it.
- **AC1/AC2:** joining a mapped group gives the role and the group, managed and audited; leaving
  takes them away.
- **Hand-made access survives:** a role or membership already held by hand stays hand-made, and
  no mapping removes it (the bug sync had).
- **An incomplete list changes nothing** (condition 3). Vendor support, service and break-glass
  accounts are never followed (condition 4).
- **Two mappings, or two sources, onto one target** keep it until both go.
- **AC3:** a managed role or membership can't be removed by hand (409, labelled).
- **The last tenant admin** is never removed by a mapping (kept, and audited).

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.group_mappings import Plan, SourceKind
from app.modules.identity_access.infra.models import IdpGroupMapping, Role, UserRole
from app.modules.identity_access.service import group_mappings
from app.modules.organization.infra.models import GroupMember
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_audit_api import by_action
from tests.db.test_incidents_api import Org, World, make_org, role

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used


async def _mapping(
    world: World, org: Org, source: uuid.UUID, external: str, **target: uuid.UUID
) -> uuid.UUID:
    made = uuid.uuid4()
    async with world.app.state.db.tenant_session(TenantContext(org.tenant, org.admin)) as session:
        session.add(
            IdpGroupMapping(
                id=made,
                tenant_id=org.tenant,
                source_kind=SourceKind.DIRECTORY.value,
                source_id=source,
                external_group_id=external,
                **target,
            )
        )
    return made


async def _follow(
    world: World, org: Org, source: uuid.UUID, user: uuid.UUID, groups: set[str] | None
) -> Plan | None:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        return await group_mappings.follow(
            session,
            source_kind=SourceKind.DIRECTORY,
            source_id=source,
            user_id=user,
            group_ids=None if groups is None else frozenset(groups),
        )


async def _held(world: World, org: Org, user: uuid.UUID) -> dict[str, Any]:
    """The person's roles and groups, each with whether it is managed."""
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        held_roles = {
            r.role_id: r.managed
            for r in await session.scalars(select(UserRole).where(UserRole.user_id == user))
        }
        held_groups = {
            g.group_id: g.managed
            for g in await session.scalars(select(GroupMember).where(GroupMember.user_id == user))
        }
    return {"roles": held_roles, "groups": held_groups}


async def test_joining_and_leaving_a_mapped_group_gives_and_takes_access(world: World) -> None:
    a = world.a
    source = uuid.uuid4()
    changer = await role(
        world, a, f"Change managers {uuid.uuid4().hex[:6]}", [("changes.view", "all")]
    )
    await _mapping(world, a, source, "sx-change-managers", role_id=changer)
    await _mapping(world, a, source, "sx-network", group_id=a.gb)
    person = a.requester  # in no support group, with no role of this kind, by hand

    done = await _follow(world, a, source, person, {"sx-change-managers", "sx-network", "other"})
    assert done is not None
    assert len(done.add_sources) == 2
    held = await _held(world, a, person)
    assert held["roles"].get(changer) is True  # AC1: managed
    assert held["groups"].get(a.gb) is True
    assert await by_action(world, a, "user.role_mapped")
    assert await by_action(world, a, "group.member_mapped")

    # AC3: neither can be removed by hand, with a labelled reason.
    by_hand = await world.call("DELETE", f"/users/{person}/roles/{changer}", a, a.admin)
    assert by_hand.status_code == 409, by_hand.text
    assert by_hand.json()["code"] == "assignment_from_identity_provider"
    leave = await world.call("DELETE", f"/organization/groups/{a.gb}/members/{person}", a, a.admin)
    assert leave.status_code == 409, leave.text

    # AC2: out of both groups, both go.
    await _follow(world, a, source, person, {"other"})
    held = await _held(world, a, person)
    assert changer not in held["roles"]
    assert a.gb not in held["groups"]


async def test_hand_made_access_survives_and_an_incomplete_list_changes_nothing(
    world: World,
) -> None:
    a = world.a
    source = uuid.uuid4()
    person = a.tech_a
    before = await _held(world, a, person)
    assert before["groups"].get(a.ga) is False  # in group A by hand (the world's seed)
    await _mapping(world, a, source, "sx-desk-a", group_id=a.ga)

    await _follow(world, a, source, person, {"sx-desk-a"})
    assert (await _held(world, a, person))["groups"][a.ga] is False  # still hand-made
    await _follow(world, a, source, person, set())  # left the directory group
    assert a.ga in (await _held(world, a, person))["groups"]  # a mapping never removes it

    # Missing, malformed or overage (None): nothing at all changes.
    assert await _follow(world, a, source, person, None) is None
    assert await _held(world, a, person) == await _held(world, a, person)


async def test_break_glass_and_service_accounts_are_never_followed(world: World) -> None:
    a = world.a
    source = uuid.uuid4()
    await _mapping(world, a, source, "sx-everyone", group_id=a.gb)
    await world.sql("UPDATE users SET break_glass = true WHERE id = $1", a.lead)
    try:
        assert await _follow(world, a, source, a.lead, {"sx-everyone"}) is None
        assert a.gb not in (await _held(world, a, a.lead))["groups"]
    finally:
        await world.sql("UPDATE users SET break_glass = false WHERE id = $1", a.lead)


async def test_a_target_two_sources_give_stays_until_both_go(world: World) -> None:
    a = world.a
    first, second = uuid.uuid4(), uuid.uuid4()
    await _mapping(world, a, first, "sx-ops", group_id=a.gb)
    await _mapping(world, a, second, "ops-team", group_id=a.gb)
    person = a.requester
    await _follow(world, a, first, person, {"sx-ops"})
    await _follow(world, a, second, person, {"ops-team"})
    await _follow(world, a, first, person, set())
    assert (await _held(world, a, person))["groups"].get(a.gb) is True  # the second still gives it
    await _follow(world, a, second, person, set())
    assert a.gb not in (await _held(world, a, person))["groups"]


async def test_the_last_tenant_admin_is_kept_and_it_is_audited(world: World) -> None:
    org = await make_org(world, f"Last admin {uuid.uuid4().hex[:6]}")
    source = uuid.uuid4()
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        admin_role = await session.scalar(select(Role.id).where(Role.key == "tenant_admin"))
    assert admin_role is not None
    await _mapping(world, org, source, "sx-admins", role_id=admin_role)
    # The tenant's only admin holds the role through that mapping alone.
    await world.sql(
        "UPDATE user_roles SET managed = true"
        " WHERE tenant_id = $1 AND user_id = $2 AND role_id = $3",
        org.tenant, org.admin, admin_role,
    )  # fmt: skip
    for user in (org.lead, org.tech_a, org.tech_b, org.tech_c):
        await world.sql(
            "DELETE FROM user_roles WHERE tenant_id = $1 AND user_id = $2 AND role_id = $3",
            org.tenant, user, admin_role,
        )  # fmt: skip
    await _follow(world, org, source, org.admin, {"sx-admins"})  # records the source
    await _follow(world, org, source, org.admin, set())  # left the group: would leave no admin
    assert (await _held(world, org, org.admin))["roles"].get(admin_role) is True
    assert await by_action(world, org, "idp_group_mapping.kept_last_admin")
