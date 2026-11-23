"""Migration 0187 (the system log; WP-057 S5b) never loses an entry.

Up, down and up again while no tenant has an entry; once one has, the downgrade is refused and
the table stays (lane B on #567): the log is append-only, so a downgrade is never a way round it.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0190"  # 0187's down revision (re-pointed with it at the lane's queue turn)
TABLE = "system_log_entries"


async def _has_table(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", TABLE))
    finally:
        await conn.close()


async def _tenants_one_with_an_entry(url: str) -> None:
    """Three tenants, only the middle one with an entry: the refusal must find it in any tenant,
    not only the first the downgrade's loop visits (lane B on #567)."""
    conn = await asyncpg.connect(url)
    try:
        tenants = [uuid.uuid4() for _ in range(3)]
        for tenant in tenants:
            await conn.execute(
                "INSERT INTO tenants (id, name, slug) VALUES ($1, 'System log', $2)",
                tenant,
                f"t-{tenant.hex[:12]}",
            )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenants[1]))
            await conn.execute(
                f"INSERT INTO {TABLE} (id, tenant_id, occurred_at, severity, module, code)"  # noqa: S608 - a fixed table name
                " VALUES ($1, $2, now(), 'error', 'audit', 'audit.export.failed')",
                uuid.uuid4(),
                tenants[1],
            )
    finally:
        await conn.close()


def test_0187_upgrades_downgrades_and_refuses_while_a_tenant_has_entries(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert not asyncio.run(_has_table(database.admin_url))
        db_testing.migrate(database.migrator_url, "0187")
        assert asyncio.run(_has_table(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)  # empty: allowed
        assert not asyncio.run(_has_table(database.admin_url))
        db_testing.migrate(database.migrator_url, "0187")
        asyncio.run(_tenants_one_with_an_entry(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_table(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
