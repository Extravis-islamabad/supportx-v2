"""Migration 0136 (declining balance's factor per product type, D-157) never loses data (rule 5h).

Up, down and up again while every type keeps the default factor; once one tenant's type has its
own, the downgrade is refused and the column stays. Existing types get 2; the check holds 0..10.
"""

import asyncio
import uuid
from decimal import Decimal

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

REVISION = "0136"
BEFORE = "0132"  # 0136's down revision


async def _columns(url: str) -> int:
    conn = await asyncpg.connect(url)
    try:
        found = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'asset_product_types' AND column_name = 'depreciation_factor'"
        )
        return int(found)
    finally:
        await conn.close()


async def _tenant_with_a_type(url: str) -> tuple[uuid.UUID, uuid.UUID]:
    conn = await asyncpg.connect(url)
    try:
        tenant, kind = uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Factor', $2)",
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
        return tenant, kind
    finally:
        await conn.close()


async def _factor(url: str, tenant: uuid.UUID, kind: uuid.UUID, value: str | None) -> Decimal:
    """Set the type's factor (None: leave it) and read it back, with the tenant's RLS set."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            if value is not None:
                await conn.execute(
                    "UPDATE asset_product_types SET depreciation_factor = $1 WHERE id = $2",
                    Decimal(value),
                    kind,
                )
            found: Decimal = await conn.fetchval(
                "SELECT depreciation_factor FROM asset_product_types WHERE id = $1", kind
            )
            return found
    finally:
        await conn.close()


def test_0136_upgrades_downgrades_and_refuses_while_a_type_has_its_own_factor(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        tenant, kind = asyncio.run(_tenant_with_a_type(database.admin_url))
        assert asyncio.run(_columns(database.admin_url)) == 0
        db_testing.migrate(database.migrator_url, REVISION)
        assert asyncio.run(_factor(database.admin_url, tenant, kind, None)) == Decimal(2)
        for wrong in ("0", "10.5", "-1"):
            with pytest.raises(asyncpg.CheckViolationError):
                asyncio.run(_factor(database.admin_url, tenant, kind, wrong))
        # Every type at the default: down and up again, nothing lost.
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_columns(database.admin_url)) == 0
        db_testing.migrate(database.migrator_url, REVISION)
        # One type with its own factor: the downgrade refuses and keeps it.
        assert asyncio.run(_factor(database.admin_url, tenant, kind, "1.5")) == Decimal("1.5")
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_columns(database.admin_url)) == 1
        assert asyncio.run(_factor(database.admin_url, tenant, kind, None)) == Decimal("1.5")
    finally:
        db_testing.destroy(db_config, database)
