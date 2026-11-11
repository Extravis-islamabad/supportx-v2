"""Recording the sign-in key ring at start-up (D-162, ADR-048; migration 0146).

Its own throwaway database: the shared one is started by many apps whose rings would otherwise
retire each other's keys. Two "replicas" are two Database objects with their own connections,
started at once with asyncio.gather.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
import pytest_asyncio

from app.core.database import Database, create_engine
from app.modules.identity_access.service.session_keys import (
    RETIRED,
    RING,
    ROTATED,
    sync_session_keys,
)
from app.shared.crypto import KeyStillInUseError, register_key_user, unregister_key_user
from conftest import create_tenant
from tooling import db_testing

pytestmark = [pytest.mark.db, pytest.mark.asyncio(loop_scope="module")]


@pytest.fixture(scope="module")
def ring_db(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    database = db_testing.create(db_config)
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def tenants(ring_db: db_testing.ThrowawayDatabase) -> tuple[uuid.UUID, uuid.UUID]:
    return (
        await create_tenant(ring_db.migrator_url, "Ring A"),
        await create_tenant(ring_db.migrator_url, "Ring B"),
    )


@pytest_asyncio.fixture(loop_scope="module")
async def replicas(ring_db: db_testing.ThrowawayDatabase) -> AsyncIterator[tuple[Database, ...]]:
    found = tuple(
        Database(
            create_engine(ring_db.app_url, application_name=f"replica-{n}", use_null_pool=True)
        )
        for n in (1, 2)
    )
    yield found
    for database in found:
        await database.dispose()


async def entries(
    db: db_testing.ThrowawayDatabase, tenant: uuid.UUID, action: str
) -> list[asyncpg.Record]:
    # Superuser: bypasses RLS, so the tenant is filtered explicitly.
    conn = await asyncpg.connect(db.admin_url)
    try:
        return await conn.fetch(
            "SELECT object_type, object_id, actor_type, actor_id, details FROM audit_entries"
            " WHERE tenant_id = $1 AND action = $2",
            tenant,
            action,
        )
    finally:
        await conn.close()


async def recorded(db: db_testing.ThrowawayDatabase) -> dict[str, bool]:
    conn = await asyncpg.connect(db.admin_url)
    try:
        rows = await conn.fetch("SELECT key_id, retired_at FROM session_key_ids")
    finally:
        await conn.close()
    return {row["key_id"]: row["retired_at"] is not None for row in rows}


async def test_rotation_and_retirement_are_audited_once_across_replicas(
    ring_db: db_testing.ThrowawayDatabase,
    tenants: tuple[uuid.UUID, uuid.UUID],
    replicas: tuple[Database, Database],
) -> None:
    one, two = replicas
    # First start: the ring as it is, no rotation, no entry.
    first = await sync_session_keys(one, ["k1"])
    assert (first.rotated, first.retired) == ([], [])
    assert await recorded(ring_db) == {"k1": False}
    for tenant in tenants:
        assert await entries(ring_db, tenant, ROTATED) == []

    # A new newest key, two replicas starting at once: exactly one writes the entry.
    results = await asyncio.gather(
        sync_session_keys(one, ["k2", "k1"]), sync_session_keys(two, ["k2", "k1"])
    )
    assert sorted(k for r in results for k in r.rotated) == ["k2"]
    assert await recorded(ring_db) == {"k1": False, "k2": False}
    for tenant in tenants:
        found = await entries(ring_db, tenant, ROTATED)
        assert len(found) == 1
        entry = found[0]
        assert (entry["object_type"], entry["object_id"]) == ("session_key", "k2")
        assert (entry["actor_type"], entry["actor_id"]) == ("system", None)
        details = json.loads(entry["details"])
        assert details == {"key_id": "k2", "previous_key_id": "k1", "readable_keys": 2}

    # Again with the same ring: nothing new.
    again = await sync_session_keys(two, ["k2", "k1"])
    assert (again.rotated, again.retired) == ([], [])

    # The old key leaves the ring: exactly one retired entry.
    results = await asyncio.gather(sync_session_keys(one, ["k2"]), sync_session_keys(two, ["k2"]))
    assert sorted(k for r in results for k in r.retired) == ["k1"]
    assert await recorded(ring_db) == {"k1": True, "k2": False}
    for tenant in tenants:
        retired = await entries(ring_db, tenant, RETIRED)
        assert len(retired) == 1
        assert retired[0]["object_id"] == "k1"
        assert len(await entries(ring_db, tenant, ROTATED)) == 1


async def test_a_removed_key_still_in_use_refuses_to_start(
    ring_db: db_testing.ThrowawayDatabase,
    tenants: tuple[uuid.UUID, uuid.UUID],
    replicas: tuple[Database, Database],
) -> None:
    del tenants
    one, _ = replicas
    await sync_session_keys(one, ["k2"])  # whatever the previous test left, k2 is recorded

    async def fake_fields(key_id: str) -> int:
        return 4 if key_id == "k2" else 0

    register_key_user(RING, "fake_fields", fake_fields)
    try:
        with pytest.raises(KeyStillInUseError) as refused:
            await sync_session_keys(one, ["k3"])
        assert refused.value.code == "session_key_still_in_use"
        assert refused.value.key_id == "k2"
        assert "k3" not in await recorded(ring_db)  # refused before recording anything
        await sync_session_keys(one, ["k3", "k2"])  # listed again: starts
    finally:
        unregister_key_user(RING, "fake_fields")
    # With no registered user, dropping it never refuses.
    await sync_session_keys(one, ["k3"])
    assert (await recorded(ring_db))["k2"] is True


async def test_the_app_role_can_never_delete_a_recorded_key(
    ring_db: db_testing.ThrowawayDatabase, replicas: tuple[Database, Database]
) -> None:
    await sync_session_keys(replicas[0], ["k3"])
    conn = await asyncpg.connect(ring_db.app_url)
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM session_key_ids")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("TRUNCATE session_key_ids")
        # Readable from any tenant context or none: it is the installation's, not a tenant's.
        assert await conn.fetchval("SELECT count(*) FROM session_key_ids") >= 1
    finally:
        await conn.close()
