"""`make db-seed`: demo data for local development (WP-005, WP-006, WP-009).

Creates the two dev tenants and their subscriptions if they are missing. The tenant IDs match the
`tenant_id` attributes of the Keycloak organizations in deploy/compose/keycloak/supportx-realm.json.
Idempotent, never updates or deletes anything: an existing tenant or subscription is left exactly
as it is (change plans with `make dev-subscription`). Runs as supportx_migrator, the only role
allowed to create tenants and plans. Documented in docs/dev-setup.md.

Plans: Demo Company = Enterprise (edition defaults, no expiry); Other Company = Professional with
only 2 technician seats, so the seat limit can be tried by hand with the realm's users.
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime

import asyncpg

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.licensing import Edition, LimitKey, SubscriptionPlan, apply_subscription

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
# Fixed start so the seed is reproducible; no expiry (change with `make dev-subscription`).
PLAN_START = datetime(2026, 1, 1, tzinfo=UTC)
OTHER_TECHNICIAN_SEATS = 2
PLANS = {
    DEMO_TENANT_ID: SubscriptionPlan(edition=Edition.ENTERPRISE, starts_at=PLAN_START),
    OTHER_TENANT_ID: SubscriptionPlan(
        edition=Edition.PROFESSIONAL,
        starts_at=PLAN_START,
        limits={LimitKey.TECHNICIANS: OTHER_TECHNICIAN_SEATS},
    ),
}


async def seed(url: str) -> list[str]:
    """Insert the dev tenants and plans that are absent. Returns what was created now."""
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
    database = Database(create_engine(url, application_name="seed-dev", use_null_pool=True))
    try:
        for tenant_id, plan in PLANS.items():
            async with database.tenant_session(TenantContext(tenant_id)) as session:
                # Through the licensing write path: row + entitlement.changed event together.
                if await apply_subscription(session, plan, only_if_absent=True):
                    created.append(f"{tenant_id}:subscription")
    finally:
        await database.dispose()
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
        plan = PLANS[tenant_id]
        state = (
            "created"
            if f"{tenant_id}:subscription" in created
            else "already present (left unchanged)"
        )
        limits = {key.value: value for key, value in plan.limits.items()}
        sys.stdout.write(f"  Subscription {plan.edition.value} {limits}: {state}.\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
