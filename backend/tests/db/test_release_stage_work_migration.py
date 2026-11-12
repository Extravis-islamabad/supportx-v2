"""Migration 0142 (worklogs by stage, the stage-task setting; WP-058b S3) never loses data.

Up, down and up again while nothing uses it. Once a tenant keeps a worklog with a stage, the
downgrade is refused and the column stays (rule 5h). Rows are seeded by SQL, never through the
application, so the lifecycle audit sink writes nothing a downgrade past 0122 would refuse on.
"""

import asyncio
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0139"  # 0142's down revision (re-pointed at its turn)


async def _has_stage(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'work_item_worklogs' AND column_name = 'stage'"
            )
        )
    finally:
        await conn.close()


async def _a_staged_worklog(url: str, tenant: uuid.UUID) -> None:
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
                " sort_order) VALUES ($1, 'release', 'deployment_scheduled', 'open', '#aaaaaa', 1)",
                tenant,
            )
            await conn.execute(
                "INSERT INTO work_items (id, tenant_id, type, display_id, display_number, subject,"
                " requester_id, channel, priority, priority_source, status, status_category,"
                " desk_id) VALUES ($1, $2, 'release', 'REL-1', 1, 'Payroll', $3, 'phone', 'p3',"
                " 'matrix', 'deployment_scheduled', 'open', $4)",
                item,
                tenant,
                user,
                desk,
            )
            await conn.execute(
                "INSERT INTO work_item_worklogs (id, tenant_id, work_item_id, owner_id,"
                " worklog_type, started_at, ended_at, minutes, stage)"
                " VALUES ($1, $2, $3, $4, 'fix', now() - interval '1 hour', now(), 60,"
                " 'deployment')",
                uuid.uuid4(),
                tenant,
                item,
                user,
            )
    finally:
        await conn.close()


def test_0142_upgrades_downgrades_and_refuses_while_a_worklog_has_a_stage(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0142")
        assert asyncio.run(_has_stage(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_has_stage(database.admin_url))
        db_testing.migrate(database.migrator_url, "0142")
        tenant = asyncio.run(create_tenant(database.migrator_url))
        asyncio.run(_a_staged_worklog(database.admin_url, tenant))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_stage(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
