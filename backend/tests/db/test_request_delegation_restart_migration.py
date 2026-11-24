"""Migration 0197 (approval delegation and restart; WP-047a S3b): up, down and up again."""

import asyncio

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0196"
COLUMNS = {
    "work_item_approvals.on_behalf_of_id",
    "work_item_approvals.round",
    "work_items.approval_round",
}


async def _shape(url: str) -> tuple[set[str], tuple[bool, bool] | None]:
    conn = await asyncpg.connect(url)
    try:
        columns = await conn.fetch(
            "SELECT table_name || '.' || column_name AS c FROM information_schema.columns"
            " WHERE table_name || '.' || column_name = ANY($1::text[])",
            sorted(COLUMNS),
        )
        rls = await conn.fetchrow(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relname = 'approval_delegations'"
        )
        return (
            {r["c"] for r in columns},
            None if rls is None else (rls["relrowsecurity"], rls["relforcerowsecurity"]),
        )
    finally:
        await conn.close()


def test_0197_adds_its_parts_and_its_downgrade_drops_them(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_shape(database.admin_url)) == (set(), None)
        db_testing.migrate(database.migrator_url, "0197")
        assert asyncio.run(_shape(database.admin_url)) == (COLUMNS, (True, True))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_shape(database.admin_url)) == (set(), None)
        db_testing.migrate(database.migrator_url, "0197")
        assert asyncio.run(_shape(database.admin_url))[0] == COLUMNS
    finally:
        db_testing.destroy(db_config, database)
