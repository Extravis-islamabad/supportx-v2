"""Relay housekeeping: expired idempotency keys and old consumer records (WP-012, migration 0010).

The database decides what the relay may see and delete there (role-scoped RLS policies whose
rule is the age limit); the relay's retention setting can only narrow it further.
"""

import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from conftest import create_tenant
from tests.events.conftest import RelayFactory
from tooling import db_testing

pytestmark = pytest.mark.db

NOW = datetime.now(UTC)


async def seed(db: db_testing.ThrowawayDatabase) -> uuid.UUID:
    """One tenant with keys and consumer records of several ages; returns the tenant."""
    tenant = await create_tenant(db.migrator_url, "Housekeeping")
    conn = await asyncpg.connect(db.admin_url)
    try:
        for key, expires in (
            ("expired", NOW - timedelta(minutes=1)),
            ("valid", NOW + timedelta(hours=1)),
        ):
            await conn.execute(
                "INSERT INTO idempotency_keys (tenant_id, user_id, key, route, fingerprint,"
                " created_at, expires_at) VALUES ($1, $2, $3, 'POST /x', 'f', $4, $5)",
                tenant,
                uuid.uuid4(),
                key,
                expires - timedelta(hours=24),
                expires,
            )
        for consumer, age in (("old", 40), ("week", 8), ("young", 3)):
            await conn.execute(
                "INSERT INTO processed_events (tenant_id, consumer, event_id, created_at)"
                " VALUES ($1, $2, $3, $4)",
                tenant,
                consumer,
                uuid.uuid4(),
                NOW - timedelta(days=age),
            )
    finally:
        await conn.close()
    return tenant


async def remaining(
    db: db_testing.ThrowawayDatabase, tenant: uuid.UUID
) -> tuple[set[str], set[str]]:
    conn = await asyncpg.connect(db.admin_url)
    try:
        keys = await conn.fetch("SELECT key FROM idempotency_keys WHERE tenant_id = $1", tenant)
        consumers = await conn.fetch(
            "SELECT consumer FROM processed_events WHERE tenant_id = $1", tenant
        )
    finally:
        await conn.close()
    return {r["key"] for r in keys}, {r["consumer"] for r in consumers}


async def test_the_database_lets_the_relay_touch_only_expired_rows(
    migrated_db: db_testing.ThrowawayDatabase,
) -> None:
    tenant = await seed(migrated_db)
    relay = await asyncpg.connect(migrated_db.relay_url)
    try:
        keys = await relay.fetch("SELECT key FROM idempotency_keys WHERE tenant_id = $1", tenant)
        assert {r["key"] for r in keys} == {"expired"}
        # Even an unconditional delete only reaches what the policy shows.
        await relay.execute("DELETE FROM idempotency_keys WHERE tenant_id = $1", tenant)
        await relay.execute("DELETE FROM processed_events WHERE tenant_id = $1", tenant)
        # And it can never change or add rows there.
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await relay.execute("UPDATE processed_events SET consumer = 'x'")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await relay.execute(
                "INSERT INTO processed_events (tenant_id, consumer, event_id) VALUES ($1, 'x', $2)",
                tenant,
                uuid.uuid4(),
            )
    finally:
        await relay.close()
    assert await remaining(migrated_db, tenant) == ({"valid"}, {"young"})


@pytest.mark.nats
async def test_relay_purges_with_its_retention_above_the_floor(
    migrated_db: db_testing.ThrowawayDatabase, make_relay: RelayFactory
) -> None:
    tenant = await seed(migrated_db)
    # 30 days: only the 40-day-old record goes. Then 1 day: the database floor (7) still holds.
    relay = make_relay(processed_retention=timedelta(days=30))
    await relay.connect()
    try:
        first = await relay.purge_housekeeping()
        assert first["idempotency_keys"] >= 1
        assert await remaining(migrated_db, tenant) == ({"valid"}, {"week", "young"})
        relay.processed_retention = timedelta(days=1)
        await relay.purge_housekeeping()
    finally:
        await relay.close()
    assert await remaining(migrated_db, tenant) == ({"valid"}, {"young"})
