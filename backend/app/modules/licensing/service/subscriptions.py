"""Changing a tenant's subscription (control-plane side; WP-009).

The application role cannot write `tenant_subscriptions` at all. This runs in a tenant session of
a platform role (today: supportx_migrator from `make db-seed` / `make dev-subscription`; later the
control plane's provisioning service). The row and the `licensing.entitlement.changed` event are
written in the same transaction (CLAUDE.md rule b), and the event invalidates every API process's
cache (infra/cache.py).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.licensing.domain.catalogue import Edition, Feature, LimitKey
from app.modules.licensing.domain.entitlement import DEFAULT_GRACE_DAYS
from app.modules.licensing.events import EntitlementChanged
from app.modules.licensing.infra.models import TenantSubscription
from app.modules.licensing.service.entitlements import session_tenant
from app.shared.events import record_event

SubscriptionStatus = Literal["active", "suspended"]


@dataclass(frozen=True)
class SubscriptionPlan:
    """Everything a subscription row holds."""

    edition: Edition
    starts_at: datetime
    features: frozenset[Feature] = frozenset()
    limits: Mapping[LimitKey, int | None] = field(default_factory=lambda: MappingProxyType({}))
    expires_at: datetime | None = None
    maintenance_until: datetime | None = None
    grace_days: int = DEFAULT_GRACE_DAYS
    status: SubscriptionStatus = "active"

    def columns(self) -> dict[str, Any]:
        """Column values of the row."""
        return {
            "edition": self.edition.value,
            "features": sorted(f.value for f in self.features),
            "limits": {k.value: v for k, v in sorted(self.limits.items())},
            "starts_at": self.starts_at,
            "expires_at": self.expires_at,
            "maintenance_until": self.maintenance_until,
            "grace_days": self.grace_days,
            "status": self.status,
        }


async def apply_subscription(
    session: AsyncSession, plan: SubscriptionPlan, *, only_if_absent: bool = False
) -> list[str]:
    """Create or update the session tenant's subscription. Returns the changed column names.

    `only_if_absent=True` never touches an existing row (seeding). Emits
    `licensing.entitlement.changed` when anything changed, in this transaction.
    """
    tenant_id = session_tenant(session).tenant_id
    values = plan.columns()
    row = await session.scalar(
        select(TenantSubscription)
        .where(TenantSubscription.tenant_id == tenant_id)
        .with_for_update()
    )
    if row is None:
        await session.execute(insert(TenantSubscription).values(tenant_id=tenant_id, **values))
        changed, version = sorted(values), 1
    elif only_if_absent:
        return []
    else:
        changed = sorted(name for name, value in values.items() if getattr(row, name) != value)
        if not changed:
            return []
        for name in changed:
            setattr(row, name, values[name])
        row.version += 1
        row.updated_at = datetime.now(row.updated_at.tzinfo)
        version = row.version
        await session.flush()
    await record_event(
        session,
        EntitlementChanged(source="subscription", changed_fields=changed),
        aggregate_id=tenant_id,
        aggregate_version=version,
    )
    return changed


async def current_subscription(session: AsyncSession) -> SubscriptionPlan | None:
    """The session tenant's subscription as a plan, or None (platform tooling)."""
    tenant_id = session_tenant(session).tenant_id
    row = await session.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
    )
    if row is None:
        return None
    return SubscriptionPlan(
        edition=Edition(row.edition),
        starts_at=row.starts_at,
        features=frozenset(Feature(f) for f in row.features),
        limits={LimitKey(k): v for k, v in row.limits.items()},
        expires_at=row.expires_at,
        maintenance_until=row.maintenance_until,
        grace_days=row.grace_days,
        status="suspended" if row.status == "suspended" else "active",
    )
