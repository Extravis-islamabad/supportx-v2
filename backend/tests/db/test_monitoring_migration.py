"""Migration 0207 (MonetX connections) never loses data.

Up, down and up again while no tenant has a connection; refused once one does (rule 5h). The
behaviour: tests/db/test_monitoring_integrations.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0204"  # 0207's down revision (re-pointed with it at its queue turn)
TABLES = (
    "monitoring_connections",
    "monitoring_topology_runs",
    "monitoring_devices",
    "monitoring_links",
)


async def _exist(url: str) -> set[bool]:
    conn = await asyncpg.connect(url)
    try:
        return {
            bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table))
            for table in TABLES
        }
    finally:
        await conn.close()


async def _with_a_connection(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'MonetX', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO monitoring_connections (id, tenant_id, name, base_url)"
                " VALUES ($1, $2, 'MonetX', 'https://m.example.com')",
                uuid.uuid4(),
                tenant,
            )
    finally:
        await conn.close()


def test_0207_upgrades_downgrades_and_refuses_while_a_connection_exists(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_exist(database.admin_url)) == {False}
        db_testing.migrate(database.migrator_url, "0207")
        assert asyncio.run(_exist(database.admin_url)) == {True}
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_exist(database.admin_url)) == {False}
        db_testing.migrate(database.migrator_url, "0207")
        asyncio.run(_with_a_connection(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_exist(database.admin_url)) == {True}
    finally:
        db_testing.destroy(db_config, database)
