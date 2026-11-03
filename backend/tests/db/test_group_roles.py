"""Roles carried by support groups (WP-042, REQ-ADM-015 AC2) and lane B's conditions.

- A member of a group holds its roles; leaving the group, or the group being disabled, ends that.
- Giving a group a role, or adding someone to a group that carries roles, needs the same rights
  as assigning the role directly: a group head cannot make themselves an admin.
- The tenant never loses its last admin through a group.
- The table is isolated per tenant (RLS).
"""

import uuid

import asyncpg

from app.core.tenancy import TenantContext
from app.modules.organization import add_member
from tests.db.test_access_api import World, problem, world  # noqa: F401 - the fixture, reused


async def _group(world: World, name: str) -> uuid.UUID:  # noqa: F811 - the fixture's name
    a = world.a
    made = await world.call("POST", "/organization/groups", a, a.admin, json={"name": name})
    assert made.status_code == 201, made.text
    return uuid.UUID(made.json()["id"])


async def _holds(world: World, user: uuid.UUID, permission: str) -> bool:  # noqa: F811
    """Whether the person may read the audit log (the auditor role's audit.view)."""
    assert permission == "audit.view"
    a = world.a
    status = (await world.call("GET", "/audit/status", a, user)).status_code
    assert status in {200, 403, 404}, status  # no access: refused, or hidden as not found
    return status == 200


async def test_a_member_holds_the_group_s_role_and_loses_it_on_leaving(world: World) -> None:  # noqa: F811
    a = world.a
    group = await _group(world, "Auditors")
    auditor = await world.role_id(a, "auditor")
    given = await world.call("PUT", f"/roles/{auditor}/groups/{group}", a, a.admin)
    assert given.status_code == 204, given.text
    assert not await _holds(world, a.tech, "audit.view")
    added = await world.call("PUT", f"/organization/groups/{group}/members/{a.tech}", a, a.admin)
    assert added.status_code == 204, added.text
    assert await _holds(world, a.tech, "audit.view")
    left = await world.call("DELETE", f"/organization/groups/{group}/members/{a.tech}", a, a.admin)
    assert left.status_code == 204
    assert not await _holds(world, a.tech, "audit.view")


async def test_a_disabled_group_grants_nothing(world: World) -> None:  # noqa: F811
    a = world.a
    group = await _group(world, "Night shift")
    auditor = await world.role_id(a, "auditor")
    await world.call("PUT", f"/roles/{auditor}/groups/{group}", a, a.admin)
    await world.call("PUT", f"/organization/groups/{group}/members/{a.tech}", a, a.admin)
    assert await _holds(world, a.tech, "audit.view")
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute("UPDATE support_groups SET disabled_at = now() WHERE id = $1", group)
    finally:
        await conn.close()
    await world.app.state.policy.invalidate(a.tenant)
    assert not await _holds(world, a.tech, "audit.view")


async def test_a_group_head_cannot_hand_themselves_admin_through_a_group(world: World) -> None:  # noqa: F811
    a = world.a
    group = await _group(world, "Admins")
    admin_role = await world.role_id(a, "tenant_admin")
    given = await world.call("PUT", f"/roles/{admin_role}/groups/{group}", a, a.admin)
    assert given.status_code == 204, given.text
    # The manager may manage roles and people, but is no tenant admin.
    grants = await world.create_role(
        a, a.admin, "Group keeper", [{"permission": "groups.manage", "scope": "all"}]
    )
    await world.call("PUT", f"/users/{a.manager}/roles/{grants.json()['id']}", a, a.admin)
    refused = await world.call(
        "PUT", f"/organization/groups/{group}/members/{a.manager}", a, a.manager
    )
    assert problem(refused) == (403, "privilege_escalation")
    # Nor may they give a group a role beyond their own rights.
    other = await _group(world, "Sneaky")
    assert problem(
        await world.call("PUT", f"/roles/{admin_role}/groups/{other}", a, a.manager)
    ) == (403, "privilege_escalation")
    # An admin may.
    allowed = await world.call("PUT", f"/organization/groups/{group}/members/{a.tech}", a, a.admin)
    assert allowed.status_code == 204, allowed.text


