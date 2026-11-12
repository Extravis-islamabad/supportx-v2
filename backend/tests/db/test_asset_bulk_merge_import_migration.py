"""Migration 0145 (asset bulk jobs, merges and imports; WP-049b S4b) never loses data.

Up, down and up again while no tenant has a row in a new table; once one does, the downgrade
is refused and the tables stay (rule 5h).
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0140"  # 0145's down revision for now (re-pointed with it at the lane's queue turn)
TABLES = ("asset_bulk_jobs", "asset_merges", "asset_imports")


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


async def _tenant_with_an_import(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Imports', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO asset_imports (tenant_id, id, kind, mode, match_on, file_name,"
                " file_format) VALUES ($1, $2, 'assets', 'add', 'tag', 'a.csv', 'csv')",
                tenant,
                uuid.uuid4(),
            )
    finally:
        await conn.close()


def test_0145_upgrades_downgrades_and_refuses_while_a_tenant_has_rows(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_tables(database.admin_url)) == 0
        db_testing.migrate(database.migrator_url, "0145")
        assert asyncio.run(_tables(database.admin_url)) == len(TABLES)
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_tables(database.admin_url)) == 0
        db_testing.migrate(database.migrator_url, "0145")
        asyncio.run(_tenant_with_an_import(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_tables(database.admin_url)) == len(TABLES)
    finally:
        db_testing.destroy(db_config, database)
