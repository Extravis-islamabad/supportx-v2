"""Migration 0045: mailbox secrets copied into the secrets store, and back (WP-040, D-113).

Seeds two tenants' mailboxes at 0043 (one with a password, one with an OAuth credential and a
refresh token, one removed), migrates, checks every live secret was copied as the same sealed
bytes into its own tenant and opens with the store's purpose, then downgrades and checks the
mailboxes are exactly as before. Nothing is unsealed by the migration itself.
"""

import asyncio
import uuid

import asyncpg
import pytest

from app.shared.files.keyring import KeyRing
from conftest import create_tenant
from tooling import db_testing

pytestmark = pytest.mark.db

RING = KeyRing.parse(KeyRing.generate())


async def _seed(admin_url: str, tenant: uuid.UUID) -> dict[str, uuid.UUID]:
    conn = await asyncpg.connect(admin_url)
    try:
        imap, api, gone = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        key, sealed = RING.seal(tenant, "mailbox", b"imap-pass")
        await conn.execute(
            "INSERT INTO mailboxes (id, tenant_id, address, host, port, username,"
            " secret_key_id, secret_sealed) VALUES ($1, $2, $3, 'imap.test', 993, 'it', $4, $5)",
            imap,
            tenant,
            f"it-{tenant.hex[:6]}@test",
            key,
            sealed,
        )
        ckey, csealed = RING.seal(tenant, "mailbox", b"app-secret")
        tkey, tsealed = RING.seal(tenant, "mailbox_token", b"refresh-1")
        await conn.execute(
            "INSERT INTO mailboxes (id, tenant_id, address, protocol, auth_model, client_id,"
            " credential_kind, secret_key_id, secret_sealed, token_key_id, token_sealed)"
            " VALUES ($1, $2, $3, 'graph', 'delegated', 'app', 'secret', $4, $5, $6, $7)",
            api,
            tenant,
            f"help-{tenant.hex[:6]}@test",
            ckey,
            csealed,
            tkey,
            tsealed,
        )
        gkey, gsealed = RING.seal(tenant, "mailbox", b"old-pass")
        await conn.execute(
            "INSERT INTO mailboxes (id, tenant_id, address, host, port, username,"
            " secret_key_id, secret_sealed, deleted_at)"
            " VALUES ($1, $2, $3, 'imap.test', 993, 'old', $4, $5, now())",
            gone,
            tenant,
            f"old-{tenant.hex[:6]}@test",
            gkey,
            gsealed,
        )
        return {"imap": imap, "api": api, "gone": gone}
    finally:
        await conn.close()


async def _mailboxes(admin_url: str) -> list[tuple[object, ...]]:
    conn = await asyncpg.connect(admin_url)
    try:
        rows = await conn.fetch(
            "SELECT id, secret_key_id, secret_sealed, token_key_id, token_sealed FROM mailboxes"
            " ORDER BY id"
        )
        return [tuple(r) for r in rows]
    finally:
        await conn.close()


async def _store(admin_url: str) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(admin_url)
    try:
        return list(
            await conn.fetch(
                "SELECT s.*, m.secret_ref, m.token_ref, m.secret_sealed AS old_secret,"
                " m.token_sealed AS old_token, m.tenant_id AS mailbox_tenant"
                " FROM connector_secrets s JOIN mailboxes m ON m.id = s.owner_id"
            )
        )
    finally:
        await conn.close()


async def _table_exists(admin_url: str) -> bool:
    conn = await asyncpg.connect(admin_url)
    try:
        return bool(await conn.fetchval("SELECT to_regclass('connector_secrets') IS NOT NULL"))
    finally:
        await conn.close()


def test_mailbox_secrets_are_copied_sealed_and_the_downgrade_loses_nothing(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config, migrate_to="0043")
    try:
        a = asyncio.run(create_tenant(database.migrator_url))
        b = asyncio.run(create_tenant(database.migrator_url))
        seeded = {
            a: asyncio.run(_seed(database.admin_url, a)),
            b: asyncio.run(_seed(database.admin_url, b)),
        }
        before = asyncio.run(_mailboxes(database.admin_url))
        db_testing.migrate(database.migrator_url, "0045")

        rows = asyncio.run(_store(database.admin_url))
        assert len(rows) == 6  # per tenant: the password, the app secret, the refresh token
        for row in rows:
            assert row["tenant_id"] == row["mailbox_tenant"]  # each in its own tenant
            assert row["owner_id"] != seeded[row["tenant_id"]]["gone"]  # removed: not copied
            if row["role"] == "credential":
                assert row["secret_ref"] == row["id"]
                assert bytes(row["sealed"]) == bytes(row["old_secret"])
            else:
                assert row["token_ref"] == row["id"]
                assert bytes(row["sealed"]) == bytes(row["old_token"])
            opened = RING.unseal(
                row["tenant_id"], row["purpose"], row["key_id"], bytes(row["sealed"])
            )
            expected = {"password": b"imap-pass", "client_secret": b"app-secret"}
            assert opened == expected.get(row["secret_type"], b"refresh-1")

        db_testing.downgrade(database.migrator_url, "0043")
        assert not asyncio.run(_table_exists(database.admin_url))
        assert asyncio.run(_mailboxes(database.admin_url)) == before
    finally:
        db_testing.destroy(db_config, database)
