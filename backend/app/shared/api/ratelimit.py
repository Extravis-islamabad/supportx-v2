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

Routes with nobody signed in (the sign-in flow, public branding, e-mailed action links) have no
user or tenant to count against: `ip_rate_limit` counts per client address instead, with its
budget set where the route is declared. The address is the one uvicorn already resolved through
the trusted proxies (`api.trustedProxies`, app/core/proxies.py), never a raw X-Forwarded-For, so
a client cannot pick its own. The sign-in routes fail closed (audit row 14): with Valkey down they
answer 503 instead of running unlimited. Everything else keeps failing open.
"""

import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

import valkey.exceptions
from fastapi import Depends, Request, Response

from app.core.config import Settings
from app.core.errors import VALKEY_RETRY_AFTER, AppError, RateLimited, ServiceUnavailable
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
# One counter: a client address's (ip_rate_limit). A list, like the script above.
_ONE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {count}
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

    async def hit_address(
        self, group: str, address: str, limit: int, window_seconds: int
    ) -> Decision:
        """Count one request from a client address against `limit` per `window_seconds`.

        Its own key space (`rlip:`), so it never shares a counter with a user's or tenant's. The
        address is hashed: Valkey keys are listed by operators, and an IP address is personal data.
        """
        now = self.clock()
        window = int(now // window_seconds)
        reset = max(1, int((window + 1) * window_seconds - now))
        subject = hashlib.sha256(address.encode()).hexdigest()[:32]
        (count,) = await self.client.eval(
            _ONE_SCRIPT, 1, f"{self.prefix}rlip:{group}:{window}:{subject}", reset + 1
        )
        left = limit - int(count)
        return Decision(
            allowed=left >= 0,
            limit=limit,
            remaining=max(0, left),
            reset_seconds=reset,
            window_seconds=window_seconds,
        )


@dataclass(frozen=True)
class AddressLimit:
    """One request's count against its address budget (`ip_rate_limit`).

    `refusal`: the error to answer with, or None when allowed. `headers`: the RateLimit-* headers
    for the response. A route that returns its own Response object (a redirect) must copy them
    on, since FastAPI only merges the injected response's headers into a returned value.
    """

    refusal: AppError | None
    headers: dict[str, str]


async def _address_outcome(
    request: Request, group: str, limit: int, window_seconds: int, fail_closed_code: str | None
) -> AddressLimit:
    limiter: RateLimiter | None = getattr(request.app.state, RATE_LIMITER_STATE, None)
    if limiter is None:
        return AddressLimit(None, {})  # disabled, or no Valkey configured
    try:
        decision = await limiter.hit_address(group, client_address(request), limit, window_seconds)
    except (valkey.exceptions.ValkeyError, OSError):
        log.warning("rate_limit_unavailable", group=group, fail_closed=bool(fail_closed_code))
        if fail_closed_code is None:
            return AddressLimit(None, {})
        refusal = ServiceUnavailable(
            code=fail_closed_code, headers={"Retry-After": VALKEY_RETRY_AFTER}
        )
        return AddressLimit(refusal, {})
    if decision.allowed:
        return AddressLimit(None, decision.headers())
    limited = RateLimited(
        params={"retry_after_seconds": decision.reset_seconds}, headers=decision.headers()
    )
    return AddressLimit(limited, {})


def client_address(request: Request) -> str:
    """The client's address as uvicorn resolved it through the trusted proxies only."""
    return request.client.host if request.client else "unknown"


def ip_rate_limit(
    group: str,
    limit: int,
    *,
    window_seconds: int = 60,
    fail_closed_code: str | None = None,
    defer: bool = False,
) -> Any:  # noqa: ANN401 - returns a FastAPI dependency
    """Dependency counting per client address, for routes with nobody signed in.

    `limit` requests per `window_seconds` from one address; then 429 `rate_limited` with
    Retry-After. RateLimit-* headers as `rate_limit`, on routes that return a value; a route that
    builds its own Response object gets them only if it copies them on (see `AddressLimit`).

    `fail_closed_code`: with Valkey unreachable, refuse with 503 and this (labelled) code instead
    of letting the request through. Only for the sign-in routes (audit row 14): they hit Valkey
    anyway (the login state lives there), so failing open would buy nothing but a flood.

    `defer`: return the refusal (in the `AddressLimit` it yields) instead of raising it, for a
    route that answers it itself (the sign-in routes send a browser back to its app with a label
    code, never a JSON page).
    """

    async def dependency(request: Request, response: Response) -> AddressLimit:
        outcome = await _address_outcome(request, group, limit, window_seconds, fail_closed_code)
        if outcome.refusal is not None and not defer:
            raise outcome.refusal
        response.headers.update(outcome.headers)
        return outcome

    return dependency


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
