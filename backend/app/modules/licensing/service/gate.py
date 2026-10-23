"""HTTP enforcement: the route gate and the rate-limit budgets (WP-009).

`RouteGate` is the `EntitlementGate` that app/core/entitlements.py calls for every module route:
feature check, read-only check for writes, and the grace warning headers for tenant admins.
`EntitlementRateLimits` is the WP-008 `RateLimitPolicyProvider` hook: budgets scale by edition.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping

from app.core.errors import EntitlementRequired, ReadOnlyMode
from app.core.tenancy import TenantContext
from app.modules.licensing.domain.catalogue import EDITION_RATE_LIMIT_MULTIPLIER
from app.modules.licensing.domain.entitlement import EntitlementState, StateReason, days_left
from app.modules.licensing.service.entitlements import EntitlementService
from app.shared.api.ratelimit import RateLimitPolicy, RateLimitPolicyProvider

STATE_HEADER = "SupportX-Licence-State"
GRACE_ENDS_HEADER = "SupportX-Licence-Grace-Ends"
DAYS_LEFT_HEADER = "SupportX-Licence-Days-Left"


AdminCheck = Callable[[TenantContext], Awaitable[bool]]


async def _nobody_is_admin(context: TenantContext) -> bool:
    del context
    return False


class RouteGate:
    """Feature and read-only enforcement for module routes."""

    def __init__(
        self, service: EntitlementService, is_admin: AdminCheck = _nobody_is_admin
    ) -> None:
        self.service = service
        # `licence.manage` through the policy layer (WP-016); only asked during a grace period.
        self.is_admin = is_admin

    async def check_request(
        self, context: TenantContext, *, feature: str | None, write: bool
    ) -> Mapping[str, str]:
        """Raise when blocked; otherwise the warning headers (grace, admins only)."""
        entitlement = await self.service.entitlement(context.tenant_id)
        if feature is not None and not entitlement.has_feature(feature):
            raise EntitlementRequired(params={"feature": feature})
        now = self.service.clock()
        status = entitlement.status(now)
        if write and not status.allows_writes:
            reason = status.reason or StateReason.NO_ENTITLEMENT
            raise ReadOnlyMode(params={"reason": reason.value})
        ends = status.grace_ends_at
        if status.state is EntitlementState.GRACE and ends and await self.is_admin(context):
            return {
                STATE_HEADER: status.state.value,
                GRACE_ENDS_HEADER: ends.isoformat(),
                DAYS_LEFT_HEADER: str(days_left(status, now)),
            }
        return {}


class EntitlementRateLimits:
    """Settings budgets x the edition's multiplier (a tenant without a plan gets x1)."""

    def __init__(self, base: RateLimitPolicyProvider, service: EntitlementService) -> None:
        self.base = base
        self.service = service

    async def policy_for(self, group: str, tenant_id: uuid.UUID) -> RateLimitPolicy:
        """Budgets of `group` for this tenant's edition."""
        policy = await self.base.policy_for(group, tenant_id)
        edition = (await self.service.entitlement(tenant_id)).edition
        factor = EDITION_RATE_LIMIT_MULTIPLIER[edition] if edition is not None else 1
        return RateLimitPolicy(policy.user * factor, policy.tenant * factor, policy.window_seconds)
