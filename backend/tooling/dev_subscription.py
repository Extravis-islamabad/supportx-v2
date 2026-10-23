"""`make dev-subscription`: show or change a dev tenant's plan (WP-009, docs/dev-setup.md).

Runs as supportx_migrator (the app role cannot write subscriptions) and goes through the licensing
module's own write path, so the change and its `licensing.entitlement.changed` event commit
together and every running API drops its cached entitlement as soon as the consumer worker sees
the event. Only the fields given on the command line change. Refuses to run in production.

    make dev-subscription TENANT=other                          # show
    make dev-subscription TENANT=other ARGS="--technicians 1"   # one technician seat
    make dev-subscription TENANT=other ARGS="--expires 2026-10-20 --grace-days 14"  # grace
    make dev-subscription TENANT=other ARGS="--expires 2026-09-01"                  # read-only
    make dev-subscription TENANT=other ARGS="--expires never --status active"       # back to normal
"""

import argparse
import asyncio
import dataclasses
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.modules import discover_modules
from app.core.tenancy import TenantContext
from app.modules.licensing import (
    Edition,
    LimitKey,
    SubscriptionPlan,
    apply_subscription,
    current_subscription,
)
from tooling.seed_dev import DEMO_TENANT_ID, OTHER_TENANT_ID

ALIASES = {"demo": DEMO_TENANT_ID, "other": OTHER_TENANT_ID}


def tenant_id(value: str) -> uuid.UUID:
    """`demo`, `other` or a tenant UUID."""
    return ALIASES.get(value) or uuid.UUID(value)


def _limit(value: str) -> int | None:
    return None if value == "unlimited" else int(value)


def _day_end(value: str) -> datetime | None:
    if value == "never":
        return None
    return datetime.combine(date.fromisoformat(value), time.min, tzinfo=UTC) + timedelta(days=1)


def parse_args(argv: Sequence[str]) -> tuple[uuid.UUID, dict[str, Any]]:
    """The tenant and the requested changes (only options given on the command line)."""
    parser = argparse.ArgumentParser(prog="dev-subscription", description=__doc__.split("\n")[0])
    parser.add_argument("--tenant", type=tenant_id, required=True)
    changes = parser.add_argument_group("changes (omit all to just show the plan)")
    changes.add_argument("--edition", type=Edition, default=argparse.SUPPRESS)
    for key in LimitKey:
        changes.add_argument(
            f"--{key.value.replace('_', '-')}",
            dest=key.value,
            type=_limit,
            default=argparse.SUPPRESS,
            help="a number or 'unlimited'",
        )
    changes.add_argument("--expires", dest="expires_at", type=_day_end, default=argparse.SUPPRESS)
    changes.add_argument("--grace-days", type=int, default=argparse.SUPPRESS)
    changes.add_argument("--status", choices=["active", "suspended"], default=argparse.SUPPRESS)
    values = vars(parser.parse_args(argv))
    return values.pop("tenant"), values


def changed_plan(current: SubscriptionPlan | None, changes: dict[str, Any]) -> SubscriptionPlan:
    """The current plan with `changes` applied (a new Professional plan if there is none)."""
    plan = current or SubscriptionPlan(
        edition=Edition.PROFESSIONAL, starts_at=datetime.now(UTC) - timedelta(days=1)
    )
    limit_keys = {key.value for key in LimitKey}
    limits = dict(plan.limits)
    for name in limit_keys & changes.keys():
        limits[LimitKey(name)] = changes[name]
    fields = {name: value for name, value in changes.items() if name not in limit_keys}
    return dataclasses.replace(plan, limits=limits, **fields)


def describe(plan: SubscriptionPlan | None) -> str:
    """One readable line per field."""
    if plan is None:
        return "  no subscription (nothing is licensed)"
    limits = {key.value: value for key, value in plan.limits.items()} or "edition defaults"
    rows = {
        "edition": plan.edition.value,
        "add-on features": sorted(f.value for f in plan.features) or "none",
        "limit overrides": limits,
        "starts": plan.starts_at.date().isoformat(),
        "expires": plan.expires_at.isoformat() if plan.expires_at else "never",
        "grace days": plan.grace_days,
        "status": plan.status,
    }
    return "\n".join(f"  {name}: {value}" for name, value in rows.items())


async def run(migrator_url: str, tenant: uuid.UUID, changes: dict[str, Any]) -> str:
    """Show the tenant's plan, or change it when `changes` is not empty; returns a report."""
    # Load every module's models, as the app does: the ORM resolves tenant_subscriptions'
    # foreign key to `tenants` (organization module) when it flushes an update.
    discover_modules()
    database = Database(create_engine(migrator_url, application_name="dev-subscription"))
    try:
        async with database.tenant_session(TenantContext(tenant)) as session:
            current = await current_subscription(session)
            if not changes:
                return f"Tenant {tenant}:\n{describe(current)}"
            plan = changed_plan(current, changes)
            changed = await apply_subscription(session, plan)
            return f"Tenant {tenant}: changed {', '.join(changed) or 'nothing'}\n{describe(plan)}"
    finally:
        await database.dispose()


def main() -> int:  # pragma: no cover - thin CLI over the tested functions
    """CLI entry point."""
    settings = Settings()
    if settings.profile == "production":
        sys.stderr.write("dev-subscription never runs in the production profile\n")
        return 2
    if settings.migration_database_url is None:
        sys.stderr.write("SUPPORTX_MIGRATION_DATABASE_URL is not set (make backend-env)\n")
        return 2
    tenant, changes = parse_args(sys.argv[1:])
    url = settings.migration_database_url.get_secret_value()
    sys.stdout.write(asyncio.run(run(url, tenant, changes)) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
