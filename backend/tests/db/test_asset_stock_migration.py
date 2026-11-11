"""Migration 0130 (stock, minimum stock, bookings; WP-049b s1) never loses data (rule 5h).

Up, down and up again while no tenant uses it; once one tenant keeps a consumable, the
downgrade is refused and every new table stays.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0129"  # 0130's down revision
NEW = (
    "asset_bookings",
    "asset_stock_rules",
    "asset_consumable_movements",
    "asset_consumable_batches",
    "asset_consumable_stocks",
    "asset_consumables",
)


async def _tables(url: str) -> int:
    conn = await asyncpg.connect(url)
    try:
        return int(
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ANY($1)",
                list(NEW),
            )
        )
    finally:
        await conn.close()


async def _tenant_with_a_consumable(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant, kind, product = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Stock', $2)",
            tenant,
            f"t-{tenant.hex[:12]}",
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO asset_product_types (tenant_id, id, api_name, names, category, kind)"
                " VALUES ($1, $2, 'toner', '{\"en\": \"Toner\"}', 'non_it', 'consumable')",
                tenant,
                kind,
            )
            await conn.execute(
                "INSERT INTO asset_products (tenant_id, id, product_type_id, name)"
                " VALUES ($1, $2, $3, 'Toner 26A')",
                tenant,
                product,
                kind,
            )
            await conn.execute(
                "INSERT INTO asset_consumables (tenant_id, id, product_id, batch_tracked)"
                " VALUES ($1, $2, $3, false)",
                tenant,
                uuid.uuid4(),
                product,
            )
    finally:
        await conn.close()


def test_0130_upgrades_downgrades_and_refuses_while_a_tenant_keeps_stock(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0130")
        assert asyncio.run(_tables(database.admin_url)) == len(NEW)
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_tables(database.admin_url)) == 0
        db_testing.migrate(database.migrator_url, "0130")
        asyncio.run(_tenant_with_a_consumable(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_tables(database.admin_url)) == len(NEW)
    finally:
        db_testing.destroy(db_config, database)
