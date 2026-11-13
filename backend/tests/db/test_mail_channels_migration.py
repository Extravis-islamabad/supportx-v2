"""Migration 0159 (mail channels; WP-046a S6) never loses data (rule 5h).

Up, down and up again while no tenant uses it. Once a tenant has a block rule, or a mailbox
trusts a server, the downgrade is refused and both stay. The behaviour:
tests/db/test_mail_channels_api.py.
"""

import asyncio
import uuid

import asyncpg
import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0156"  # 0159's down revision while building (re-pointed at its queue turn)


async def _has_rules_table(url: str) -> bool:
    conn = await asyncpg.connect(url)
    try:
        return bool(await conn.fetchval("SELECT to_regclass('mail_block_rules') IS NOT NULL"))
    finally:
        await conn.close()


async def _tenant(conn: asyncpg.Connection) -> uuid.UUID:
    tenant = uuid.uuid4()
    await conn.execute(
        "INSERT INTO tenants (id, name, slug) VALUES ($1, 'Mail channels', $2)",
        tenant,
        f"t-{tenant.hex[:12]}",
    )
    return tenant


async def _with_a_block_rule(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = await _tenant(conn)
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO mail_block_rules (id, tenant_id, kind, value)"
                " VALUES ($1, $2, 'domain', 'spam.test')",
                uuid.uuid4(),
                tenant,
            )
    finally:
        await conn.close()


async def _forget(url: str) -> None:
    """Remove only the rows this test made (its own throwaway database)."""
    conn = await asyncpg.connect(url)
    try:
        for row in await conn.fetch("SELECT id FROM tenants WHERE name = 'Mail channels'"):
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(row["id"]))
                await conn.execute("DELETE FROM mail_block_rules WHERE tenant_id = $1", row["id"])
                await conn.execute("DELETE FROM mailboxes WHERE tenant_id = $1", row["id"])
    finally:
        await conn.close()


async def _with_a_trusted_server(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        tenant = await _tenant(conn)
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO mailboxes (id, tenant_id, address, protocol, host, port, username,"
                " trusted_servers) VALUES ($1, $2, 'help@acme.test', 'imap', 'imap.acme.test',"
                " 993, 'help', '{mx.acme.test}')",
                uuid.uuid4(),
                tenant,
            )
    finally:
        await conn.close()


def test_0159_upgrades_downgrades_and_refuses_while_a_tenant_uses_it(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        db_testing.migrate(database.migrator_url, "0159")
        assert asyncio.run(_has_rules_table(database.admin_url))
        db_testing.downgrade(database.migrator_url, BEFORE)
        assert not asyncio.run(_has_rules_table(database.admin_url))
        db_testing.migrate(database.migrator_url, "0159")
        asyncio.run(_with_a_block_rule(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_rules_table(database.admin_url))
        asyncio.run(_forget(database.admin_url))
        asyncio.run(_with_a_trusted_server(database.admin_url))
        with pytest.raises(Exception, match="downgrade refused"):
            db_testing.downgrade(database.migrator_url, BEFORE)
        assert asyncio.run(_has_rules_table(database.admin_url))
    finally:
        db_testing.destroy(db_config, database)
