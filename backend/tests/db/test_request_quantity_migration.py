"""Migration 0193 (a request's quantity, needed-by and expected delivery; WP-047a S1).

Expand only: two item settings and three request columns, all nullable or defaulted, with the
range checks. Up, down and up again; the downgrade drops only those five columns (rule 5h).
"""

import asyncio

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0184"  # 0193's down revision (main's head now; re-pointed at its queue turn)
ITEM_COLUMNS = {"max_quantity", "asks_needed_by"}
REQUEST_COLUMNS = {"quantity", "needed_by", "expected_delivery_at"}


async def _columns(url: str) -> tuple[set[str], set[str], set[str]]:
    """(the item's new columns, the request's new columns, the two range checks present)."""
    conn = await asyncpg.connect(url)
    try:
        items = await conn.fetch(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'catalog_items' AND column_name = ANY($1::text[])",
            sorted(ITEM_COLUMNS),
        )
        requests = await conn.fetch(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'work_items' AND column_name = ANY($1::text[])",
            sorted(REQUEST_COLUMNS),
        )
        checks = await conn.fetch(
            "SELECT conname FROM pg_constraint WHERE conname = ANY($1::text[])",
            ["ck_catalog_items_max_quantity_range", "ck_work_items_quantity_range"],
        )
        return (
            {r["column_name"] for r in items},
            {r["column_name"] for r in requests},
            {r["conname"] for r in checks},
        )
    finally:
        await conn.close()


async def _quantity_rule(url: str) -> str:
    """The request quantity's check as the database states it (1 to 10,000)."""
    conn = await asyncpg.connect(url)
    try:
        found = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'ck_work_items_quantity_range'"
        )
        return str(found)
    finally:
        await conn.close()


def test_0193_adds_the_quantity_and_dates_and_its_downgrade_drops_only_them(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_columns(database.admin_url)) == (set(), set(), set())
        db_testing.migrate(database.migrator_url, "0193")
        items, requests, checks = asyncio.run(_columns(database.admin_url))
        assert (items, requests) == (ITEM_COLUMNS, REQUEST_COLUMNS)
        assert checks == {"ck_catalog_items_max_quantity_range", "ck_work_items_quantity_range"}
        rule = asyncio.run(_quantity_rule(database.admin_url))
        assert "quantity >= 1" in rule
        assert "quantity <= 10000" in rule
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_columns(database.admin_url)) == (set(), set(), set())
        db_testing.migrate(database.migrator_url, "0193")
        assert asyncio.run(_columns(database.admin_url))[1] == REQUEST_COLUMNS
    finally:
        db_testing.destroy(db_config, database)
