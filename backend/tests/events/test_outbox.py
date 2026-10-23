"""The outbox writer and the database rights around it (CLAUDE.md rules a and b; WP-007).

Runs as supportx_app through PgBouncer (like the API) and as supportx_relay directly (like the
relay). Needs PostgreSQL only.
"""

import asyncio
import json
import uuid

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.database import Database, TenantContextMissingError
from app.core.errors import NotFound
from app.core.tenancy import TenantContext
from app.shared.events import DomainEvent, UnregisteredEventError, record_event
from app.shared.events.envelope import Actor
from tests.db.probe import ProbeItem, ProbeRepository
from tests.events.conftest import emit, outbox_rows
from tests.events.sample import ProbeHappened
from tooling import db_testing, rls_guard

pytestmark = pytest.mark.db


class Rollback(Exception):
    pass


async def test_business_row_and_event_commit_together(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    tenant: uuid.UUID,
    clean_outbox: None,
) -> None:
    del clean_outbox
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        item = await ProbeRepository(session).add(ProbeItem(title="committed"))
        envelope = await record_event(
            session, ProbeHappened(note="committed"), aggregate_id=item.id, aggregate_version=1
        )

    rows = await outbox_rows(migrated_db.admin_url)
    assert [row["id"] for row in rows] == [envelope.event_id]
    stored = json.loads(rows[0]["envelope"])
    assert stored["event_type"] == "probe.item.happened"
    assert stored["tenant_id"] == str(tenant)
    assert stored["aggregate_id"] == str(item.id)
    assert stored["aggregate_version"] == 1
    assert stored["payload"] == {"note": "committed"}
    assert stored["actor"] == {"type": "system", "id": "probe"}
    assert rows[0]["published_at"] is None
    assert envelope.event_id.version == 7
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        assert await ProbeRepository(session).get(item.id) is not None


async def test_rollback_leaves_neither_row_nor_event(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    tenant: uuid.UUID,
    clean_outbox: None,
) -> None:
    del clean_outbox
    created: list[uuid.UUID] = []

    async def change_then_fail() -> None:
        async with app_db.tenant_session(TenantContext(tenant)) as session:
            item = await ProbeRepository(session).add(ProbeItem(title="rolled back"))
            created.append(item.id)
            await record_event(session, ProbeHappened(note="rolled back"), aggregate_id=item.id)
            raise Rollback

    with pytest.raises(Rollback):
        await change_then_fail()
    assert await outbox_rows(migrated_db.admin_url) == []
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        with pytest.raises(NotFound):
            await ProbeRepository(session).get(created[0])


async def test_failed_commit_leaves_no_event(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    tenant: uuid.UUID,
    clean_outbox: None,
) -> None:
    """The event is written first, then the business write fails: the event goes too."""
    del clean_outbox

    async def event_then_bad_write() -> None:
        async with app_db.tenant_session(TenantContext(tenant)) as session:
            await record_event(session, ProbeHappened(note="x"), aggregate_id=uuid.uuid4())
            await session.execute(text("INSERT INTO probe_items (id) VALUES (NULL)"))

    with pytest.raises(DBAPIError):
        await event_then_bad_write()
    assert await outbox_rows(migrated_db.admin_url) == []


async def test_user_actor_comes_from_the_session(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    tenant: uuid.UUID,
    clean_outbox: None,
) -> None:
    del clean_outbox
    user = uuid.uuid4()
    async with app_db.tenant_session(TenantContext(tenant, user)) as session:
        envelope = await record_event(session, ProbeHappened(note="u"), aggregate_id="a1")
    assert envelope.actor == Actor.user(user)
    assert json.loads((await outbox_rows(migrated_db.admin_url))[0]["envelope"])["actor"] == {
        "type": "user",
        "id": str(user),
    }


async def test_unregistered_event_cannot_be_written(app_db: Database, tenant: uuid.UUID) -> None:
    class Sneaky(DomainEvent):
        event_type = "probe.item.sneaked"
        aggregate_type = "item"

    async with app_db.tenant_session(TenantContext(tenant)) as session:
        with pytest.raises(UnregisteredEventError):
            await record_event(session, Sneaky(), aggregate_id="x")


async def test_events_need_a_tenant_session(app_db: Database) -> None:
    async with app_db.platform_session() as session:
        with pytest.raises(TenantContextMissingError):
            await record_event(session, ProbeHappened(note="x"), aggregate_id="x")


# --- supportx_app rights -------------------------------------------------------------------------


async def test_app_role_cannot_read_change_or_delete_outbox_rows(
    app_db: Database, tenant: uuid.UUID
) -> None:
    await emit(app_db, tenant)
    for statement in (
        "SELECT * FROM outbox_events",
        "UPDATE outbox_events SET published_at = now()",
        "DELETE FROM outbox_events",
        "TRUNCATE outbox_events",
    ):
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with app_db.tenant_session(TenantContext(tenant)) as session:
                await session.execute(text(statement))


