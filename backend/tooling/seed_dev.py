"""`make db-seed`: demo data for local development (WP-005, WP-006).

Creates the two dev tenants if they are missing. Their IDs match the `tenant_id` attributes of the
Keycloak organizations in deploy/compose/keycloak/supportx-realm.json. Idempotent
(`ON CONFLICT DO NOTHING`), never updates or deletes anything. Runs as supportx_migrator, the only
role allowed to create tenants. The fixed IDs are documented in docs/dev-setup.md.
"""

import asyncio
import sys
import uuid

import asyncpg

from app.core.config import Settings

DEMO_TENANT_ID = uuid.UUID("01900000-0000-7000-8000-00000000de30")
DEMO_TENANT_NAME = "Demo Company"
DEMO_TENANT_SLUG = "demo"
OTHER_TENANT_ID = uuid.UUID("01900000-0000-7000-8000-00000000a7e2")
OTHER_TENANT_NAME = "Other Company"
OTHER_TENANT_SLUG = "other"
TENANTS = (
    (DEMO_TENANT_ID, DEMO_TENANT_NAME, DEMO_TENANT_SLUG),
    (OTHER_TENANT_ID, OTHER_TENANT_NAME, OTHER_TENANT_SLUG),
)


async def seed(url: str) -> list[str]:
    """Insert the dev tenants that are absent. Returns the slugs created now."""
    created: list[str] = []
    conn = await asyncpg.connect(url)
    try:
        for tenant_id, name, slug in TENANTS:
            status = await conn.execute(
                """
                INSERT INTO tenants (id, name, slug, status) VALUES ($1, $2, $3, 'active')
                ON CONFLICT DO NOTHING
                """,
                tenant_id,
                name,
                slug,
            )
            if status.endswith(" 1"):
                created.append(slug)
    finally:
        await conn.close()
    return created


def main() -> int:  # pragma: no cover - thin CLI over the tested `seed`
    """CLI entry point."""
    url = Settings().migration_database_url
    if url is None:
        sys.stderr.write("SUPPORTX_MIGRATION_DATABASE_URL is not set (make backend-env)\n")
        return 2
    created = asyncio.run(seed(url.get_secret_value()))
    for tenant_id, _name, slug in TENANTS:
        state = "created" if slug in created else "already present (left unchanged)"
        sys.stdout.write(f"Tenant {slug} ({tenant_id}): {state}.\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
