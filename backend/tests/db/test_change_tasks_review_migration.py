"""Migration 0133 (task stages, the review date, child changes; WP-045d S1) never loses data.

Up, down and up again while nothing uses it. Once a tenant keeps a task with a stage, the
downgrade is refused and the column stays (rule 5h). Rows are seeded by SQL, never through the
application, so the lifecycle audit sink writes nothing that a downgrade past 0122 would refuse
on (memory: downgrade tests vs lifecycle audit).
"""

import asyncio
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0132"  # 0133's down revision


async def _has_stage_column(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'work_item_tasks' AND column_name = 'stage'"
            )
        )
    finally:
        await conn.close()


async def _a_stage_task(url: str, tenant: uuid.UUID) -> None:
    conn = await asyncpg.connect(url)
    try:
        user, desk, item = (uuid.uuid4() for _ in range(3))
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO users (id, tenant_id, display_name, first_name, user_type)"
                " VALUES ($1, $2, 'Sara', 'Sara', 'requester')",
                user,
                tenant,
            )
            await conn.execute(
                "INSERT INTO desks (id, tenant_id, code, labels)"
                " VALUES ($1, $2, 'it', '{}'::jsonb)",
                desk,
                tenant,
            )
            await conn.execute(
                "INSERT INTO work_item_statuses (tenant_id, type, code, category, colour,"
                " sort_order) VALUES ($1, 'change', 'planning_planning', 'open', '#aaaaaa', 1)",
                tenant,
            )
            await conn.execute(
                "INSERT INTO work_items (id, tenant_id, type, display_id, display_number, subject,"
                " requester_id, channel, priority, priority_source, status, status_category,"
                " desk_id) VALUES ($1, $2, 'change', 'CHG-1', 1, 'Switch', $3, 'phone', 'p3',"
                " 'matrix', 'planning_planning', 'open', $4)",
                item,
                tenant,
                user,
                desk,
            )
            await conn.execute(
                "INSERT INTO work_item_tasks (id, tenant_id, work_item_id, title, position, stage)"
                " VALUES ($1, $2, $3, 'Back up the config', 1, 'planning')",
                uuid.uuid4(),
                tenant,
                item,
            )
    finally:
        await conn.close()


def test_0133_upgrades_downgrades_and_refuses_while_a_tenant_keeps_a_stage_task(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0133")
        assert asyncio.run(_has_stage_column(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_has_stage_column(database.admin_url))
        db_testing.migrate(database.migrator_url, "0133")
        tenant = asyncio.run(create_tenant(database.migrator_url))
        asyncio.run(_a_stage_task(database.admin_url, tenant))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_stage_column(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
