"""Attacks on tenant isolation, run as supportx_app through PgBouncer (CLAUDE.md rule a).

Each test plays tenant A trying to reach tenant B's data, or code with no tenant at all. The
database must refuse every one of them on its own: these tests use raw SQL where the repository
would never even try.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.database import Database, TenantContextMissingError
from app.core.tenancy import TenantContext
from tests.db.probe import ProbeItem, ProbeRepository

pytestmark = pytest.mark.db


async def seed_probe(db: Database, tenant: uuid.UUID, title: str) -> uuid.UUID:
    async with db.tenant_session(TenantContext(tenant)) as session:
        item = await ProbeRepository(session).add(ProbeItem(title=title))
        return item.id


@pytest.fixture
async def two_tenants_with_rows(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant A, tenant B, A's row, B's row)."""
    a, b = tenant_pair
    return a, b, await seed_probe(app_db, a, "a-secret"), await seed_probe(app_db, b, "b-secret")


async def test_select_sees_only_own_rows(
    app_db: Database, two_tenants_with_rows: tuple[uuid.UUID, ...]
) -> None:
    a, _b, a_row, b_row = two_tenants_with_rows
    async with app_db.tenant_session(TenantContext(a)) as session:
        all_rows = (await session.execute(text("SELECT id, tenant_id FROM probe_items"))).all()
        by_id = await session.scalar(
            text("SELECT count(*) FROM probe_items WHERE id = :id"), {"id": b_row}
        )
        by_tenant = await session.scalar(
            text("SELECT count(*) FROM probe_items WHERE tenant_id <> :a"), {"a": a}
        )
    assert {row.tenant_id for row in all_rows} == {a}
    assert a_row in {row.id for row in all_rows}
    assert by_id == 0
    assert by_tenant == 0


async def test_update_and_delete_of_other_tenant_affect_nothing(
    app_db: Database, two_tenants_with_rows: tuple[uuid.UUID, ...]
) -> None:
    a, b, _a_row, b_row = two_tenants_with_rows
    async with app_db.tenant_session(TenantContext(a)) as session:
        updated = await session.execute(
            text("UPDATE probe_items SET title = 'hacked' WHERE id = :id"), {"id": b_row}
        )
        deleted = await session.execute(
            text("DELETE FROM probe_items WHERE id = :id"), {"id": b_row}
        )
        assert updated.rowcount == 0  # type: ignore[attr-defined]  # CursorResult at runtime
        assert deleted.rowcount == 0  # type: ignore[attr-defined]
    async with app_db.tenant_session(TenantContext(b)) as session:
        title = await session.scalar(
            text("SELECT title FROM probe_items WHERE id = :id"), {"id": b_row}
        )
    assert title == "b-secret"


async def test_insert_for_other_tenant_is_rejected(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = tenant_pair
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with app_db.tenant_session(TenantContext(a)) as session:
            await session.execute(
                text("INSERT INTO probe_items (id, tenant_id, title) VALUES (:id, :b, 'smuggled')"),
                {"id": uuid.uuid4(), "b": b},
            )


async def test_moving_own_row_to_other_tenant_is_rejected(
    app_db: Database, two_tenants_with_rows: tuple[uuid.UUID, ...]
) -> None:
    a, b, a_row, _b_row = two_tenants_with_rows
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with app_db.tenant_session(TenantContext(a)) as session:
            await session.execute(
                text("UPDATE probe_items SET tenant_id = :b WHERE id = :id"), {"b": b, "id": a_row}
            )


async def test_no_tenant_sees_nothing_and_cannot_write(
    app_db: Database, two_tenants_with_rows: tuple[uuid.UUID, ...]
) -> None:
    a, *_ = two_tenants_with_rows
    async with app_db.platform_session() as session:
        assert await session.scalar(text("SELECT count(*) FROM probe_items")) == 0
        assert await session.scalar(text("SELECT count(*) FROM tenants")) == 0
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with app_db.platform_session() as session:
            await session.execute(
                text("INSERT INTO probe_items (id, tenant_id, title) VALUES (:id, :a, 'x')"),
                {"id": uuid.uuid4(), "a": a},
            )


async def test_tenant_session_without_context_refuses_to_run_sql(app_db: Database) -> None:
    session = app_db.session_without_context()
    try:
        with pytest.raises(TenantContextMissingError):
            await session.execute(text("SELECT 1"))
    finally:
        await session.close()


async def test_tenant_setting_does_not_leak_to_the_next_transaction(
    app_db: Database, two_tenants_with_rows: tuple[uuid.UUID, ...]
) -> None:
    """Same physical connection, tenant first, then no tenant: SET LOCAL must have expired and
    the '' left behind must read as 'no tenant' (zero rows), not as an error or a leak."""
    a, *_ = two_tenants_with_rows
    async with app_db.engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a)})
            assert await conn.scalar(text("SELECT count(*) FROM probe_items")) >= 1
        async with conn.begin():
            assert await conn.scalar(text("SELECT current_setting('app.tenant_id', true)")) == ""
            assert await conn.scalar(text("SELECT count(*) FROM probe_items")) == 0


async def test_garbage_tenant_value_fails_closed(app_db: Database) -> None:
    async def query_with_garbage_tenant() -> None:
        async with app_db.platform_session() as session:
            await session.execute(text("SELECT set_config('app.tenant_id', 'not-a-uuid', true)"))
            await session.execute(text("SELECT count(*) FROM probe_items"))

    with pytest.raises(DBAPIError, match="invalid input syntax for type uuid"):
        await query_with_garbage_tenant()


@pytest.mark.parametrize(
    ("statement", "error"),
    [
        ("ALTER TABLE probe_items DISABLE ROW LEVEL SECURITY", "must be owner"),
        ("ALTER TABLE probe_items NO FORCE ROW LEVEL SECURITY", "must be owner"),
        ("DROP POLICY probe_items_tenant_select ON probe_items", "must be owner"),
        ("TRUNCATE probe_items", "permission denied"),
        ("SET ROLE supportx_migrator", "permission denied"),
        ("CREATE TABLE sneaky (id int)", "permission denied"),
        (
            "INSERT INTO tenants (id, name, slug) VALUES (gen_random_uuid(), 'x', 'x1')",
            "permission denied",
        ),
        ("UPDATE tenants SET name = 'x'", "permission denied"),
    ],
)
async def test_app_role_cannot_weaken_isolation(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID], statement: str, error: str
) -> None:
    a, _b = tenant_pair
    with pytest.raises(DBAPIError, match=error):
        async with app_db.tenant_session(TenantContext(a)) as session:
            await session.execute(text(statement))


async def test_row_security_off_errors_instead_of_bypassing(
    app_db: Database, two_tenants_with_rows: tuple[uuid.UUID, ...]
) -> None:
    a, *_ = two_tenants_with_rows

    async def query_with_row_security_off() -> None:
        async with app_db.tenant_session(TenantContext(a)) as session:
            await session.execute(text("SET LOCAL row_security = off"))
            await session.execute(text("SELECT * FROM probe_items"))

    with pytest.raises(DBAPIError, match="row-level security"):
        await query_with_row_security_off()


async def test_tenants_table_shows_only_own_tenant(
    app_db: Database, tenant_pair: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _b = tenant_pair
    async with app_db.tenant_session(TenantContext(a)) as session:
        visible = (await session.execute(text("SELECT id FROM tenants"))).scalars().all()
    assert visible == [a]


async def test_app_role_attributes(app_db: Database) -> None:
    async with app_db.platform_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, current_user FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).one()
    assert row.current_user == "supportx_app"
    assert row.rolsuper is False
    assert row.rolbypassrls is False
