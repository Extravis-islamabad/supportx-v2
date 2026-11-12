"""Recording the sign-in key ring at start-up (D-162, ADR-048; migration 0146).

Its own throwaway database: the shared one is started by many apps whose rings would otherwise
retire each other's keys. Two "replicas" are two Database objects with their own connections,
started at once with asyncio.gather.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from app.core.database import SESSION_TENANT_KEY, Database, create_engine
from app.modules.audit import record
from app.modules.identity_access.service.session_keys import (
    RETIRED,
    RING,
    ROTATED,
    announce_pending,
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


async def listed(db: db_testing.ThrowawayDatabase) -> list[str]:
    """The recorded keys still in use, so a test can add one without retiring the others."""
    return [key for key, retired in (await recorded(db)).items() if not retired]


async def recorded(db: db_testing.ThrowawayDatabase) -> dict[str, bool]:
    conn = await asyncpg.connect(db.admin_url)
    try:
        rows = await conn.fetch("SELECT key_id, retired_at FROM session_key_ids")
    finally:
        await conn.close()
    return {row["key_id"]: row["retired_at"] is not None for row in rows}


async def test_rotation_and_retirement_are_claimed_once_and_announced_once_per_tenant(
    ring_db: db_testing.ThrowawayDatabase,
    tenants: tuple[uuid.UUID, uuid.UUID],
    replicas: tuple[Database, Database],
) -> None:
    one, two = replicas
    # First start: the ring as it is, no rotation, nothing to announce.
    first = await sync_session_keys(one, ["k1"])
    assert (first.rotated, first.retired) == ([], [])
    assert await recorded(ring_db) == {"k1": False}
    assert await announce_pending(one) == 0

    # A new newest key, two replicas starting at once: exactly one claims it.
    results = await asyncio.gather(
        sync_session_keys(one, ["k2", "k1"]), sync_session_keys(two, ["k2", "k1"])
    )
    assert sorted(k for r in results for k in r.rotated) == ["k2"]
    assert await recorded(ring_db) == {"k1": False, "k2": False}
    # Start-up writes no tenant entry: that is the announcer's job.
    for tenant in tenants:
        assert await entries(ring_db, tenant, ROTATED) == []
    # A tenant created after the change is not told about it.
    later = await create_tenant(ring_db.migrator_url, "Ring later")

    # Two announcer runs at once: one entry per tenant.
    written = await asyncio.gather(announce_pending(one), announce_pending(two))
    assert sum(written) == len(tenants)
    for tenant in tenants:
        found = await entries(ring_db, tenant, ROTATED)
        assert len(found) == 1
        entry = found[0]
        assert (entry["object_type"], entry["object_id"]) == ("session_key", "k2")
        assert (entry["actor_type"], entry["actor_id"]) == ("system", None)
        details = json.loads(entry["details"])
        assert details == {"key_id": "k2", "previous_key_id": "k1", "readable_keys": 2}
    assert await entries(ring_db, later, ROTATED) == []
    assert await announce_pending(one) == 0  # announced: nothing pending

    # Again with the same ring: nothing new.
    again = await sync_session_keys(two, ["k2", "k1"])
    assert (again.rotated, again.retired) == ([], [])

    # The old key leaves the ring: exactly one retired entry per tenant.
    results = await asyncio.gather(sync_session_keys(one, ["k2"]), sync_session_keys(two, ["k2"]))
    assert sorted(k for r in results for k in r.retired) == ["k1"]
    assert await recorded(ring_db) == {"k1": True, "k2": False}
    await asyncio.gather(announce_pending(one), announce_pending(two))
    for tenant in tenants:
        retired = await entries(ring_db, tenant, RETIRED)
        assert len(retired) == 1
        assert retired[0]["object_id"] == "k1"
        assert json.loads(retired[0]["details"]) == {"key_id": "k1", "readable_keys": 1}
        assert len(await entries(ring_db, tenant, ROTATED)) == 1


async def test_a_crash_half_way_neither_loses_nor_repeats_an_entry(
    ring_db: db_testing.ThrowawayDatabase,
    tenants: tuple[uuid.UUID, uuid.UUID],
    replicas: tuple[Database, Database],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    one, _ = replicas
    await sync_session_keys(one, ["k1"])  # baseline, if this test runs alone
    await announce_pending(one)
    await sync_session_keys(one, ["k9", *(await listed(ring_db))])
    first, second = tenants
    target = "app.modules.identity_access.service.session_keys.record"

    async def crash_for_second(session: Any, **values: Any) -> uuid.UUID:  # noqa: ANN401 - record()'s
        if session.info[SESSION_TENANT_KEY].tenant_id == second:
            msg = "the worker died"
            raise RuntimeError(msg)
        return await record(session, **values)

    monkeypatch.setattr(target, crash_for_second)
    # One tenant failing never holds back another (lane A's #418 review): the first still gets
    # its entry, the failure is logged, and the change stays pending for the next run.
    await announce_pending(one)
    k9 = [e for e in await entries(ring_db, first, ROTATED) if e["object_id"] == "k9"]
    assert len(k9) == 1
    assert [e for e in await entries(ring_db, second, ROTATED) if e["object_id"] == "k9"] == []
    assert await pending_events(ring_db, "k9") == 1
    monkeypatch.setattr(target, record)
    await announce_pending(one)
    for tenant in (first, second):
        found = [e for e in await entries(ring_db, tenant, ROTATED) if e["object_id"] == "k9"]
        assert len(found) == 1, tenant
    assert await pending_events(ring_db, "k9") == 0


async def pending_events(db: db_testing.ThrowawayDatabase, key_id: str) -> int:
    conn = await asyncpg.connect(db.admin_url)
    try:
        found = await conn.fetchval(
            "SELECT count(*) FROM session_key_events WHERE key_id = $1 AND announced_at IS NULL",
            key_id,
        )
    finally:
        await conn.close()
    return int(found)


@pytest.mark.parametrize(
    ("key_id", "previous", "readable"),
    [
        ("Free text!", None, 1),  # not a key ID
        ("k1", "<b>hi</b>", 1),  # nor is the previous one
        ("k1", None, 1000),  # a count out of range
    ],
)
async def test_an_event_can_only_carry_key_ids_and_a_small_count(
    ring_db: db_testing.ThrowawayDatabase, key_id: str, previous: str | None, readable: int
) -> None:
    """The announcer copies events into every tenant's log: the database keeps them to key-ID
    shape, so even the app role's own INSERT can never carry free text there (lane A, #418)."""
    conn = await asyncpg.connect(ring_db.app_url)
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO session_key_events (id, key_id, action, previous_key_id,"
                " readable_keys, occurred_at) VALUES ($1, $2, 'security.session_key_rotated',"
                " $3, $4, now())",
                uuid.uuid4(),
                key_id,
                previous,
                readable,
            )
    finally:
        await conn.close()


async def _insert_as(
    conn: asyncpg.Connection, acting: uuid.UUID, owner: uuid.UUID, event: uuid.UUID
) -> None:
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(acting))
        await conn.execute(
            "INSERT INTO session_key_announcements (tenant_id, event_id, key_id, action)"
            " VALUES ($1, $2, 'kx', 'security.session_key_rotated')",
            owner,
            event,
        )


async def test_announcements_are_isolated_per_tenant(
    ring_db: db_testing.ThrowawayDatabase, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    first, second = tenants
    conn = await asyncpg.connect(ring_db.app_url)
    try:
        event = await conn.fetchval("SELECT id FROM session_key_events LIMIT 1")
        assert event is not None  # the tests above announced to both tenants
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(first))
            seen = await conn.fetch("SELECT tenant_id FROM session_key_announcements")
            assert seen
            assert {row["tenant_id"] for row in seen} == {first}
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await _insert_as(conn, first, second, event)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM session_key_announcements")
        # Without a tenant, nothing is visible.
        assert await conn.fetchval("SELECT count(*) FROM session_key_announcements") == 0
    finally:
        await conn.close()


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
