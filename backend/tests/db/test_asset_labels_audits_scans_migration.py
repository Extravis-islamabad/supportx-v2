"""Migration 0134 (labels, audits, scans, the overdue rule; WP-049b s3) never loses data.

Up, down and up again while no tenant uses it; once one tenant keeps a scan, or an asset with a
last scan time, the downgrade is refused and every new table and column stays (rule 5h).
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0133"  # 0134's down revision
NEW = (
    "asset_label_jobs",
    "asset_label_prints",
    "asset_audits",
    "asset_audit_auditors",
    "asset_audit_items",
    "asset_scans",
    "asset_overdue_rules",
    "asset_overdue_runs",
)


async def _shape(url: str) -> tuple[int, int, int]:
    """(new tables, new columns on assets and acknowledgements, the change index)."""
    conn = await asyncpg.connect(url)
    try:
        tables = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ANY($1)", list(NEW)
        )
        columns = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE"
            " (table_name = 'assets' AND column_name = 'last_scanned_at')"
            " OR (table_name = 'asset_acknowledgements' AND column_name = 'audit_id')"
        )
        index = await conn.fetchval(
            "SELECT count(*) FROM pg_indexes WHERE indexname = 'ix_field_changes_change'"
        )
        return int(tables), int(columns), int(index)
    finally:
        await conn.close()


async def _tenant_with_a_scan(url: str, *, scan: bool) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant, kind, product, state, asset = (uuid.uuid4() for _ in range(5))
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Scans', $2)",
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
                "INSERT INTO assets (tenant_id, id, name, product_id, product_type_id, state_id)"
                " VALUES ($1, $2, 'Laptop 1', $3, $4, $5)",
                tenant,
                asset,
                product,
                kind,
                state,
            )
            if scan:
                await conn.execute(
                    "INSERT INTO asset_scans (tenant_id, id, asset_id, scanned_at, source, result)"
                    " VALUES ($1, $2, $3, now(), 'agent', 'ok')",
                    tenant,
                    uuid.uuid4(),
                    asset,
                )
            else:
                await conn.execute("UPDATE assets SET last_scanned_at = now() WHERE id = $1", asset)
    finally:
        await conn.close()


def test_0134_upgrades_downgrades_and_refuses_while_a_tenant_keeps_scan_data(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_shape(database.admin_url))[:2] == (0, 0)
        db_testing.migrate(database.migrator_url, "0134")
        assert asyncio.run(_shape(database.admin_url))[:2] == (len(NEW), 2)
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_shape(database.admin_url))[:2] == (0, 0)
        db_testing.migrate(database.migrator_url, "0134")
        # One tenant's asset with a last scan time is kept: the downgrade refuses.
        asyncio.run(_tenant_with_a_scan(database.admin_url, scan=False))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        # As is another tenant's scan history.
        asyncio.run(_tenant_with_a_scan(database.admin_url, scan=True))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_shape(database.admin_url))[:2] == (len(NEW), 2)
    finally:
        db_testing.destroy(db_config, database)
