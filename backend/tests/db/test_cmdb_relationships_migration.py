"""Migration 0180 (CMDB relationships and business views; WP-053 S2) never loses data.

Up, down and up again while no tenant has a relationship, a view or its own relationship type;
once a tenant has its own type, the downgrade is refused and the tables stay (rule 5h).
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0176"  # 0180's down revision for now (re-pointed with it at the lane's queue turn)
TABLES = (
    "cmdb_relationship_types",
    "cmdb_relationship_type_rules",
    "cmdb_relationships",
    "cmdb_business_views",
)


async def _tables(url: str) -> int:
    conn = await asyncpg.connect(url)
    try:
        found = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ANY($1::text[])",
            list(TABLES),
        )
        return int(found)
    finally:
        await conn.close()


async def _tenant_with_its_own_type(url: str, *, built_in: bool) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Relationships', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO cmdb_relationship_types (tenant_id, id, code, built_in)"
                " VALUES ($1, $2, 'feeds', $3)",
                tenant,
                uuid.uuid4(),
                built_in,
            )
    finally:
        await conn.close()


def test_0180_upgrades_downgrades_and_refuses_while_a_tenant_has_rows(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_tables(database.admin_url)) == 0
        db_testing.migrate(database.migrator_url, "0180")
        assert asyncio.run(_tables(database.admin_url)) == len(TABLES)
        # Built-in types alone are made again on first use: they never hold a downgrade back.
        asyncio.run(_tenant_with_its_own_type(database.admin_url, built_in=True))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_tables(database.admin_url)) == 0
        db_testing.migrate(database.migrator_url, "0180")
        asyncio.run(_tenant_with_its_own_type(database.admin_url, built_in=False))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_tables(database.admin_url)) == len(TABLES)
    finally:
        db_testing.destroy(db_config, database)
