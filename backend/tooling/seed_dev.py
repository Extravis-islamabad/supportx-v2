"""`make db-seed`: demo data for local development (WP-005).

Creates the demo tenant if it is missing. Idempotent (`ON CONFLICT DO NOTHING`), never updates
or deletes anything. Runs as supportx_migrator, the only role allowed to create tenants.
The fixed ID is documented in docs/dev-setup.md so you can use it as X-Tenant-ID.
"""

import asyncio
import sys
import uuid

import asyncpg

from app.core.config import Settings

DEMO_TENANT_ID = uuid.UUID("01900000-0000-7000-8000-00000000de30")
DEMO_TENANT_NAME = "Demo Company"
DEMO_TENANT_SLUG = "demo"


async def seed(url: str) -> bool:
    """Insert the demo tenant if absent. Returns True if it was created now."""
    conn = await asyncpg.connect(url)
    try:
        status = await conn.execute(
            """
            INSERT INTO tenants (id, name, slug, status) VALUES ($1, $2, $3, 'active')
            ON CONFLICT DO NOTHING
            """,
            DEMO_TENANT_ID,
            DEMO_TENANT_NAME,
            DEMO_TENANT_SLUG,
        )
    finally:
        await conn.close()
    return status.endswith(" 1")


def main() -> int:  # pragma: no cover - thin CLI over the tested `seed`
    """CLI entry point."""
    url = Settings().migration_database_url
    if url is None:
        sys.stderr.write("SUPPORTX_MIGRATION_DATABASE_URL is not set (make backend-env)\n")
        return 2
    created = asyncio.run(seed(url.get_secret_value()))
    state = "created" if created else "already present (left unchanged)"
    sys.stdout.write(f"Demo tenant {DEMO_TENANT_SLUG} ({DEMO_TENANT_ID}): {state}.\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
