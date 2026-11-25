"""Migration 0209 (CI baselines; WP-053 S7b) never loses data.

Up, down and up again while no tenant has a baseline; once one does, the downgrade is refused
and the table stays (rule 5h).
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0204"  # 0209's down revision for now (re-pointed with it at the lane's queue turn)


async def _exists(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(await conn.fetchval("SELECT to_regclass('cmdb_ci_baselines') IS NOT NULL"))
    finally:
        await conn.close()


async def _a_baseline(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant, ci_type, state, ci = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Baselines', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO cmdb_ci_types (id, tenant_id, api_name) VALUES ($1, $2, 'svc')",
                ci_type,
                tenant,
            )
            await conn.execute(
                "INSERT INTO cmdb_ci_states (id, tenant_id, api_name) VALUES ($1, $2, 'up')",
                state,
                tenant,
            )
            await conn.execute(
                "INSERT INTO cmdb_cis (id, tenant_id, display_id, type_id, state_id, name)"
                " VALUES ($1, $2, 'CI-1', $3, $4, 'Payroll')",
                ci,
                tenant,
                ci_type,
                state,
            )
            await conn.execute(
                "INSERT INTO cmdb_ci_baselines (tenant_id, id, ci_id, name, from_version, snapshot)"
                " VALUES ($1, $2, $3, 'Gold', 1, '{}')",
                tenant,
                uuid.uuid4(),
                ci,
            )
    finally:
        await conn.close()


def test_0209_upgrades_downgrades_and_refuses_while_a_tenant_has_a_baseline(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert not asyncio.run(_exists(database.admin_url))
        db_testing.migrate(database.migrator_url, "0209")
        assert asyncio.run(_exists(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_exists(database.admin_url))
        db_testing.migrate(database.migrator_url, "0209")
        asyncio.run(_a_baseline(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_exists(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
