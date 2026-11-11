"""Migration 0106 (WP-048b S2: sub-flows, the approval chair, workflow approvals and tasks).

Up, down and up again on an empty database; and the downgrade refuses while a tenant uses what
it would drop (rule 5h), here a chair (D-146). The tables force RLS, so the check runs per
tenant: a bare SELECT would see nothing and let the drop through.

Seeded with SQL, not through the app: an app save writes lifecycle audit entries (WP-064), and
this test stays clear of them. It only goes down to 0127 anyway, above 0122.
"""

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0127"  # 0106's down revision (re-pointed onto main's head)


@pytest.fixture
def head(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A throwaway database migrated to 0106."""
    database = db_testing.create(db_config, migrate_to="0106")
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


async def _chair(database: db_testing.ThrowawayDatabase) -> uuid.UUID:
    """A tenant whose approvals have a chair; returns the tenant."""
    tenant = await create_tenant(database.migrator_url, "Chaired")
    person = uuid.uuid4()
    conn = await asyncpg.connect(database.admin_url)
    try:
        await conn.execute(
            "INSERT INTO users (id, tenant_id, display_name, first_name, user_type)"
            " VALUES ($1, $2, 'Chair', 'Chair', 'technician')",
            person,
            tenant,
        )
        await conn.execute(
            "INSERT INTO work_item_approval_settings (tenant_id, chair_user_id) VALUES ($1, $2)",
            tenant,
            person,
        )
    finally:
        await conn.close()
    return tenant


async def _no_chair(database: db_testing.ThrowawayDatabase, tenant: uuid.UUID) -> None:
    conn = await asyncpg.connect(database.admin_url)
    try:
        await conn.execute(
            "UPDATE work_item_approval_settings SET chair_user_id = NULL WHERE tenant_id = $1",
            tenant,
        )
    finally:
        await conn.close()


def test_0106_upgrades_downgrades_and_upgrades_again(head: db_testing.ThrowawayDatabase) -> None:
    db_testing.downgrade(head.migrator_url, BEFORE)
    db_testing.migrate(head.migrator_url, "0106")


def test_the_downgrade_refuses_while_a_tenant_has_a_chair(
    head: db_testing.ThrowawayDatabase,
) -> None:
    tenant = asyncio.run(_chair(head))
    with pytest.raises(Exception, match="downgrade refused"):
        db_testing.downgrade(head.migrator_url, BEFORE)
    # Without the chair the downgrade goes through, and up again applies cleanly.
    asyncio.run(_no_chair(head, tenant))
    db_testing.downgrade(head.migrator_url, BEFORE)
    db_testing.migrate(head.migrator_url, "0106")
