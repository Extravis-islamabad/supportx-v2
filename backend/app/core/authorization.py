"""Authorization seam (architecture.md §11.2; WP-016; D-029).

Core cannot import modules, so it defines only the contract; identity_access implements it and
registers it on app.state at startup (like the session resolver and the entitlement gate).

Every API route declares exactly one of:

    dependencies=[Depends(require_permission("users.view"))]   # a catalogue permission
    dependencies=[Depends(require_signed_in())]                  # any signed-in user (own data)
    @public_route                                                # no session at all (health, login)

and a guard test fails for any route that declares none (tests/test_route_permissions.py).
`require_permission` returns the caller's compiled *subject*; services pass it to the policy
service for scope filters, attribute rules, field masking and segregation-of-duties checks.
Without an authorizer (no database in a dev/test run) protected routes answer 503: authorization
never fails open.
"""

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from fastapi import Request

from app.core.errors import ServiceUnavailable
from app.core.tenancy import TenantContext, resolve_tenant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

AUTHORIZER_STATE = "authorizer"
Scope = Literal["all", "site", "group", "own"]
ALL_SCOPES: tuple[Scope, ...] = ("all", "site", "group", "own")

PERMISSION_ATTR = "__supportx_permission__"
SIGNED_IN_ATTR = "__supportx_signed_in__"
PUBLIC_ATTR = "__supportx_public_route__"


@dataclass(frozen=True)
class PermissionSpec:
    """One permission a module offers, e.g. `users.view`.

    `feature` ties it to the licence (WP-009): a tenant without the feature never holds it,
    whatever its roles say. `scopes` lists the scopes a role may grant it with; the first is the
    broadest. Labels live in frontend/packages/labels (`permission.<key>`, `.description`).
    """

    key: str
    feature: str | None = None
    scopes: tuple[Scope, ...] = ("all",)

    @property
    def module(self) -> str:
        """`users.view` → `users` (the group in the role editor)."""
        return self.key.split(".", 1)[0]


class Authorizer(Protocol):
    """Implemented by identity_access (service/policy.py)."""

    async def subject_for(self, request: Request, context: TenantContext) -> Any:  # noqa: ANN401 - the module's Subject type
        """The caller's compiled permissions (memoised per request, cached across requests)."""
        ...

    def require(self, subject: Any, permissions: Sequence[str]) -> None:  # noqa: ANN401
        """Raise 403 `permission_denied` unless the subject holds one of `permissions`."""
        ...

    async def allows(self, context: TenantContext, permission: str) -> bool:
        """Whether the context's user holds `permission` (any scope); for other modules' checks."""
        ...


def _authorizer(request: Request) -> Authorizer:
    authorizer: Authorizer | None = getattr(request.app.state, AUTHORIZER_STATE, None)
    if authorizer is None:
        # The policy needs the database: say so rather than a vaguer "authorization" outage.
        if getattr(request.app.state, "db", None) is None:
            raise ServiceUnavailable(code="database_not_configured")
        raise ServiceUnavailable(code="authorization_unavailable")
    return authorizer


def require_permission(*permissions: str) -> Callable[[Request], Awaitable[Any]]:
    """Route dependency: the caller must hold one of `permissions` (at any scope).

    Returns the caller's subject, for scope filters and resource checks in the service.
    """
    if not permissions:
        msg = "require_permission needs at least one permission"
        raise ValueError(msg)

    async def dependency(request: Request) -> Any:  # noqa: ANN401 - the module's Subject type
        authorizer = _authorizer(request)
        subject = await authorizer.subject_for(request, await resolve_tenant(request))
        authorizer.require(subject, permissions)
        return subject

    setattr(dependency, PERMISSION_ATTR, permissions)
    return dependency


def require_signed_in() -> Callable[[Request], Awaitable[Any]]:
    """Route dependency for a user's own data (session, own profile, the plan summary)."""

    async def dependency(request: Request) -> Any:  # noqa: ANN401 - the module's Subject type
        return await _authorizer(request).subject_for(request, await resolve_tenant(request))

    setattr(dependency, SIGNED_IN_ATTR, True)
    return dependency


def public_route[Endpoint: Callable[..., Any]](endpoint: Endpoint) -> Endpoint:
    """Mark a route that runs without a session (health probes, the login flow)."""
    setattr(endpoint, PUBLIC_ATTR, True)
    return endpoint


def declared_access(
    dependencies: Sequence[Callable[..., Any]], endpoint: Callable[..., Any]
) -> str | None:
    """How a route is protected ('permission:<keys>', 'signed_in', 'public'), or None (guard)."""
    if getattr(endpoint, PUBLIC_ATTR, False):
        return "public"
    for dependency in dependencies:
        keys = getattr(dependency, PERMISSION_ATTR, None)
        if keys is not None:
            return "permission:" + ",".join(keys)
    if any(getattr(dependency, SIGNED_IN_ATTR, False) for dependency in dependencies):
        return "signed_in"
    return None


# --- refreshing compiled permissions after access-relevant changes --------------------------------

AccessInvalidator = Callable[[uuid.UUID], Awaitable[None]]
_invalidators: list[AccessInvalidator] = []


def register_access_invalidator(invalidator: AccessInvalidator) -> None:
    """identity_access registers its cache invalidation at startup (one per running app)."""
    _invalidators.append(invalidator)


def unregister_access_invalidator(invalidator: AccessInvalidator) -> None:
    """Undo `register_access_invalidator` (app shutdown)."""
    if invalidator in _invalidators:
        _invalidators.remove(invalidator)


def access_changed(session: "AsyncSession") -> None:
    """Call in any transaction that changes what users may do (memberships, roles ...).

    Once it commits, compiled permissions of the tenant are refreshed in this process at once;
    other processes follow when the change's event reaches the invalidation consumer.
    """
    from app.core.database import SESSION_TENANT_KEY, after_commit  # noqa: PLC0415 - database imports this module's peers

    context: TenantContext = session.info[SESSION_TENANT_KEY]

    async def refresh() -> None:
        for invalidator in _invalidators:
            await invalidator(context.tenant_id)

    after_commit(session, refresh)
