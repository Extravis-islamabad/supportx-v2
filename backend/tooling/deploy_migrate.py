"""`python -m tooling.deploy_migrate`: the database step of every Kubernetes deploy (WP-014).

Run by the chart's migrate Job (one per Helm revision, before the new pods start serving):

1. wait until PostgreSQL accepts the admin login (a fresh in-cluster database takes a while);
2. create or complete the roles, the database and its schema privileges from tooling/sql (the
   single source, same as the dev stack and CI). Skipped for an external, DBA-managed database
   (`SUPPORTX_DEPLOY_ADMIN_URL` unset);
3. `alembic upgrade head` as supportx_migrator, under an advisory lock so two Jobs (two quick
   upgrades) never migrate at once.

Rollback-safe (expand/contract, architecture.md §14.3): when the database is already at a
revision this code does not know, it was migrated by a newer release and stays as it is (a
`helm rollback` only moves the images back). Never downgrades, never drops (CLAUDE.md rule h).

Environment: SUPPORTX_MIGRATION_DATABASE_URL (migrator), optional SUPPORTX_DEPLOY_ADMIN_URL
(superuser, any database) with SUPPORTX_DEPLOY_APP_PASSWORD / _MIGRATOR_PASSWORD /
_RELAY_PASSWORD, SUPPORTX_DEPLOY_DATABASE (default supportx), SUPPORTX_DEPLOY_WAIT_SECONDS (300),
SUPPORTX_DEPLOY_CNPG_POOLER=1 to let CloudNativePG's PgBouncer look up the roles
(tooling/sql/cnpg_pooler.sql).
"""

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import asyncpg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from tooling.db_bootstrap import RolePasswords, bootstrap, run_script, with_database

BACKEND_DIR = Path(__file__).resolve().parents[1]
POOLER_ROLE = "cnpg_pooler_pgbouncer"
# Any constant works; it only has to be the same for every migrate Job of this installation.
ADVISORY_LOCK_KEY = 0x5375_7058_4D69_67  # "SupXMig"


class Action(StrEnum):
    """What the migrate step does for a given database revision."""

    UPGRADE = "upgrade"
    CURRENT = "current"
    NEWER = "newer"  # migrated by a newer release: leave it alone


def plan(database_revision: str | None, known: set[str], head: str) -> Action:
    """Decide from the database's revision and the revisions this code ships."""
    if database_revision == head:
        return Action.CURRENT
    if database_revision is not None and database_revision not in known:
        return Action.NEWER
    return Action.UPGRADE


@dataclass(frozen=True)
class DeployConfig:
    """The migrate step's settings (environment only; no .env file in a cluster)."""

    migrator_url: str
    admin_url: str | None
    database: str
    passwords: RolePasswords | None
    wait_seconds: float
    cnpg_pooler: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "DeployConfig":
        """Read and check the environment."""
        admin = env.get("SUPPORTX_DEPLOY_ADMIN_URL") or None
        passwords = None
        if admin is not None:
            passwords = RolePasswords(
                app=env["SUPPORTX_DEPLOY_APP_PASSWORD"],
                migrator=env["SUPPORTX_DEPLOY_MIGRATOR_PASSWORD"],
                relay=env["SUPPORTX_DEPLOY_RELAY_PASSWORD"],
            )
        return cls(
            migrator_url=env["SUPPORTX_MIGRATION_DATABASE_URL"],
            admin_url=admin,
            database=env.get("SUPPORTX_DEPLOY_DATABASE", "supportx"),
            passwords=passwords,
            wait_seconds=float(env.get("SUPPORTX_DEPLOY_WAIT_SECONDS", "300")),
            cnpg_pooler=env.get("SUPPORTX_DEPLOY_CNPG_POOLER") == "1",
        )


def alembic_config(url: str) -> Config:
    """Alembic config for this image's migrations against `url`."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["database_url"] = url
    return config


async def wait_for(url: str, seconds: float) -> None:
    """Retry the login until it works or `seconds` pass (then the last error is raised)."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            conn = await asyncpg.connect(url, timeout=5)
        except (OSError, asyncpg.PostgresError, TimeoutError):
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(2)
        else:
            await conn.close()
            return


async def database_revision(conn: asyncpg.Connection) -> str | None:
    """The revision stamped in alembic_version, or None before the first migration."""
    exists = await conn.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL")
    if not exists:
        return None
    revision: str | None = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
    return revision


async def allow_cnpg_pooler(admin_url: str, database: str, seconds: float) -> None:
    """Let the CloudNativePG pooler authenticate our roles (its role appears after start-up)."""
    deadline = time.monotonic() + seconds
    admin = await asyncpg.connect(admin_url)
    try:
        while not await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", POOLER_ROLE):
            if time.monotonic() > deadline:
                msg = f"role {POOLER_ROLE} did not appear: is the CloudNativePG Pooler deployed?"
                raise RuntimeError(msg)
            await asyncio.sleep(2)
    finally:
        await admin.close()
    in_database = await asyncpg.connect(with_database(admin_url, database))
    try:
        await run_script(in_database, "cnpg_pooler.sql", {"database": database})
    finally:
        await in_database.close()


async def migrate(config: DeployConfig) -> Action:
    """Bootstrap (if allowed) and upgrade; returns what was done."""
    if config.admin_url is not None and config.passwords is not None:
        await wait_for(config.admin_url, config.wait_seconds)
        created = await bootstrap(config.admin_url, config.database, config.passwords)
        sys.stdout.write(f"database {config.database}: {'created' if created else 'present'}\n")
        if config.cnpg_pooler:
            await allow_cnpg_pooler(config.admin_url, config.database, config.wait_seconds)
    await wait_for(config.migrator_url, config.wait_seconds)
    script = ScriptDirectory.from_config(alembic_config(config.migrator_url))
    head = script.get_current_head()
    if head is None:  # pragma: no cover - the image always ships migrations
        msg = "no migrations found in this image"
        raise RuntimeError(msg)
    known = {rev.revision for rev in script.walk_revisions()}
    lock = await asyncpg.connect(config.migrator_url)
    try:
        await lock.execute("SELECT pg_advisory_lock($1)", ADVISORY_LOCK_KEY)
        action = plan(await database_revision(lock), known, head)
        if action is Action.UPGRADE:
            # Alembic's env.py runs its own event loop; keep it off this one.
            await asyncio.to_thread(command.upgrade, alembic_config(config.migrator_url), "head")
        await lock.execute("SELECT pg_advisory_unlock($1)", ADVISORY_LOCK_KEY)
    finally:
        await lock.close()
    return action


def main() -> int:  # pragma: no cover - thin CLI over tested functions
    """CLI entry point (the chart's migrate Job)."""
    config = DeployConfig.from_env(dict(os.environ))
    action = asyncio.run(migrate(config))
    messages = {
        Action.UPGRADE: "migrated to head",
        Action.CURRENT: "already at head",
        Action.NEWER: "database was migrated by a newer release; left unchanged",
    }
    sys.stdout.write(f"migrate: {messages[action]}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
