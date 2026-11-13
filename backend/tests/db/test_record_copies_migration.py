"""Migration 0156 (copying a record; WP-046a S5c) never loses data (rule 5h).

Up, down and up again while no tenant uses it. Once a tenant holds a copied file, or has
changed its copy limit, the downgrade is refused and both stay: the old source rule cannot hold
a copy, and relabelling it as an upload would misstate where it came from. The behaviour:
tests/db/test_record_copies_api.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0153"  # 0156's down revision while building (re-pointed at its queue turn)


async def _copy_limit_column(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'work_item_type_settings' AND column_name = 'copy_limit'"
            )
        )
    finally:
        await conn.close()


async def _tenant(conn: asyncpg.Connection) -> uuid.UUID:
    tenant = uuid.uuid4()
    await conn.execute(
        "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Copies', $2)",
        tenant,
        f"t-{tenant.hex[:12]}",
    )
    return tenant


async def _tenant_with_a_copied_file(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = await _tenant(conn)
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            file_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO files (id, tenant_id, name, size, sha256, content_type, kind, state,"
                " data_key_id, object_key, stored_size, source)"
                " VALUES ($1, $2, 'a.txt', 1, $3, 'text/plain', 'other', 'clean', $4, $5, 1,"
                " 'copy')",
                file_id,
                tenant,
                bytes(32),
                uuid.uuid4(),
                f"{tenant}/{file_id}",
            )
    finally:
        await conn.close()


async def _tenant_with_a_copy_limit(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = await _tenant(conn)
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO work_item_type_settings (tenant_id, type, prefix, default_priority,"
                " copy_limit) VALUES ($1, 'incident', 'INC', 'p3', 5)",
                tenant,
            )
    finally:
        await conn.close()


async def _forget_tenants(url: str) -> None:
    """Remove only the rows this test made (its own throwaway database)."""
    conn = await asyncpg.connect(url)
    try:
        for tenant in await conn.fetch("SELECT id FROM tenants WHERE name = 'Copies'"):
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant["id"])
                )
                await conn.execute("DELETE FROM files WHERE tenant_id = $1", tenant["id"])
                await conn.execute(
                    "DELETE FROM work_item_type_settings WHERE tenant_id = $1", tenant["id"]
                )
    finally:
        await conn.close()


def test_0156_upgrades_downgrades_and_refuses_while_a_tenant_keeps_a_copy(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0156")
        assert asyncio.run(_copy_limit_column(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_copy_limit_column(database.admin_url))
        db_testing.migrate(database.migrator_url, "0156")
        asyncio.run(_tenant_with_a_copied_file(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_copy_limit_column(database.admin_url))
        asyncio.run(_forget_tenants(database.admin_url))
        asyncio.run(_tenant_with_a_copy_limit(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_copy_limit_column(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
