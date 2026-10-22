"""Create the database roles and a SupportX database (WP-005; single source since WP-006).

The definitions live in tooling/sql/*.sql and are executed by BOTH this module (test fixtures,
CI) and the dev stack's PostgreSQL init script (with psql), so they cannot drift. This module
contains a tiny runner for the psql subset those files use (see tooling/sql/README.md).

CLI (CI): python -m tooling.db_bootstrap --database supportx
  env: SUPPORTX_TEST_ADMIN_URL, SUPPORTX_TEST_APP_PASSWORD, SUPPORTX_TEST_MIGRATOR_PASSWORD
"""

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

SQL_DIR = Path(__file__).resolve().parent / "sql"
TEST_DATABASE_PREFIX = "supportx_test_"
_DATABASE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_LITERAL_VAR = re.compile(r":'([A-Za-z_][A-Za-z0-9_]*)'")
_IDENTIFIER_VAR = re.compile(r':"([A-Za-z_][A-Za-z0-9_]*)"')
_GEXEC = "\\gexec"


@dataclass(frozen=True)
class Statement:
    """One statement from a bootstrap SQL file."""

    sql: str
    gexec: bool  # psql \gexec: run, then execute every value of the result as SQL


def quote_literal(value: str) -> str:
    """SQL string literal (standard_conforming_strings, the PostgreSQL default since 9.1)."""
    if "\x00" in value:
        msg = "NUL byte in SQL literal"
        raise ValueError(msg)
    return "'" + value.replace("'", "''") + "'"


def quote_identifier(value: str) -> str:
    """SQL identifier, always double-quoted."""
    if "\x00" in value:
        msg = "NUL byte in SQL identifier"
        raise ValueError(msg)
    return '"' + value.replace('"', '""') + '"'


def parse(script: str, variables: Mapping[str, str]) -> list[Statement]:
    """Split a bootstrap file into statements, substituting psql-style variables."""

    def literal(match: re.Match[str]) -> str:
        return quote_literal(variables[match.group(1)])

    def identifier(match: re.Match[str]) -> str:
        return quote_identifier(variables[match.group(1)])

    statements: list[Statement] = []
    buffer: list[str] = []
    for raw in script.splitlines():
        line = raw.rstrip()
        if not buffer and (not line.strip() or line.lstrip().startswith("--")):
            continue
        gexec = line.endswith(_GEXEC)
        if gexec:
            line = line[: -len(_GEXEC)].rstrip()
        buffer.append(line)
        if gexec or line.endswith(";"):
            sql = "\n".join(buffer).rstrip(";").strip()
            sql = _IDENTIFIER_VAR.sub(identifier, _LITERAL_VAR.sub(literal, sql))
            statements.append(Statement(sql=sql, gexec=gexec))
            buffer = []
    if any(part.strip() for part in buffer):
        msg = "bootstrap SQL ends without ';' or \\gexec"
        raise ValueError(msg)
    return statements


async def run_script(conn: asyncpg.Connection, name: str, variables: Mapping[str, str]) -> None:
    """Execute tooling/sql/<name> on `conn` like `psql -v ... -f <name>` would."""
    for statement in parse((SQL_DIR / name).read_text(encoding="utf-8"), variables):
        if statement.gexec:
            for row in await conn.fetch(statement.sql):
                for value in row.values():
                    await conn.execute(value)
        else:
            await conn.execute(statement.sql)


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


def _check_database_name(name: str) -> str:
    if not _DATABASE_NAME.fullmatch(name):
        msg = f"unsafe database name {name!r}"
        raise ValueError(msg)
    return name


async def drop_test_database(admin: asyncpg.Connection, name: str) -> None:
    """Drop a throwaway test database. Refuses any name without the test prefix."""
    if not name.startswith(TEST_DATABASE_PREFIX) or not _DATABASE_NAME.fullmatch(name):
        msg = f"refusing to drop {name!r}: only {TEST_DATABASE_PREFIX}* databases"
        raise ValueError(msg)
    await admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


async def bootstrap(
    admin_url: str, database: str, app_password: str, migrator_password: str
) -> bool:
    """Roles + database + schema. Idempotent; never drops or alters data. True if created."""
    _check_database_name(database)
    admin = await asyncpg.connect(admin_url)
    try:
        await run_script(
            admin,
            "roles.sql",
            {"app_password": app_password, "migrator_password": migrator_password},
        )
        existed = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database)
        await run_script(admin, "database.sql", {"database": database})
    finally:
        await admin.close()
    in_database = await asyncpg.connect(with_database(admin_url, database))
    try:
        await run_script(in_database, "schema.sql", {})
    finally:
        await in_database.close()
    return not existed


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
