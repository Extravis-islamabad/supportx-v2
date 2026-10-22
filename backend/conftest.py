"""Shared pytest fixtures for app-level tests (tests/) and module tests (app/modules/*/tests/)."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.database import Database, create_engine
from tests.db.probe import create_probe_table
from tooling import db_testing


def make_settings(**overrides: Any) -> Settings:  # noqa: ANN401 - pydantic validates the values
    """Test-profile settings that never read backend/.env or the developer's environment file."""
    values: dict[str, Any] = {"profile": "test", "tracing_enabled": False, **overrides}
    return Settings.load(env_file=None, **values)


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    """Build test settings with overrides: `settings_factory(log_format="json")`."""
    return make_settings


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Run the app's lifespan (startup/shutdown hooks) around an HTTP client."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def run_app() -> Callable[[FastAPI], Any]:
    """Return `running`, used as `async with run_app(app) as client:`."""
    return running


# --- Database fixtures (WP-005) -----------------------------------------------------------------
# Tests marked `db` run against a throwaway database on the real PostgreSQL (dev stack locally,
# service container in CI). Locally they skip when no database is reachable; in CI
# SUPPORTX_REQUIRE_DB_TESTS=1 turns that skip into a failure, so they can never be skipped there.


def _unavailable(reason: str) -> None:
    if os.environ.get("SUPPORTX_REQUIRE_DB_TESTS") == "1":
        pytest.fail(f"database tests are required here but {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="session")
def db_config() -> db_testing.DbTestConfig:
    """Connection settings for test databases (skips/fails when unavailable)."""
    config = db_testing.load_config()
    if config is None:
        _unavailable("no test database configured (make dev-init / SUPPORTX_TEST_ADMIN_URL)")
        msg = "unreachable: _unavailable always raises"
        raise AssertionError(msg)
    if not asyncio.run(db_testing.server_reachable(config)):
        _unavailable("PostgreSQL is not reachable (make dev-up)")
    return config


@pytest.fixture(scope="session")
def migrated_db(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """One migrated throwaway database for the session, plus the probe_items test table."""
    database = db_testing.create(db_config)
    try:
        asyncio.run(create_probe_table(database.migrator_url))
        yield database
    finally:
        db_testing.destroy(db_config, database)


@pytest_asyncio.fixture
async def app_db(migrated_db: db_testing.ThrowawayDatabase) -> AsyncIterator[Database]:
    """The application role's Database (through PgBouncer when configured), per test."""
    database = Database(
        create_engine(migrated_db.app_url, application_name="tests", use_null_pool=True)
    )
    yield database
    await database.dispose()


async def create_tenant(migrator_url: str, name: str = "Tenant") -> uuid.UUID:
    """Insert a tenant as the migrator (the only role allowed to provision tenants)."""
    tenant_id = uuid.uuid4()
    conn = await asyncpg.connect(migrator_url)
    try:
        await conn.execute(
            "INSERT INTO tenants (id, name, slug) VALUES ($1, $2, $3)",
            tenant_id,
            name,
            f"t-{tenant_id.hex[:12]}",
        )
    finally:
        await conn.close()
    return tenant_id


@pytest_asyncio.fixture
async def tenant_pair(migrated_db: db_testing.ThrowawayDatabase) -> tuple[uuid.UUID, uuid.UUID]:
    """Two fresh tenants (A, B) for isolation tests."""
    return (
        await create_tenant(migrated_db.migrator_url, "Tenant A"),
        await create_tenant(migrated_db.migrator_url, "Tenant B"),
    )
