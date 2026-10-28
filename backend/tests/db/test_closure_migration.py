"""Migration 0034's data step reaches the tenants that existed before it (lane C's finding).

`work_item_statuses` has FORCE ROW LEVEL SECURITY, so a plain UPDATE in a migration (no
app.tenant_id) changes nothing. Tenants seeded later get the value from the seed code, which
hides the gap; this test seeds a tenant at 0033 and migrates.
"""

import asyncio
import uuid

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db


async def _seed_status(admin_url: str, tenant: uuid.UUID) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(
            "INSERT INTO work_item_statuses (tenant_id, type, code, category, colour, sort_order)"
            " VALUES ($1, 'incident', 'awaiting_requester', 'paused', '#aaaaaa', 1)",
            tenant,
        )
    finally:
        await conn.close()


async def _resume(admin_url: str, tenant: uuid.UUID) -> bool:
    conn = await asyncpg.connect(admin_url)
    try:
        return bool(
            await conn.fetchval(
                "SELECT resume_on_requester_reply FROM work_item_statuses"
                " WHERE tenant_id = $1 AND code = 'awaiting_requester'",
                tenant,
            )
        )
    finally:
        await conn.close()


def test_awaiting_requester_resumes_on_reply_for_existing_tenants(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0033")
    try:
        tenant = asyncio.run(create_tenant(database.migrator_url))
        asyncio.run(_seed_status(database.admin_url, tenant))
        db_testing.migrate(database.migrator_url)
        assert asyncio.run(_resume(database.admin_url, tenant)) is True
    finally:
        db_testing.destroy(db_config, database)
