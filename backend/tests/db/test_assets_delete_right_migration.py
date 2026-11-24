"""Migration 0202 (D-185): every assets.manage holder keeps delete through assets.delete.

Up copies `assets.manage` to `assets.delete` at the same scope, per tenant under RLS, including a
role held by a service identity. Down removes only those copies, and refuses while a tenant
granted assets.delete on its own (rule 5h). The behaviour: tests/db/test_assets_delete_right.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0197"  # 0202's down revision


async def _tenant_with_roles(url: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant, a person's manager role at site scope, a service's manager role, a viewer role)."""
    conn = await asyncpg.connect(url)
    try:
        tenant, person_role, service_role, viewer = (uuid.uuid4() for _ in range(4))
        service = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Assets', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            for role, key in ((person_role, "mgr"), (service_role, "bot"), (viewer, "viewer")):
                await conn.execute(
                    "INSERT INTO roles (id, tenant_id, key, name) VALUES ($1, $2, $3, $3)",
                    role,
                    tenant,
                    key,
                )
            for role, permission, scope in (
                (person_role, "assets.manage", "site"),
                (service_role, "assets.manage", "all"),
                (viewer, "assets.view", "all"),
            ):
                await conn.execute(
                    "INSERT INTO role_permissions (tenant_id, role_id, permission, scope)"
                    " VALUES ($1, $2, $3, $4)",
                    tenant,
                    role,
                    permission,
                    scope,
                )
            await conn.execute(
                "INSERT INTO users (id, tenant_id, display_name, first_name, user_type,"
                " can_sign_in)"
                " VALUES ($1, $2, 'Import bot', 'Import', 'service', false)",
                service,
                tenant,
            )
            await conn.execute(
                "INSERT INTO user_roles (tenant_id, user_id, role_id) VALUES ($1, $2, $3)",
                tenant,
                service,
                service_role,
            )
        return tenant, person_role, service_role, viewer
    finally:
        await conn.close()


async def _deletes(url: str, tenant: uuid.UUID) -> dict[uuid.UUID, str]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            rows = await conn.fetch(
                "SELECT role_id, scope FROM role_permissions WHERE permission = 'assets.delete'"
            )
        return {r["role_id"]: r["scope"] for r in rows}
    finally:
        await conn.close()


async def _grant_delete_alone(url: str, tenant: uuid.UUID, role: uuid.UUID) -> None:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, permission, scope)"
                " VALUES ($1, $2, 'assets.delete', 'all')",
                tenant,
                role,
            )
    finally:
        await conn.close()


def test_0202_copies_manage_to_delete_removes_only_its_copies_and_refuses_an_own_grant(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        tenant, person_role, service_role, viewer = asyncio.run(
            _tenant_with_roles(database.admin_url)
        )
        db_testing.migrate(database.migrator_url, "0202")
        copied = asyncio.run(_deletes(database.admin_url, tenant))
        # The same scope as each role's assets.manage; the viewer gets nothing.
        assert copied == {person_role: "site", service_role: "all"}
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_deletes(database.admin_url, tenant)) == {}
        db_testing.migrate(database.migrator_url, "0202")
        # The tenant gives assets.delete to a role without assets.manage: its own choice.
        asyncio.run(_grant_delete_alone(database.admin_url, tenant, viewer))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert viewer in asyncio.run(_deletes(database.admin_url, tenant))
    finally:
        db_testing.destroy(db_config, database)
