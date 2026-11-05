"""Migration 0080's downgrade never loses data (rule 5h).

While no tenant has catalogue rows the tables go; once one tenant has a state (its defaults are
made the first time its catalogue is used), the downgrade is refused and nothing is dropped.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db


async def _tenant_with_a_state(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Assets', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO asset_states (tenant_id, id, code, names, category, sort)"
                " VALUES ($1, $2, 'in_store', '{\"en\": \"In store\"}', 'in_stock', 0)",
                tenant,
                uuid.uuid4(),
            )
    finally:
        await conn.close()


async def _tables(url: str) -> int:
    conn = await asyncpg.connect(url)
    try:
        return int(
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.tables WHERE table_name LIKE 'asset_%'"
            )
        )
    finally:
        await conn.close()


def test_0080_downgrade_drops_empty_tables_and_refuses_when_a_tenant_has_data(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0080")
    try:
        assert asyncio.run(_tables(database.admin_url)) == 6
        db_testing.downgrade(database.migrator_url, "0092")
        assert asyncio.run(_tables(database.admin_url)) == 0
        db_testing.migrate(database.migrator_url, "0080")
        asyncio.run(_tenant_with_a_state(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, "0092")
        assert asyncio.run(_tables(database.admin_url)) == 6
    finally:
        db_testing.destroy(db_config, database)
