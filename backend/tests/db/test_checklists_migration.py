"""Migration 0144 (checklists and reminders; WP-046a S2) never loses data (rule 5h).

Up, down and up again while no tenant uses it; once one tenant keeps a library checklist, the
downgrade is refused and the tables stay. The behaviour: tests/db/test_checklists_api.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0138"  # 0144's down revision


async def _has_table(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_name = 'checklist_library'"
            )
        )
    finally:
        await conn.close()


async def _tenant_with_a_checklist(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Checklists', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO checklist_library (tenant_id, id, type, name, items)"
                """ VALUES ($1, $2, 'incident', 'Kept', '[{"title": "x"}]'::jsonb)""",
                tenant,
                uuid.uuid4(),
            )
    finally:
        await conn.close()


def test_0144_upgrades_downgrades_and_refuses_while_a_tenant_keeps_a_checklist(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0144")
        assert asyncio.run(_has_table(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_has_table(database.admin_url))
        db_testing.migrate(database.migrator_url, "0144")
        asyncio.run(_tenant_with_a_checklist(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_table(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
