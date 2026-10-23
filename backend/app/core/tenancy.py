"""Request-scoped tenant context (architecture.md §7.2, §11.1; CLAUDE.md rule a).

The tenant (and user) of a request is resolved once, kept in a `TenantContext`, bound into every
log line, and written into each database transaction as `app.tenant_id` / `app.user_id` (see
app/core/database.py), where PostgreSQL row-level security enforces it.

Resolution order:
1. the login session (the identity_access module registers a `SessionResolver` on app.state at
   startup; core never imports modules);
2. only when there is no session, and only if SUPPORTX_DEV_TENANT_HEADER=true in the dev or test
   profile: the `X-Tenant-ID` header. Production ignores the header whatever the settings say;
3. otherwise 401 `unauthenticated`.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog
from fastapi import Request

from app.core.config import Settings
from app.core.errors import BadRequest, Unauthenticated

TENANT_HEADER = "X-Tenant-ID"
SESSION_RESOLVER_STATE = "session_resolver"
# request.state attribute holding the resolved context: the route guards (app/core/entitlements.py)
# resolve the tenant outside FastAPI's dependency cache, so resolution is memoised per request.
_REQUEST_CONTEXT_ATTR = "tenant_context"


@dataclass(frozen=True)
class TenantContext:
    """Who the current work is for: the tenant and the acting user (None for system work)."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID | None = None
    # Realm roles of the session user (tenant_admin, technician, requester). Coarse until the
    # policy layer exists (WP-016); used for admin-only notices such as the licence grace warning.
    roles: frozenset[str] = field(default_factory=frozenset)


# Returns the session's context, None when the request has no session, or raises a problem
# (expired session, CSRF failure ...). Registered by identity_access.
SessionResolver = Callable[[Request], Awaitable[TenantContext | None]]


def tenant_from_header(settings: Settings, header_value: str | None) -> TenantContext | None:
    """Tenant from X-Tenant-ID if the dev-only switch allows it; None otherwise."""
    if not settings.tenant_header_enabled or header_value is None:
        return None
    try:
        return TenantContext(tenant_id=uuid.UUID(header_value.strip()))
    except ValueError as exc:
        raise BadRequest(code="invalid_tenant_id") from exc


async def resolve_tenant(request: Request) -> TenantContext:
    """FastAPI dependency: the tenant (and user) of this request, or 401 `unauthenticated`."""
    cached: TenantContext | None = getattr(request.state, _REQUEST_CONTEXT_ATTR, None)
    if cached is not None:
        return cached
    context: TenantContext | None = None
    resolver: SessionResolver | None = getattr(request.app.state, SESSION_RESOLVER_STATE, None)
    if resolver is not None:
        context = await resolver(request)
    if context is None:
        settings: Settings = request.app.state.settings
        context = tenant_from_header(settings, request.headers.get(TENANT_HEADER))
    if context is None:
        raise Unauthenticated
    structlog.contextvars.bind_contextvars(
        tenant_id=str(context.tenant_id),
        user_id=str(context.user_id) if context.user_id else None,
    )
    setattr(request.state, _REQUEST_CONTEXT_ATTR, context)
    return context
