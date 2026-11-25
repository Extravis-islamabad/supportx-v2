"""Migration 0199 (CIs on work items; WP-053 S5, lane A): up, down and up again."""

import asyncio

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0188"  # 0199's down revision for now (re-pointed onto main's head at its turn)


async def _table(url: str) -> tuple[bool, bool] | None:
    conn = await asyncpg.connect(url)
    try:
        row = await conn.fetchrow(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relname = 'work_item_cis'"
        )
        return None if row is None else (row["relrowsecurity"], row["relforcerowsecurity"])
    finally:
        await conn.close()


def test_0199_adds_the_table_with_rls_and_its_downgrade_drops_it(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_table(database.admin_url)) is None
        db_testing.migrate(database.migrator_url, "0199")
        assert asyncio.run(_table(database.admin_url)) == (True, True)  # rule 5a
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_table(database.admin_url)) is None
        db_testing.migrate(database.migrator_url, "0199")
        assert asyncio.run(_table(database.admin_url)) == (True, True)
    finally:
        db_testing.destroy(db_config, database)
