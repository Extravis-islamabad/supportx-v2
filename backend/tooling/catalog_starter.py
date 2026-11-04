"""Add the starter catalog to an existing tenant (WP-031, D-138): `make catalog-starter TENANT=x`.

For dev, QA and demo tenants that existed before WP-031 (migration 0074 marked them, so the
automatic seed skips them). It seeds only a catalog that has never had anything (no categories
or items at all, deleted ones included): it never adds to or changes existing content. The items
arrive as drafts; an admin chooses their group and publishes them in the console.

Refuses the production profile.
"""

import asyncio
import sys

import asyncpg

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.service_catalog.service.starter import Seeded, seed_empty_catalog


async def seed(url: str, slug: str) -> Seeded | None:
    """Seed the tenant with this slug; None if there is no such tenant."""
    conn = await asyncpg.connect(url)
    try:
        tenant_id = await conn.fetchval("SELECT id FROM tenants WHERE slug = $1", slug)
    finally:
        await conn.close()
    if tenant_id is None:
        return None
    database = Database(create_engine(url, application_name="catalog-starter", use_null_pool=True))
    try:
        async with database.tenant_session(TenantContext(tenant_id)) as session:
            return await seed_empty_catalog(session)
    finally:
        await database.dispose()


def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI over the tested seed
    """CLI entry point."""
    if len(argv) != 1 or not argv[0]:
        sys.stderr.write("usage: make catalog-starter TENANT=<slug>\n")
        return 2
    settings = Settings()
    if settings.profile == "production":
        sys.stderr.write("refusing to run against production\n")
        return 2
    url = settings.migration_database_url
    if url is None:
        sys.stderr.write("SUPPORTX_MIGRATION_DATABASE_URL is not set (make backend-env)\n")
        return 2
    seeded = asyncio.run(seed(url.get_secret_value(), argv[0]))
    if seeded is None:
        sys.stderr.write(f"no tenant with the slug {argv[0]!r}\n")
        return 1
    if not seeded.items:
        sys.stdout.write("The catalog is not empty: nothing was added.\n")
    else:
        sys.stdout.write(
            f"Added {seeded.categories} categories and {seeded.items} items as drafts."
            " Choose their group and publish them under Admin > Service catalog.\n"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
