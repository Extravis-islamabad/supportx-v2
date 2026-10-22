"""Throwaway PostgreSQL databases for the test suite (WP-005).

Each test session creates its own `supportx_test_<random>` database on the real server (dev stack
locally, service container in CI), creates the roles exactly like CI does (tooling.db_bootstrap),
migrates it to head as supportx_migrator, and drops it afterwards. Existing databases and data are
never touched (CLAUDE.md rule h).

Connection settings, in order:
1. env: SUPPORTX_TEST_ADMIN_URL (superuser, any database), SUPPORTX_TEST_APP_PASSWORD,
   SUPPORTX_TEST_MIGRATOR_PASSWORD, optional SUPPORTX_TEST_PGBOUNCER (host:port);
2. otherwise the dev stack's deploy/compose/.env.
The application role connects through PgBouncer when one is configured (as in production).
"""

import asyncio
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
from alembic import command
from alembic.config import Config

from app.shared.db.rls import APP_ROLE, MIGRATOR_ROLE
from tooling.db_bootstrap import (
    TEST_DATABASE_PREFIX,
    bootstrap,
    drop_test_database,
    with_credentials,
    with_database,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
STACK_ENV = BACKEND_DIR.parent / "deploy" / "compose" / ".env"


@dataclass(frozen=True)
class DbTestConfig:
    """Where the test databases live and how to log in."""

    admin_url: str
    app_password: str
    migrator_password: str
    pgbouncer: str | None  # "host:port" or None to connect the app role directly


@dataclass(frozen=True)
class ThrowawayDatabase:
    """One migrated throwaway database."""

    name: str
    admin_url: str
    migrator_url: str
    app_url: str  # through PgBouncer when configured
    app_direct_url: str


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def load_config() -> DbTestConfig | None:
    """Test database settings from the environment or the dev stack, or None if neither."""
    if admin_url := os.environ.get("SUPPORTX_TEST_ADMIN_URL"):
        return DbTestConfig(
            admin_url=admin_url,
            app_password=os.environ["SUPPORTX_TEST_APP_PASSWORD"],
            migrator_password=os.environ["SUPPORTX_TEST_MIGRATOR_PASSWORD"],
            pgbouncer=os.environ.get("SUPPORTX_TEST_PGBOUNCER") or None,
        )
    if not STACK_ENV.is_file():
        return None
    env = _read_env_file(STACK_ENV)
    return DbTestConfig(
        admin_url=(
            f"postgresql://{env['POSTGRES_SUPERUSER']}:{env['POSTGRES_SUPERUSER_PASSWORD']}"
            f"@127.0.0.1:{env['POSTGRES_PORT']}/postgres"
        ),
        app_password=env["SUPPORTX_APP_PASSWORD"],
        migrator_password=env["SUPPORTX_MIGRATOR_PASSWORD"],
        pgbouncer=f"127.0.0.1:{env['PGBOUNCER_PORT']}",
    )


async def server_reachable(config: DbTestConfig) -> bool:
    """Whether the admin login works (used to skip locally when the stack is down)."""
    try:
        conn = await asyncpg.connect(config.admin_url, timeout=3)
    except (OSError, asyncpg.PostgresError, TimeoutError):
        return False
    await conn.close()
    return True


def _via(url: str, hostport: str) -> str:
    """Same login and database, different host:port (e.g. PgBouncer instead of PostgreSQL)."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(netloc=f"{parts.username}:{parts.password}@{hostport}"))


def describe(config: DbTestConfig, name: str) -> ThrowawayDatabase:
    """URLs for database `name` as each role."""
    in_db = with_database(config.admin_url, name)
    app_direct = with_credentials(in_db, APP_ROLE, config.app_password)
    return ThrowawayDatabase(
        name=name,
        admin_url=in_db,
        migrator_url=with_credentials(in_db, MIGRATOR_ROLE, config.migrator_password),
        app_url=_via(app_direct, config.pgbouncer) if config.pgbouncer else app_direct,
        app_direct_url=app_direct,
    )


def alembic_config(url: str) -> Config:
    """Alembic config for backend/alembic.ini against `url`."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["database_url"] = url
    return config


def migrate(url: str, revision: str = "head") -> None:
    """Upgrade to `revision` (sync; runs its own event loop)."""
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str = "base") -> None:
    """Downgrade to `revision` (sync)."""
    command.downgrade(alembic_config(url), revision)


def create(config: DbTestConfig, *, migrate_to: str | None = "head") -> ThrowawayDatabase:
    """Create, bootstrap and (optionally) migrate a fresh throwaway database."""
    name = f"{TEST_DATABASE_PREFIX}{secrets.token_hex(6)}"
    asyncio.run(bootstrap(config.admin_url, name, config.app_password, config.migrator_password))
    database = describe(config, name)
    if migrate_to is not None:
        migrate(database.migrator_url, migrate_to)
    return database


def destroy(config: DbTestConfig, database: ThrowawayDatabase) -> None:
    """Drop a throwaway database created by `create`."""

    async def _drop() -> None:
        conn = await asyncpg.connect(config.admin_url)
        try:
            await drop_test_database(conn, database.name)
        finally:
            await conn.close()

    asyncio.run(_drop())
