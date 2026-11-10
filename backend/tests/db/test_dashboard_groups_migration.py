"""Migration 0123: group dashboards (D-152). Its downgrade never turns them into private ones.

While any tenant has a group dashboard, the downgrade refuses (rule 5h); the check runs per
tenant with app.tenant_id set, as dashboards force RLS. Without one it goes back cleanly.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db


async def _group_dashboard(admin_url: str) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        tenant, owner = uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Dash', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        await conn.execute(
            "INSERT INTO users (id, tenant_id, email, display_name, first_name, user_type)"
            " VALUES ($1, $2, $3, 'Lead', 'Lead', 'technician')",
            owner,
            tenant,
            f"l-{owner.hex[:8]}@example.test",
        )
        await conn.execute(
            "INSERT INTO dashboards (id, tenant_id, name, owner_id, group_id, body)"
            " VALUES ($1, $2, 'Queue', $3, $4, '{}'::jsonb)",
            uuid.uuid4(),
            tenant,
            owner,
            uuid.uuid4(),
        )
    finally:
        await conn.close()


async def _clear(admin_url: str) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute("UPDATE dashboards SET group_id = NULL")
    finally:
        await conn.close()


def test_the_downgrade_refuses_while_group_dashboards_exist(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0123")
    try:
        asyncio.run(_group_dashboard(database.admin_url))
        with pytest.raises(Exception, match="group dashboards"):
            db_testing.downgrade(database.migrator_url, "0121")
        asyncio.run(_clear(database.admin_url))
        db_testing.downgrade(database.migrator_url, "0121")
    finally:
        db_testing.destroy(db_config, database)
