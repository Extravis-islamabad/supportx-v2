"""Migration 0162 (field access per role; ADR-047, WP-046a S7) never loses data (rule 5h).

Up, down and up again while no tenant has a rule; refused once one does. The behaviour:
tests/db/test_field_access_api.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0161"  # 0162's down revision


async def _has_table(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(await conn.fetchval("SELECT to_regclass('role_field_access') IS NOT NULL"))
    finally:
        await conn.close()


async def _with_a_rule(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant, role = uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Fields', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO roles (id, tenant_id, key, name) VALUES ($1, $2, 'hr_desk', 'HR')",
                role,
                tenant,
            )
            await conn.execute(
                "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
                " VALUES ($1, $2, $3, 'incident', 'custom.salary', 'hidden')",
                uuid.uuid4(),
                tenant,
                role,
            )
    finally:
        await conn.close()


def test_0162_upgrades_downgrades_and_refuses_while_a_rule_exists(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0162")
        assert asyncio.run(_has_table(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_has_table(database.admin_url))
        db_testing.migrate(database.migrator_url, "0162")
        asyncio.run(_with_a_rule(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_table(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
