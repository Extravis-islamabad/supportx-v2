"""Migration 0160 (kept drafts; WP-046a S5c) never loses data (rule 5h).

Up, down and up again while no tenant holds a draft; refused once one does. The behaviour:
tests/db/test_drafts_api.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0159"  # 0160's down revision


async def _has_table(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(await conn.fetchval("SELECT to_regclass('work_item_drafts') IS NOT NULL"))
    finally:
        await conn.close()


async def _with_a_draft(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant, user = uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Drafts', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO users (id, tenant_id, email, display_name, first_name, last_name,"
                " user_type) VALUES ($1, $2, 'd@drafts.test', 'D', 'D', 'D', 'technician')",
                user,
                tenant,
            )
            await conn.execute(
                "INSERT INTO work_item_drafts (id, tenant_id, owner_id, type, form_key, body)"
                " VALUES ($1, $2, $3, 'incident', 'incident-new', 'sealed')",
                uuid.uuid4(),
                tenant,
                user,
            )
    finally:
        await conn.close()


def test_0160_upgrades_downgrades_and_refuses_while_a_draft_is_kept(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0160")
        assert asyncio.run(_has_table(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_has_table(database.admin_url))
        db_testing.migrate(database.migrator_url, "0160")
        asyncio.run(_with_a_draft(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_table(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
