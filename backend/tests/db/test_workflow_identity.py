"""A workflow's run-as identity, to lane B's conditions (WP-048b S1, ADR-043 §6).

Real PostgreSQL, the real policy layer:
- a service identity made for a workflow says so in history (source "workflow");
- roles reach it only through the guarded path: never beyond the giving admin's own rights,
  never tenant administration or a role that manages identities, roles or previews people;
- a disabled identity can do nothing;
- it never shows in people lists.
"""

import uuid

import pytest
from sqlalchemy import text

from app.core.errors import PermissionDenied
from app.core.tenancy import TenantContext
from app.modules.identity_access import (
    assign_service_identity_role,
    create_service_identity,
    set_service_identity_active,
    subject_for,
    worker_policy,
)
from tests.db.test_incidents_api import World, role, world

__all__ = ["world"]  # the fixture, re-used


async def _identity(world: World) -> uuid.UUID:
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        return await create_service_identity(
            session, name="Workflow: Major incident", source="workflow"
        )


async def _give(world: World, giver: uuid.UUID, identity: uuid.UUID, role_id: uuid.UUID) -> bool:
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        subject = await subject_for(session, a.tenant, giver)
        return await assign_service_identity_role(
            session, worker_policy(), subject, identity, role_id
        )


async def _system_role(world: World, key: str) -> uuid.UUID:
    rows = await world.sql(
        "SELECT id FROM roles WHERE tenant_id = $1 AND key = $2", world.a.tenant, key
    )
    return uuid.UUID(str(rows[0]["id"]))


async def test_history_names_the_workflow(world: World) -> None:
    identity = await _identity(world)
    rows = await world.sql(
        "SELECT source FROM field_changes WHERE record_id = $1 AND kind = 'created'", identity
    )
    assert [r["source"] for r in rows] == ["workflow"]


async def test_an_admin_gives_a_role_within_their_rights(world: World) -> None:
    a = world.a
    identity = await _identity(world)
    editor = await role(world, a, "Workflow editors", [("incidents.edit", "all")])
    assert await _give(world, a.admin, identity, editor) is True


async def test_never_tenant_administration(world: World) -> None:
    identity = await _identity(world)
    with pytest.raises(PermissionDenied) as refused:
        await _give(world, world.a.admin, identity, await _system_role(world, "tenant_admin"))
    assert refused.value.instance_code == "service_identity_role_not_allowed"


# users.preview is guarded too; it joins the catalogue with lane B's people work.
@pytest.mark.parametrize("permission", ["identity.manage", "roles.manage"])
async def test_never_a_role_that_changes_who_may_do_what(world: World, permission: str) -> None:
    a = world.a
    identity = await _identity(world)
    risky = await role(world, a, f"Risky {permission}", [(permission, "all")])
    with pytest.raises(PermissionDenied) as refused:
        await _give(world, a.admin, identity, risky)
    assert refused.value.instance_code == "service_identity_role_not_allowed"


async def test_never_beyond_the_giver_s_own_rights(world: World) -> None:
    a = world.a
    identity = await _identity(world)
    beyond = await role(world, a, "Deleters", [("incidents.delete", "all")])
    with pytest.raises(PermissionDenied) as refused:
        await _give(world, a.tech_a, identity, beyond)  # a technician cannot hand that out
    assert refused.value.instance_code == "privilege_escalation"


async def test_a_disabled_identity_can_do_nothing(world: World) -> None:
    a = world.a
    identity = await _identity(world)
    await _give(
        world, a.admin, identity, await role(world, a, "Viewers", [("incidents.view", "all")])
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await subject_for(session, a.tenant, identity)).holds("incidents.view")
        await set_service_identity_active(session, identity, active=False)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert not (await subject_for(session, a.tenant, identity)).holds("incidents.view")


async def test_it_never_shows_in_people_lists(world: World) -> None:
    a = world.a
    identity = await _identity(world)
    listed = await world.call("GET", "/users?limit=100", a, a.admin)
    assert listed.status_code == 200, listed.text
    assert str(identity) not in {u["id"] for u in listed.json()["items"]}
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        found = await session.execute(
            text("SELECT user_type FROM users WHERE id = :i"), {"i": identity}
        )
        assert found.scalar_one() == "service"