async def test_the_last_admin_is_never_lost_through_a_group(world: World) -> None:  # noqa: F811
    a = world.a
    group = await _group(world, "Owners")
    admin_role = await world.role_id(a, "tenant_admin")
    await world.call("PUT", f"/roles/{admin_role}/groups/{group}", a, a.admin)
    await world.call("PUT", f"/organization/groups/{group}/members/{a.tech}", a, a.admin)
    # The admin may now give up their own role: the technician is admin through the group.
    dropped = await world.call("DELETE", f"/users/{a.admin}/roles/{admin_role}", a, a.admin)
    assert dropped.status_code == 204, dropped.text
    # But the group cannot lose the role: no admin would be left.
    refused = await world.call("DELETE", f"/roles/{admin_role}/groups/{group}", a, a.tech)
    assert problem(refused) == (409, "last_tenant_admin")


async def test_group_roles_are_isolated_by_tenant(world: World) -> None:  # noqa: F811
    a, b = world.a, world.b
    group = await _group(world, "Alpha only")
    auditor = await world.role_id(a, "auditor")
    await world.call("PUT", f"/roles/{auditor}/groups/{group}", a, a.admin)
    conn = await asyncpg.connect(world.db.app_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(b.tenant))
            assert await conn.fetchval("SELECT count(*) FROM group_roles") == 0
            moved = await conn.execute("DELETE FROM group_roles WHERE group_id = $1", group)
            assert moved == "DELETE 0"
    finally:
        await conn.close()


async def test_pickers_find_people_who_hold_a_permission_through_a_group(world: World) -> None:  # noqa: F811
    a = world.a
    group = await _group(world, "Audit pickers")
    auditor = await world.role_id(a, "auditor")
    await world.call("PUT", f"/roles/{auditor}/groups/{group}", a, a.admin)
    await world.call("PUT", f"/organization/groups/{group}/members/{a.tech}", a, a.admin)
    policy = world.app.state.policy
    async with world.app.state.db.tenant_session(TenantContext(a.tenant, a.admin)) as session:
        found = await policy.holders(session, a.tenant, "audit.view")
    assert a.tech in {user for user, _ in found}


async def test_a_sync_made_membership_change_refreshes_access_like_any_other(world: World) -> None:  # noqa: F811
    """Directory sync adds members through organization's add_member with no person (lane B):
    the same membership event goes out, so members' access refreshes as for an admin's change."""
    a = world.a
    group = await _group(world, "Synced")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await add_member(session, "group", group, a.tech)
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        found = await conn.fetchval(
            "SELECT count(*) FROM outbox_events WHERE tenant_id = $1"
            " AND event_type = 'organization.membership.changed'"
            " AND envelope->'payload'->>'user_id' = $2",
            a.tenant,
            str(a.tech),
        )
    finally:
        await conn.close()
    assert found == 1


async def test_disabling_the_last_admin_s_group_is_refused(world: World) -> None:  # noqa: F811
    a = world.a
    group = await _group(world, "Sole owners")
    admin_role = await world.role_id(a, "tenant_admin")
    await world.call("PUT", f"/roles/{admin_role}/groups/{group}", a, a.admin)
    await world.call("PUT", f"/organization/groups/{group}/members/{a.tech}", a, a.admin)
    assert (
        await world.call("DELETE", f"/users/{a.admin}/roles/{admin_role}", a, a.admin)
    ).status_code == 204
    groups = (await world.call("GET", "/organization/groups", a, a.tech)).json()
    version = next(g["version"] for g in groups if g["id"] == str(group))
    refused = await world.call(
        "PATCH",
        f"/organization/groups/{group}",
        a,
        a.tech,
        json={"disabled": True},
        headers={"If-Match": f'"{version}"'},
    )
    assert problem(refused) == (409, "last_tenant_admin")
