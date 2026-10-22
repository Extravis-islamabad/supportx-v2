"""Create the database roles and a SupportX database the way the dev stack does (WP-005).

The dev stack's init script (deploy/compose/postgres/initdb/10-supportx.sh) runs only inside the
compose Postgres. This module does the same for any PostgreSQL where we hold a superuser login:
test fixtures (throwaway databases) and CI (service container). Keep the two in step.

    supportx_migrator  owns the database and schema; runs migrations.
    supportx_app       runtime role: not superuser, owns nothing, NOBYPASSRLS, NOINHERIT.

Existing roles keep their passwords (the dev stack's .env depends on them); only their safety
attributes are re-asserted.

CLI (CI): python -m tooling.db_bootstrap --database supportx
  env: SUPPORTX_TEST_ADMIN_URL, SUPPORTX_TEST_APP_PASSWORD, SUPPORTX_TEST_MIGRATOR_PASSWORD
"""

import argparse
import asyncio
import os
import re
import sys
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from app.shared.db.rls import APP_ROLE, MIGRATOR_ROLE

TEST_DATABASE_PREFIX = "supportx_test_"
_ROLE_ATTRIBUTES = {
    MIGRATOR_ROLE: "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
    APP_ROLE: "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT",
}
_DATABASE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def with_database(url: str, database: str) -> str:
    """Same server and credentials, different database."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


def with_credentials(url: str, user: str, password: str) -> str:
    """Same server and database, different login."""
    parts = urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit(parts._replace(netloc=f"{user}:{password}@{host}{port}"))


async def ensure_roles(
    admin: asyncpg.Connection, app_password: str, migrator_password: str
) -> None:
    """Create missing roles; re-assert safety attributes on all of them."""
    for role, password in ((MIGRATOR_ROLE, migrator_password), (APP_ROLE, app_password)):
        exists = await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
        if not exists:
            statement = await admin.fetchval(
                "SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', $1::text, $2::text)",
                role,
                password,
            )
            await admin.execute(statement)
        await admin.execute(f"ALTER ROLE {role} LOGIN {_ROLE_ATTRIBUTES[role]}")


async def create_database(admin: asyncpg.Connection, name: str) -> bool:
    """Create `name` owned by the migrator if missing. Returns True if it was created."""
    if not _DATABASE_NAME.fullmatch(name):
        msg = f"unsafe database name {name!r}"
        raise ValueError(msg)
    if await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
        return False
    await admin.execute(f"CREATE DATABASE {name} OWNER {MIGRATOR_ROLE}")
    await admin.execute(f"REVOKE ALL ON DATABASE {name} FROM PUBLIC")
    await admin.execute(f"GRANT CONNECT, TEMPORARY ON DATABASE {name} TO {APP_ROLE}")
    return True


async def prepare_schema(admin_in_database: asyncpg.Connection) -> None:
    """Extensions and schema privileges inside the database (connected as superuser)."""
    for extension in ("vector", "pgcrypto", "citext"):
        await admin_in_database.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
    await admin_in_database.execute(f"ALTER SCHEMA public OWNER TO {MIGRATOR_ROLE}")
    await admin_in_database.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    await admin_in_database.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")


async def drop_test_database(admin: asyncpg.Connection, name: str) -> None:
    """Drop a throwaway test database. Refuses any name without the test prefix."""
    if not name.startswith(TEST_DATABASE_PREFIX) or not _DATABASE_NAME.fullmatch(name):
        msg = f"refusing to drop {name!r}: only {TEST_DATABASE_PREFIX}* databases"
        raise ValueError(msg)
    await admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


async def bootstrap(
    admin_url: str, database: str, app_password: str, migrator_password: str
) -> bool:
    """Roles + database + schema. Idempotent; never drops or alters data."""
    admin = await asyncpg.connect(admin_url)
    try:
        await ensure_roles(admin, app_password, migrator_password)
        created = await create_database(admin, database)
    finally:
        await admin.close()
    in_database = await asyncpg.connect(with_database(admin_url, database))
    try:
        await prepare_schema(in_database)
    finally:
        await in_database.close()
    return created


def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI over tested functions
    """CLI entry point used by CI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="supportx")
    args = parser.parse_args(argv)
    created = asyncio.run(
        bootstrap(
            os.environ["SUPPORTX_TEST_ADMIN_URL"],
            args.database,
            os.environ["SUPPORTX_TEST_APP_PASSWORD"],
            os.environ["SUPPORTX_TEST_MIGRATOR_PASSWORD"],
        )
    )
    sys.stdout.write(f"database {args.database}: {'created' if created else 'already present'}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
