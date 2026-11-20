"""Migration 0183 (fine-grained access, the assets' managing group; ADR-053) never loses data.

Up, down and up again while no tenant has a rule; refused once one does (rule 5h). The behaviour:
tests/db/test_resource_access.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0179"  # 0183's down revision for now (re-pointed with it at the lane's queue turn)


async def _shape(url: str) -> tuple[bool, bool]:
    """(the rules table exists, assets has managed_by_group_id)."""
    conn = await asyncpg.connect(url)
    try:
        table = await conn.fetchval("SELECT to_regclass('role_resource_access') IS NOT NULL")
        column = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
            " WHERE table_name = 'assets' AND column_name = 'managed_by_group_id')"
        )
        return bool(table), bool(column)
    finally:
        await conn.close()


async def _with_a_rule(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant, role = uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Records', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO roles (id, tenant_id, key, name) VALUES ($1, $2, 'printers', 'P')",
                role,
                tenant,
            )
            await conn.execute(
                "INSERT INTO role_resource_access (id, tenant_id, role_id, resource, criteria)"
                " VALUES ($1, $2, $3, 'ci', $4::jsonb)",
                uuid.uuid4(),
                tenant,
                role,
                '{"site_ids": ["00000000-0000-0000-0000-000000000001"]}',
            )
    finally:
        await conn.close()


def test_0183_upgrades_downgrades_and_refuses_while_a_rule_exists(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_shape(database.admin_url)) == (False, False)
        db_testing.migrate(database.migrator_url, "0183")
        assert asyncio.run(_shape(database.admin_url)) == (True, True)
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_shape(database.admin_url)) == (False, False)
        db_testing.migrate(database.migrator_url, "0183")
        asyncio.run(_with_a_rule(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_shape(database.admin_url)) == (True, True)
    finally:
        db_testing.destroy(db_config, database)
