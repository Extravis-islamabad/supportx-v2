"""Route guard seam for entitlements (architecture.md §13.1, §13.6; WP-009; CLAUDE.md rule f).

Core cannot import modules, so it only defines the hook. The module registry wraps every module's
routers with `route_guard(spec.feature)`; the licensing module registers the real
`EntitlementGate` on app.state at startup. For each request the guard then:

1. skips routes marked `@entitlement_exempt` (health probes, the login flow: no tenant yet);
2. resolves the tenant (memoised per request, see app/core/tenancy.py);
3. asks the gate, which raises 403 `entitlement_required` when the module's feature is not in the
   tenant's plan, and 403 `read_only_mode` for a write (any method but GET/HEAD/OPTIONS) while the
   tenant is read-only, unless the route is marked `@read_only_exempt` (exports, logout);
4. copies the headers the gate returns (the grace-period warning) onto the response.

Without a gate (no licensing module, or no database in a dev/test run) requests pass: the
production profile always has a database, so the gate is always installed there.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from fastapi import Request, Response

from app.core.tenancy import TenantContext, resolve_tenant

ENTITLEMENT_GATE_STATE = "entitlement_gate"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_EXEMPT_ATTR = "__supportx_entitlement_exempt__"
_READ_ONLY_EXEMPT_ATTR = "__supportx_read_only_exempt__"


class EntitlementGate(Protocol):
    """What the guard asks per request; implemented by the licensing module."""

    async def check_request(
        self, context: TenantContext, *, feature: str | None, write: bool
    ) -> Mapping[str, str]:
        """Raise the problem that blocks this request, or return headers to add to the response."""
        ...


def entitlement_exempt[Endpoint: Callable[..., Any]](endpoint: Endpoint) -> Endpoint:
    """Mark a route as outside entitlement checks (no tenant needed: health, login flow)."""
    setattr(endpoint, _EXEMPT_ATTR, True)
    return endpoint


def read_only_exempt[Endpoint: Callable[..., Any]](endpoint: Endpoint) -> Endpoint:
    """Mark a non-GET route that must keep working in read-only mode (exports, logout)."""
    setattr(endpoint, _READ_ONLY_EXEMPT_ATTR, True)
    return endpoint


def route_guard(feature: str | None) -> Callable[[Request, Response], Awaitable[None]]:
    """Dependency the module registry adds to every route of a module needing `feature`."""

    async def guard(request: Request, response: Response) -> None:
        endpoint = request.scope.get("endpoint")
        if getattr(endpoint, _EXEMPT_ATTR, False):
            return
        gate: EntitlementGate | None = getattr(request.app.state, ENTITLEMENT_GATE_STATE, None)
        if gate is None:
            return
        context = await resolve_tenant(request)
        write = request.method not in SAFE_METHODS and not getattr(
            endpoint, _READ_ONLY_EXEMPT_ATTR, False
        )
        headers = await gate.check_request(context, feature=feature, write=write)
        response.headers.update(headers)

    return guard
