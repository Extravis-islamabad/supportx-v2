"""Migration 0185 (business service subscribers) never loses data.

Up, down and up again while no tenant has a subscription; refused once one does (rule 5h). The
behaviour: tests/db/test_cmdb_service_subscribers.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0179"  # 0185's down revision for now (re-pointed with it at the lane's queue turn)


async def _exists(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(
            await conn.fetchval("SELECT to_regclass('cmdb_service_subscribers') IS NOT NULL")
        )
    finally:
        await conn.close()


async def _with_a_subscription(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        ci_type, state, ci = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Services', $2)",
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
                "INSERT INTO cmdb_service_subscribers (id, tenant_id, ci_id, kind, ref_id)"
                " VALUES ($1, $2, $3, 'group', $4)",
                uuid.uuid4(),
                tenant,
                ci,
                uuid.uuid4(),
            )
    finally:
        await conn.close()


def test_0185_upgrades_downgrades_and_refuses_while_a_subscription_exists(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_exists(database.admin_url)) is False
        db_testing.migrate(database.migrator_url, "0185")
        assert asyncio.run(_exists(database.admin_url)) is True
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_exists(database.admin_url)) is False
        db_testing.migrate(database.migrator_url, "0185")
        asyncio.run(_with_a_subscription(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_exists(database.admin_url)) is True
    finally:
        db_testing.destroy(db_config, database)
