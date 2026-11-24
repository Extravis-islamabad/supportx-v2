"""Migration 0192 (CI merges and imports) never loses data.

Up, down and up again while no tenant has a merge or an import; refused once one does, whichever
tenant it is in (rule 5h). The behaviour: tests/db/test_cmdb_merge_import.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0190"  # 0192's down revision (re-pointed with it at its queue turn)


async def _exists(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(
            await conn.fetchval(
                "SELECT to_regclass('cmdb_ci_aliases') IS NOT NULL"
                " AND to_regclass('cmdb_imports') IS NOT NULL"
            )
        )
    finally:
        await conn.close()


async def _tenants_one_with_an_import(url: str) -> None:
    """Three tenants, only the middle one with an import: the refusal finds it in any tenant."""
    conn = await asyncpg.connect(url)
    try:
        tenants = [uuid.uuid4() for _ in range(3)]
        for tenant in tenants:
            await conn.execute(
                "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Imports', $2)",
                tenant,
                f"t-{tenant.hex[:12]}",
            )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenants[1]))
            await conn.execute(
                "INSERT INTO cmdb_imports (id, tenant_id, kind, mode, match_on, file_name,"
                " file_format) VALUES ($1, $2, 'relationships', 'add', 'name', 'f.csv', 'csv')",
                uuid.uuid4(),
                tenants[1],
            )
    finally:
        await conn.close()


def test_0192_upgrades_downgrades_and_refuses_while_a_tenant_has_an_import(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        assert asyncio.run(_exists(database.admin_url)) is False
        db_testing.migrate(database.migrator_url, "0192")
        assert asyncio.run(_exists(database.admin_url)) is True
        db_testing.downgrade(database.migrator_url, BEFORE)  # empty: allowed
        assert asyncio.run(_exists(database.admin_url)) is False
        db_testing.migrate(database.migrator_url, "0192")
        asyncio.run(_tenants_one_with_an_import(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_exists(database.admin_url)) is True
    finally:
        db_testing.destroy(db_config, database)
