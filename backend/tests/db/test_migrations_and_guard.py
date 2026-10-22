"""Migrations run clean both ways, match the models, and leave every table isolated."""

import asyncio
from collections.abc import Iterator

import asyncpg
import pytest
from alembic import command
from alembic.util.exc import CommandError

from tooling import db_testing, rls_guard

pytestmark = pytest.mark.db


@pytest.fixture
def fresh_db(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """An empty, bootstrapped (not migrated) throwaway database."""
    database = db_testing.create(db_config, migrate_to=None)
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


def tables(url: str) -> set[str]:
    async def _fetch() -> set[str]:
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        finally:
            await conn.close()
        return {row["tablename"] for row in rows}

    return asyncio.run(_fetch())


def guard(url: str) -> tuple[list[rls_guard.TableReport], list[str]]:
    return asyncio.run(rls_guard.run(url))


def assert_guard_passes(url: str) -> None:
    reports, role_problems = guard(url)
    problems = role_problems + [f"{r.name}: {p}" for r in reports for p in r.problems]
    assert problems == [], rls_guard.render(reports, role_problems)


def test_upgrade_downgrade_upgrade_is_clean(fresh_db: db_testing.ThrowawayDatabase) -> None:
    db_testing.migrate(fresh_db.migrator_url)
    assert {"tenants", "display_id_sequences", "alembic_version"} <= tables(fresh_db.admin_url)
    assert_guard_passes(fresh_db.admin_url)

    db_testing.downgrade(fresh_db.migrator_url, "base")
    assert tables(fresh_db.admin_url) == {"alembic_version"}

    db_testing.migrate(fresh_db.migrator_url)
    assert_guard_passes(fresh_db.admin_url)


def test_models_match_migrations(fresh_db: db_testing.ThrowawayDatabase) -> None:
    """`alembic check`: autogenerate finds nothing, so no model change is missing a migration."""
    db_testing.migrate(fresh_db.migrator_url)
    command.check(db_testing.alembic_config(fresh_db.migrator_url))


def test_check_detects_drift(fresh_db: db_testing.ThrowawayDatabase) -> None:
    db_testing.migrate(fresh_db.migrator_url)

    async def _add_stray_table() -> None:
        conn = await asyncpg.connect(fresh_db.migrator_url)
        try:
            await conn.execute("CREATE TABLE stray (id uuid PRIMARY KEY)")
        finally:
            await conn.close()

    asyncio.run(_add_stray_table())
    with pytest.raises(CommandError, match="New upgrade operations detected"):
        command.check(db_testing.alembic_config(fresh_db.migrator_url))


def test_rls_guard_passes_on_the_migrated_database(
    migrated_db: db_testing.ThrowawayDatabase,
) -> None:
    reports, role_problems = guard(migrated_db.admin_url)
    by_name = {r.name: r for r in reports}
    assert set(by_name) >= {"tenants", "display_id_sequences", "probe_items"}
    assert by_name["tenants"].kind == "platform"
    assert by_name["display_id_sequences"].kind == "tenant"
    assert all(r.rls_enabled and r.rls_forced for r in reports)
    assert role_problems == []
    assert "RLS guard: PASS" in rls_guard.render(reports, role_problems)


RLS_ON = (
    "ALTER TABLE bad_t ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE bad_t FORCE ROW LEVEL SECURITY",
)
TENANT_TABLE = "CREATE TABLE bad_t (id uuid, tenant_id uuid NOT NULL, title text)"

# case -> (DDL statements, expected problem text)
BAD_TABLES: dict[str, tuple[tuple[str, ...], str]] = {
    "no tenant_id column": (
        ("CREATE TABLE bad_t (id uuid PRIMARY KEY)", *RLS_ON),
        "no tenant_id column",
    ),
    "RLS not enabled": ((TENANT_TABLE,), "RLS not enabled"),
    "RLS not forced": ((TENANT_TABLE, RLS_ON[0]), "RLS not forced"),
    "nullable tenant_id": (
        ("CREATE TABLE bad_t (id uuid, tenant_id uuid)", *RLS_ON),
        "tenant_id must be uuid NOT NULL",
    ),
    "no policies": (
        (TENANT_TABLE, *RLS_ON),
        "no tenant policy for ['DELETE', 'INSERT', 'SELECT', 'UPDATE']",
    ),
    "permissive policy": (
        (TENANT_TABLE, *RLS_ON, "CREATE POLICY open_all ON bad_t FOR ALL USING (true)"),
        "policy open_all is not tenant-restricted",
    ),
    "policy ignoring the tenant": (
        (TENANT_TABLE, *RLS_ON, "CREATE POLICY by_id ON bad_t FOR ALL USING (id IS NOT NULL)"),
        "does not compare tenant_id with app.tenant_id",
    ),
    "index not led by tenant_id": (
        (TENANT_TABLE, "CREATE INDEX ix_bad ON bad_t (title, tenant_id)"),
        "index ix_bad does not start with tenant_id",
    ),
    "TRUNCATE granted": (
        (TENANT_TABLE, "GRANT TRUNCATE ON bad_t TO supportx_app"),
        "forbidden privileges ['TRUNCATE']",
    ),
}


@pytest.mark.parametrize("case", list(BAD_TABLES))
def test_rls_guard_catches_unsafe_tables(
    migrated_db: db_testing.ThrowawayDatabase, case: str
) -> None:
    """Each unsafe table is created inside a transaction that is rolled back afterwards."""
    ddl, expected = BAD_TABLES[case]

    async def _inspect() -> list[str]:
        conn = await asyncpg.connect(migrated_db.migrator_url)
        try:
            transaction = conn.transaction()
            await transaction.start()
            try:
                for statement in ddl:
                    await conn.execute(statement)
                reports = await rls_guard.inspect(conn)
            finally:
                await transaction.rollback()
        finally:
            await conn.close()
        return [p for r in reports if r.name == "bad_t" for p in r.problems]

    problems = asyncio.run(_inspect())
    assert any(expected in p for p in problems), problems
