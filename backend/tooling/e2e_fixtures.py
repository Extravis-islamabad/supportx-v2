"""`python -m tooling.e2e_fixtures create|delete`: test records for the Playwright suite (WP-010).

Creates 40 requester rows in Demo Company (`e2e-scroll-NN@demo.test`) so the users list has
more than one page to scroll through; `delete` removes exactly those rows again. Only rows this
tool creates are ever touched (CLAUDE.md rule h): they are matched by their reserved e-mail
pattern. They are requesters, so they never take a technician seat. Refuses production.
"""

import asyncio
import sys
import uuid

import asyncpg

from app.core.config import Settings
from tooling.seed_dev import DEMO_TENANT_ID

COUNT = 40
PATTERN = "e2e-scroll-%@demo.test"


async def _in_tenant(conn: asyncpg.Connection) -> None:
    # users has FORCED RLS: even the migrator works inside the tenant's context.
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(DEMO_TENANT_ID))


async def create(url: str) -> int:
    """Insert the fixture users that are missing; returns how many were created."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await _in_tenant(conn)
            created = 0
            for n in range(COUNT):
                status = await conn.execute(
                    "INSERT INTO users (id, tenant_id, external_subject, email, display_name,"
                    " user_type, status, locale) VALUES ($1, $2, $3, $4, $5, 'requester',"
                    " 'active', 'en') ON CONFLICT DO NOTHING",
                    uuid.uuid4(),
                    DEMO_TENANT_ID,
                    f"e2e-scroll-{n:02d}",
                    f"e2e-scroll-{n:02d}@demo.test",
                    f"E2E Scroll {n:02d}",
                )
                created += status.endswith(" 1")
            return created
    finally:
        await conn.close()


async def delete(url: str) -> int:
    """Remove the fixture users (and nothing else); returns how many were removed."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await _in_tenant(conn)
            status = await conn.execute("DELETE FROM users WHERE email LIKE $1", PATTERN)
            return int(status.split()[-1])
    finally:
        await conn.close()


def main() -> int:  # pragma: no cover - thin CLI over the tested functions
    """CLI entry point."""
    settings = Settings()
    if settings.profile == "production" or settings.migration_database_url is None:
        sys.stderr.write(
            "e2e fixtures need a dev/test profile and SUPPORTX_MIGRATION_DATABASE_URL\n"
        )
        return 2
    action = sys.argv[1] if len(sys.argv) > 1 else "create"
    url = settings.migration_database_url.get_secret_value()
    done = asyncio.run(create(url) if action == "create" else delete(url))
    sys.stdout.write(f"e2e fixtures {action}: {done} rows\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
