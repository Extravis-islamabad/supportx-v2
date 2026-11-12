"""Migration 0149 (bulk assign_role, Take's role; WP-058b S5a) never loses data.

Up, down and up again while nothing uses it. Once a tenant marks a role as Take's, the
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

BEFORE = "0144"  # 0149's down revision (re-pointed at its turn)


async def _state(url: str) -> tuple[bool, bool]:
    """(the column exists, the bulk check allows assign_role)."""
    conn = await asyncpg.connect(url)
    try:
        column = bool(
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'work_item_role_defs' AND column_name = 'taken_by_take'"
            )
        )
        check = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'ck_work_item_bulk_jobs_action_code'"
        )
        return column, "'assign_role'" in str(check)
    finally:
        await conn.close()


async def _a_marked_role(url: str, tenant: uuid.UUID) -> None:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO work_item_role_defs (tenant_id, type, code, sort_order, single,"
                " system, taken_by_take) VALUES ($1, 'release', 'release_manager', 1, true,"
                " true, true)",
                tenant,
            )
    finally:
        await conn.close()


def test_0149_upgrades_downgrades_and_refuses_while_a_role_is_take_s(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0149")
        assert asyncio.run(_state(database.admin_url)) == (True, True)
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_state(database.admin_url)) == (False, False)
        db_testing.migrate(database.migrator_url, "0149")
        tenant = asyncio.run(create_tenant(database.migrator_url))
        asyncio.run(_a_marked_role(database.admin_url, tenant))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_state(database.admin_url)) == (True, True)
    finally:
        db_testing.destroy(db_config, database)
