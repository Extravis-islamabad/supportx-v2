"""Rate limiting per user (or API token) and per tenant, in Valkey (architecture.md §10; WP-008).

Each route group has two budgets per window (default 60 s): one for the calling user and one for
the whole tenant. A request uses one unit of each; when either is exhausted the API answers 429
`rate_limited` with `Retry-After`. Every limited response carries the headers of the tighter
budget:

    RateLimit-Limit: 600        RateLimit-Remaining: 597        RateLimit-Reset: 41
    RateLimit-Policy: 600;w=60

Counting is a fixed window per (group, scope, subject, window number), done by one Lua script so
both counters move atomically. A burst of up to 2 x limit is possible across a window boundary;
that is the accepted trade-off for one round trip and O(1) memory per subject.

Budgets come from a `RateLimitPolicyProvider`. The default reads SUPPORTX_RATE_LIMITS; WP-009 can
install a provider that raises them by licence tier (entitlement interface) without touching any
endpoint. If Valkey is unreachable the request is allowed and a warning is logged: losing rate
limiting briefly is better than losing the API.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

import valkey.exceptions
from fastapi import Depends, Request, Response

from app.core.config import Settings
from app.core.errors import RateLimited
from app.core.logging import get_logger
from app.core.tenancy import TenantContext, resolve_tenant

log = get_logger(__name__)

RATE_LIMITER_STATE = "rate_limiter"
_SCRIPT = """
local function hit(key, ttl)
  local count = redis.call('INCR', key)
  if count == 1 then redis.call('EXPIRE', key, ttl) end
  return count
end
return {hit(KEYS[1], ARGV[1]), hit(KEYS[2], ARGV[1])}
"""


@dataclass(frozen=True)
class RateLimitPolicy:
    """Budgets for one route group."""

    user: int
    tenant: int
    window_seconds: int


class RateLimitPolicyProvider(Protocol):
    """Where budgets come from (settings now; licence entitlements later, WP-009)."""

    async def policy_for(self, group: str, tenant_id: uuid.UUID) -> RateLimitPolicy:
        """Budgets of `group` for this tenant."""
        ...


class SettingsPolicyProvider:
    """Budgets from SUPPORTX_RATE_LIMITS (group → {user, tenant}), falling back to "default"."""

    def __init__(self, settings: Settings) -> None:
        self._limits = settings.rate_limits
        self._window = settings.rate_limit_window_seconds

    async def policy_for(self, group: str, tenant_id: uuid.UUID) -> RateLimitPolicy:
        """Same budgets for every tenant until entitlements exist."""
        del tenant_id
        default = self._limits.get("default", {"user": 600, "tenant": 6000})
        values = {**default, **self._limits.get(group, {})}
        return RateLimitPolicy(values["user"], values["tenant"], self._window)


@dataclass(frozen=True)
class Decision:
    """Outcome of one request against both budgets."""

    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    window_seconds: int

    def headers(self) -> dict[str, str]:
        """RateLimit-* headers (plus Retry-After when refused)."""
        headers = {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(self.remaining),
            "RateLimit-Reset": str(self.reset_seconds),
            "RateLimit-Policy": f"{self.limit};w={self.window_seconds}",
        }
        if not self.allowed:
            headers["Retry-After"] = str(self.reset_seconds)
        return headers


class RateLimiter:
    """Counts requests in Valkey."""

    def __init__(
        self,
        client: Any,  # noqa: ANN401 - valkey.asyncio.Valkey; valkey-py ships no type hints
        *,
        prefix: str,
        provider: RateLimitPolicyProvider,
        clock: Any = time.time,  # noqa: ANN401 - Callable[[], float]; tests pass a fake
    ) -> None:
        self.client = client
        self.prefix = prefix
        self.provider = provider
        self.clock = clock

    async def hit(self, group: str, tenant_id: uuid.UUID, subject: str) -> Decision:
        """Count one request; the decision for the tighter of the two budgets."""
        policy = await self.provider.policy_for(group, tenant_id)
        now = self.clock()
        window = int(now // policy.window_seconds)
        reset = max(1, int((window + 1) * policy.window_seconds - now))
        base = f"{self.prefix}rl:{group}:{window}"
        user_count, tenant_count = await self.client.eval(
            _SCRIPT, 2, f"{base}:u:{tenant_id}:{subject}", f"{base}:t:{tenant_id}", reset + 1
        )
        user_left = policy.user - int(user_count)
        tenant_left = policy.tenant - int(tenant_count)
        limit, left = (
            (policy.user, user_left) if user_left <= tenant_left else (policy.tenant, tenant_left)
        )
        return Decision(
            allowed=user_left >= 0 and tenant_left >= 0,
            limit=limit,
            remaining=max(0, left),
            reset_seconds=reset,
            window_seconds=policy.window_seconds,
        )


def rate_limit(group: str) -> Any:  # noqa: ANN401 - returns a FastAPI dependency
    """Dependency for a route group: `dependencies=[Depends(rate_limit("users"))]`."""

    async def dependency(
        request: Request,
        response: Response,
        tenant: Annotated[TenantContext, Depends(resolve_tenant)],
    ) -> None:
        limiter: RateLimiter | None = getattr(request.app.state, RATE_LIMITER_STATE, None)
        if limiter is None:
            return  # disabled, or no Valkey configured
        # API tokens (integrations) will be their own subject once they exist (WP-006 stub).
        subject = str(tenant.user_id) if tenant.user_id else "anonymous"
        try:
            decision = await limiter.hit(group, tenant.tenant_id, subject)
        except (valkey.exceptions.ValkeyError, OSError):
            log.warning("rate_limit_unavailable", group=group)
            return
        if not decision.allowed:
            raise RateLimited(
                params={"retry_after_seconds": decision.reset_seconds},
                headers=decision.headers(),
            )
        response.headers.update(decision.headers())

    return dependency
