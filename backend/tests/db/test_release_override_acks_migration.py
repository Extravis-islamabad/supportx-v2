"""Migration 0139 (a release's freeze override, conflict acks; WP-058b S2) never loses data.

Up, down and up again while nothing uses it. Once a tenant keeps a conflict ack, the downgrade is
refused and the table stays (rule 5h). Rows are seeded by SQL, never through the application, so
the lifecycle audit sink writes nothing a downgrade past 0122 would refuse on.
"""

import asyncio
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0138"  # 0139's down revision


async def _has_acks(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_name = 'work_item_conflict_acks'"
            )
        )
    finally:
        await conn.close()


async def _an_ack(url: str, tenant: uuid.UUID) -> None:
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
                "INSERT INTO work_item_conflict_acks"
                " (id, tenant_id, work_item_id, conflict_key, reason, acked_by, acked_at)"
                " VALUES ($1, $2, $3, 'release:x:1:1', 'Known', $4, now())",
                uuid.uuid4(),
                tenant,
                item,
                user,
            )
    finally:
        await conn.close()


def test_0139_upgrades_downgrades_and_refuses_while_a_tenant_keeps_an_ack(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0139")
        assert asyncio.run(_has_acks(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_has_acks(database.admin_url))
        db_testing.migrate(database.migrator_url, "0139")
        tenant = asyncio.run(create_tenant(database.migrator_url))
        asyncio.run(_an_ack(database.admin_url, tenant))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_acks(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
