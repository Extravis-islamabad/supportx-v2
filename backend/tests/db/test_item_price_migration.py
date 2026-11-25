"""Migration 0205 (item prices, the estimate and charge-back; WP-047b S1).

Expand only: the item's price columns, the tenant's setting, the request's estimate and charge,
their checks and index, and supportx_report reading an item's ID and names only. Up, down and
up again; the downgrade drops only what 0205 added and takes the grant back (rule 5h).
"""

import asyncio

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0204"  # 0205's down revision (main's head at its queue turn)
ITEM_COLUMNS = {"price", "internal_cost", "price_period", "charge_to", "charge_question_key"}
REQUEST_COLUMNS = {
    "estimated_cost",
    "estimate_period",
    "charge_department_id",
    "charge_cost_centre",
    "charged_amount",
    "charged_at",
}


async def _state(url: str) -> tuple[set[str], set[str], bool, set[str]]:
    """(item columns, request columns, the setting present, item columns the report role reads)."""
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
        setting = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'catalog_settings' AND column_name = 'requesters_see_prices'"
        )
        readable = await conn.fetch(
            "SELECT column_name FROM information_schema.column_privileges"
            " WHERE table_name = 'catalog_items' AND grantee = 'supportx_report'"
            " AND privilege_type = 'SELECT'"
        )
        return (
            {r["column_name"] for r in items},
            {r["column_name"] for r in requests},
            bool(setting),
            {r["column_name"] for r in readable},
        )
    finally:
        await conn.close()


def test_0205_adds_prices_and_charge_back_and_its_downgrade_drops_only_them(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        items, requests, setting, readable = asyncio.run(_state(database.admin_url))
        assert (items, requests, setting, readable) == (set(), set(), False, set())
        db_testing.migrate(database.migrator_url, "0205")
        items, requests, setting, readable = asyncio.run(_state(database.admin_url))
        assert (items, requests, setting) == (ITEM_COLUMNS, REQUEST_COLUMNS, True)
        # Names only: never an item's descriptions or forms (free text).
        assert readable == {"id", "tenant_id", "names", "deleted_at"}
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_state(database.admin_url)) == (set(), set(), False, set())
        db_testing.migrate(database.migrator_url, "0205")
        assert asyncio.run(_state(database.admin_url))[1] == REQUEST_COLUMNS
    finally:
        db_testing.destroy(db_config, database)
