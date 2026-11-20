"""Migration 0182 (a person's list layout and board grouping; WP-046b S3b): up, down, up again.

Expand only: two nullable columns with checks on `work_item_list_settings`. The downgrade drops
the columns (people's layout goes back to the table) and touches no other row (rule 5h).
"""

import asyncio

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0179"  # 0182's down revision (main's head at its queue turn)


async def _shape(url: str) -> tuple[set[str], set[str]]:
    """(the columns, the check constraints) of work_item_list_settings."""
    conn = await asyncpg.connect(url)
    try:
        columns = await conn.fetch(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'work_item_list_settings'"
            " AND column_name IN ('layout', 'group_by')"
        )
        checks = await conn.fetch(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'work_item_list_settings'::regclass"
            " AND contype = 'c' AND conname LIKE ANY (ARRAY['%layout%', '%group_by%'])"
        )
        return {r["column_name"] for r in columns}, {r["conname"] for r in checks}
    finally:
        await conn.close()


async def _check(url: str, column: str) -> str:
    """The text of the column's check constraint."""
    conn = await asyncpg.connect(url)
    try:
        return str(
            await conn.fetchval(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conrelid = 'work_item_list_settings'::regclass AND contype = 'c'"
                " AND conname LIKE $1",
                f"%{column}_code%",
            )
        )
    finally:
        await conn.close()


def test_0182_adds_the_two_columns_with_their_checks_and_its_downgrade_drops_them(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_shape(database.admin_url)) == (set(), set())
        db_testing.migrate(database.migrator_url, "0182")
        columns, checks = asyncio.run(_shape(database.admin_url))
        assert columns == {"layout", "group_by"}
        assert len(checks) == 2
        layout = asyncio.run(_check(database.admin_url, "layout"))
        for code in ("table", "cards", "board", "calendar"):
            assert f"'{code}'" in layout
        group_by = asyncio.run(_check(database.admin_url, "group_by"))
        for code in ("status", "priority", "technician", "group"):
            assert f"'{code}'" in group_by
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_shape(database.admin_url)) == (set(), set())
        db_testing.migrate(database.migrator_url, "0182")
        assert asyncio.run(_shape(database.admin_url))[0] == {"layout", "group_by"}
    finally:
        db_testing.destroy(db_config, database)