async def test_app_role_cannot_insert_for_another_tenant(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = tenant_pair
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with app_db.tenant_session(TenantContext(a)) as session:
            await session.execute(
                text(
                    "INSERT INTO outbox_events (id, tenant_id, event_type, schema_version,"
                    " aggregate_type, aggregate_id, envelope)"
                    " VALUES (:id, :tenant, 'probe.item.happened', 1, 'item', 'x', '{}')"
                ),
                {"id": uuid.uuid4(), "tenant": b},
            )


async def test_app_role_sees_only_its_tenant_in_processed_events(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = tenant_pair
    insert = text(
        "INSERT INTO processed_events (tenant_id, consumer, event_id) VALUES (:t, 'c', :e)"
    )
    async with app_db.tenant_session(TenantContext(a)) as session:
        await session.execute(insert, {"t": a, "e": uuid.uuid4()})
    async with app_db.tenant_session(TenantContext(b)) as session:
        assert (await session.execute(text("SELECT count(*) FROM processed_events"))).scalar() == 0
        with pytest.raises(ProgrammingError, match="row-level security"):
            await session.execute(insert, {"t": a, "e": uuid.uuid4()})


# --- supportx_relay rights -----------------------------------------------------------------------


async def test_relay_reads_every_tenant_and_marks_only_delivery_columns(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    tenant_pair: tuple[uuid.UUID, uuid.UUID],
    clean_outbox: None,
) -> None:
    del clean_outbox
    a, b = tenant_pair
    (event_a,) = await emit(app_db, a)
    (event_b,) = await emit(app_db, b)
    relay = await asyncpg.connect(migrated_db.relay_url)
    try:
        ids = await relay.fetch("SELECT id FROM outbox_events ORDER BY id")
        assert [r["id"] for r in ids] == [event_a.event_id, event_b.event_id]
        await relay.execute(
            "UPDATE outbox_events SET published_at = now() WHERE id = $1", event_a.event_id
        )
        for forbidden in (
            "UPDATE outbox_events SET envelope = '{}'",
            "UPDATE outbox_events SET tenant_id = gen_random_uuid()",
            "UPDATE outbox_events SET event_type = 'x.y.z'",
            "INSERT INTO outbox_events (id) VALUES (gen_random_uuid())",
            "TRUNCATE outbox_events",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await relay.execute(forbidden)
        # Purge rule enforced by the database: an unpublished row cannot be deleted.
        assert await relay.execute("DELETE FROM outbox_events WHERE id = $1", event_b.event_id) == (
            "DELETE 0"
        )
        assert await relay.execute("DELETE FROM outbox_events WHERE id = $1", event_a.event_id) == (
            "DELETE 1"
        )
    finally:
        await relay.close()


# processed_events and idempotency_keys are housekeeping tables the relay purges (WP-012): it may
# see and delete only expired rows there, tested in tests/events/test_housekeeping.py.
@pytest.mark.parametrize(
    "table", ["users", "tenants", "announcements", "display_id_sequences", "probe_items"]
)
async def test_relay_cannot_read_any_business_table(
    migrated_db: db_testing.ThrowawayDatabase, table: str
) -> None:
    relay = await asyncpg.connect(migrated_db.relay_url)
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await relay.fetch(f"SELECT * FROM {table} LIMIT 1")  # noqa: S608 - fixed test names
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await relay.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed test names
    finally:
        await relay.close()


async def test_relay_role_has_no_bypass_and_no_ownership(
    migrated_db: db_testing.ThrowawayDatabase,
) -> None:
    conn = await asyncpg.connect(migrated_db.admin_url)
    try:
        role = await conn.fetchrow(
            "SELECT rolsuper, rolbypassrls, rolinherit FROM pg_roles"
            " WHERE rolname = 'supportx_relay'"
        )
        owned = await conn.fetchval(
            "SELECT count(*) FROM pg_class WHERE relowner ="
            " (SELECT oid FROM pg_roles WHERE rolname = 'supportx_relay')"
        )
    finally:
        await conn.close()
    assert role is not None
    assert (role["rolsuper"], role["rolbypassrls"], role["rolinherit"]) == (False, False, False)
    assert owned == 0


def test_guard_fails_when_the_relay_gets_a_business_table(
    db_config: db_testing.DbTestConfig,
) -> None:
    """Mutation check: one stray GRANT to the relay and the RLS guard fails CI."""

    async def grant_and_inspect(database: db_testing.ThrowawayDatabase) -> list[str]:
        conn = await asyncpg.connect(database.migrator_url)
        try:
            await conn.execute("GRANT SELECT ON users TO supportx_relay")
            await conn.execute(
                "CREATE POLICY users_relay_all ON users FOR SELECT TO supportx_relay USING (true)"
            )
        finally:
            await conn.close()
        reports, _ = await rls_guard.run(database.admin_url)
        return [p for r in reports if r.name == "users" for p in r.problems]

    database = db_testing.create(db_config)
    try:
        problems = asyncio.run(grant_and_inspect(database))
    finally:
        db_testing.destroy(db_config, database)
    assert any("supportx_relay has ['SELECT']" in p for p in problems)
    assert any("users_relay_all is not tenant-restricted" in p for p in problems)
