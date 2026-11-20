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
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace

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
class AgentActor:
    """An AI agent doing work for a person (REQ-AUD-014, WP-057 S4b).

    `key` is the agent's catalogue code, `version` the published version that ran and `tools` the
    tools it may call in this run. The audit log names the agent, with the person on whose behalf
    it acts, never the person alone.
    """

    id: uuid.UUID  # the agent's own ID: the audit's actor (lane B: never a NULL actor)
    key: str
    version: str
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class TenantContext:
    """Who the current work is for: the tenant and the acting user (None for system work)."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID | None = None
    # Realm roles of the session user (tenant_admin, technician, requester). Coarse until the
    # policy layer exists (WP-016); used for admin-only notices such as the licence grace warning.
    roles: frozenset[str] = field(default_factory=frozenset)
    # An API key's call (WP-041, D-128): the key and its scopes. None for a browser session. A key
    # acts as its owner (`user_id`) limited to these scopes; the owner's permissions are live.
    api_key_id: uuid.UUID | None = None
    api_scopes: frozenset[str] | None = None
    # The key's owner is a service account, not a person (WP-057 S4b): the audit names the account.
    service_identity: bool = False
    # Work an AI agent does for `user_id` (WP-057 S4b); None for everything else.
    agent: AgentActor | None = None
    # A vendor support account's session (WP-057 S4c-2): the grant it acts under, so the audit
    # names "Extravis support" and the grant on its every entry. None for everyone else.
    support_grant_id: uuid.UUID | None = None
    # People's e-mail addresses and phones withheld from this request's answers: every vendor
    # support session (D-180, always). Read at every people lookup, so a read without it fails
    # closed for support (set with support_grant_id, never apart).
    mask_contacts: bool = False
    # People's names withheld too (D-180): only when the grant asks for it (its "Mask names too"
    # tick, 0188); names are shown by default.
    mask_names: bool = False


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


# The request's vendor support facts (WP-057 S4c-2): set when the request resolves to a support
# session, read by `tenant_session` so a session the request's code opens for itself is masked and
# tied to the grant too (lane B's #561 review, (2)). Per request task (a copied context), never
# set in workers, so jobs and mail are never masked.
_SUPPORT_REQUEST: ContextVar[TenantContext | None] = ContextVar("support_request", default=None)


def open_support_scope() -> Token[TenantContext | None]:
    """A request starts with no support facts (the request middleware, per request)."""
    return _SUPPORT_REQUEST.set(None)


def close_support_scope(token: Token[TenantContext | None]) -> None:
    """The request is done: whatever it set is gone, so the next request starts clean."""
    _SUPPORT_REQUEST.reset(token)


def support_request() -> TenantContext | None:
    """The current request's support context, if it is a vendor support session's."""
    return _SUPPORT_REQUEST.get()


def with_support(context: TenantContext) -> TenantContext:
    """`context` carrying the request's support facts when it is for the same tenant (fail closed).

    Never removes anything: a context already naming a grant, or another tenant's, is unchanged.
    """
    support = _SUPPORT_REQUEST.get()
    if support is None or context.support_grant_id is not None:
        return context
    if context.tenant_id != support.tenant_id:
        return context
    return replace(
        context,
        support_grant_id=support.support_grant_id,
        mask_contacts=support.mask_contacts,
        mask_names=support.mask_names,
    )


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
    if context.support_grant_id is not None:
        _SUPPORT_REQUEST.set(context)
    setattr(request.state, _REQUEST_CONTEXT_ATTR, context)
    return context
