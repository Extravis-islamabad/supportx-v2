"""Migration 0198 (CI downtimes) never loses data.

Up, down and up again while no tenant has a downtime; refused once one does (rule 5h). The
behaviour: tests/db/test_cmdb_downtimes.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0188"  # 0198's down revision (re-pointed with it at its queue turn)


async def _exists(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(await conn.fetchval("SELECT to_regclass('cmdb_ci_downtimes') IS NOT NULL"))
    finally:
        await conn.close()


async def _with_a_downtime(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        ci_type, state, ci = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Downtimes', $2)",
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
                "INSERT INTO cmdb_ci_downtimes (id, tenant_id, ci_id, source, phase, starts_at)"
                " VALUES ($1, $2, $3, 'manual', 'actual', now())",
                uuid.uuid4(),
                tenant,
                ci,
            )
    finally:
        await conn.close()


def test_0198_upgrades_downgrades_and_refuses_while_a_downtime_exists(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_exists(database.admin_url)) is False
        db_testing.migrate(database.migrator_url, "0198")
        assert asyncio.run(_exists(database.admin_url)) is True
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_exists(database.admin_url)) is False
        db_testing.migrate(database.migrator_url, "0198")
        asyncio.run(_with_a_downtime(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_exists(database.admin_url)) is True
    finally:
        db_testing.destroy(db_config, database)
