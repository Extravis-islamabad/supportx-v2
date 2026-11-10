"""Migration 0131 (asset financials, notes, attachments; WP-049b s2) never loses data (rule 5h).

Up, down and up again while no tenant uses it; once one tenant keeps a cost line, or sets a cost
centre on an asset, the downgrade is refused and every new table and column stays.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0130"  # 0131's down revision
NEW = ("asset_costs", "asset_notes", "asset_valuations")


async def _shape(url: str) -> tuple[int, int, str]:
    """(new tables, new asset columns, the file owner check)."""
    conn = await asyncpg.connect(url)
    try:
        tables = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ANY($1)", list(NEW)
        )
        columns = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'assets' AND column_name = ANY($1)",
            ["cost_centre", "gl_code", "depreciation_method", "useful_life_years", "salvage_value"],
        )
        check = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'ck_file_links_owner_type'"
        )
        return int(tables), int(columns), str(check)
    finally:
        await conn.close()


async def _tenant_with_an_asset(url: str, *, cost: bool) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant, kind, product, state, asset = (uuid.uuid4() for _ in range(5))
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Money', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO asset_product_types (tenant_id, id, api_name, names, category, kind)"
                " VALUES ($1, $2, 'laptop', '{\"en\": \"Laptop\"}', 'it', 'asset')",
                tenant,
                kind,
            )
            await conn.execute(
                "INSERT INTO asset_products (tenant_id, id, product_type_id, name)"
                " VALUES ($1, $2, $3, 'X1')",
                tenant,
                product,
                kind,
            )
            await conn.execute(
                "INSERT INTO asset_states (tenant_id, id, code, names, category)"
                " VALUES ($1, $2, 'in_store', '{\"en\": \"In store\"}', 'in_stock')",
                tenant,
                state,
            )
            await conn.execute(
                "INSERT INTO assets (tenant_id, id, name, product_id, product_type_id, state_id,"
                " cost_centre) VALUES ($1, $2, 'Laptop 1', $3, $4, $5, $6)",
                tenant,
                asset,
                product,
                kind,
                state,
                None if cost else "CC-10",
            )
            if cost:
                await conn.execute(
                    "INSERT INTO asset_costs (tenant_id, id, asset_id, kind, incurred_on, amount)"
                    " VALUES ($1, $2, $3, 'service', current_date, 200)",
                    tenant,
                    uuid.uuid4(),
                    asset,
                )
    finally:
        await conn.close()


def test_0131_upgrades_downgrades_and_refuses_while_a_tenant_keeps_money_data(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert "'asset'" not in asyncio.run(_shape(database.admin_url))[2]
        db_testing.migrate(database.migrator_url, "0131")
        tables, columns, check = asyncio.run(_shape(database.admin_url))
        assert (tables, columns) == (len(NEW), 5)
        assert "'asset'" in check
        db_testing.downgrade(database.migrator_url, BEFORE)
        tables, columns, check = asyncio.run(_shape(database.admin_url))
        assert (tables, columns) == (0, 0)
        assert "'asset_disposal'" in check
        assert "'asset'" not in check.replace("'asset_disposal'", "")
        db_testing.migrate(database.migrator_url, "0131")
        # A cost centre typed on one tenant's asset is kept: the downgrade refuses.
        asyncio.run(_tenant_with_an_asset(database.admin_url, cost=False))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        # As is a cost line on another tenant's.
        asyncio.run(_tenant_with_an_asset(database.admin_url, cost=True))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_shape(database.admin_url))[:2] == (len(NEW), 5)
    finally:
        db_testing.destroy(db_config, database)
