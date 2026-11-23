"""Migration 0184 (requester cancel and edit rules; WP-046b S5): up, down and up again.

Expand only: two settings columns with defaults (off, none) and a new table with RLS. The
downgrade drops the table and both columns, touching no other row (rule 5h).
"""

import asyncio

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0190"  # 0184's down revision (main's head at its queue turn)
TABLE = "work_item_cancellation_requests"


async def _shape(url: str) -> tuple[set[str], bool, bool]:
    """(the two settings columns present, the table present, its RLS forced)."""
    conn = await asyncpg.connect(url)
    try:
        columns = await conn.fetch(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'work_item_type_settings'"
            " AND column_name IN ('requester_cancel', 'requester_edit_fields')"
        )
        table = await conn.fetchrow(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = $1", TABLE
        )
        return (
            {r["column_name"] for r in columns},
            table is not None,
            table is not None and bool(table["relrowsecurity"]),
        )
    finally:
        await conn.close()


def test_0184_adds_the_settings_and_the_asks_table_and_its_downgrade_drops_them(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_shape(database.admin_url)) == (set(), False, False)
        db_testing.migrate(database.migrator_url, "0184")
        assert asyncio.run(_shape(database.admin_url)) == (
            {"requester_cancel", "requester_edit_fields"},
            True,
            True,
        )
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_shape(database.admin_url)) == (set(), False, False)
        db_testing.migrate(database.migrator_url, "0184")
        assert asyncio.run(_shape(database.admin_url))[1] is True
    finally:
        db_testing.destroy(db_config, database)
