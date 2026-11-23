"""Migration 0175 (custom fields scoped to a type subtree; CIs) never loses data.

Up, down and up again while no tenant has a scoped or CI field; once one does, the downgrade is
refused and the column stays (rule 5h).
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0174"  # 0175's down revision for now (re-pointed with it at the queue turn)


async def _has_column(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        found = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'custom_fields' AND column_name = 'scope_type_id'"
        )
        return bool(found)
    finally:
        await conn.close()


async def _tenant_with_a_ci_field(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Scopes', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO custom_fields (tenant_id, id, entity, key, field_type, labels,"
                " scope_type_id) VALUES ($1, $2, 'ci', 'rack_unit', 'text',"
                ' \'{"en": "Rack unit"}\'::jsonb, $3)',
                tenant,
                uuid.uuid4(),
                uuid.uuid4(),
            )
    finally:
        await conn.close()


def test_0175_upgrades_downgrades_and_refuses_while_a_tenant_has_scoped_fields(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert not asyncio.run(_has_column(database.admin_url))
        db_testing.migrate(database.migrator_url, "0175")
        assert asyncio.run(_has_column(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_has_column(database.admin_url))
        db_testing.migrate(database.migrator_url, "0175")
        asyncio.run(_tenant_with_a_ci_field(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_column(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
