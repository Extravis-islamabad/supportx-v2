"""Guard: every API route counts against a rate-limit budget (audit #14; architecture.md §10).

A route is limited when `rate_limit(group)`, or `ip_rate_limit(...)` for routes with nobody
signed in (lane B's #447), is among its dependencies (app/shared/api/ratelimit.py).
KNOWN_UNLIMITED lists today's exceptions, each with its owning module. It is a ratchet:

- a new route without a limit fails here;
- a listed route that gains a limit, or is renamed or removed, fails too: no stale rows;
- the list never grows: whoever fixes a route deletes its row AND lowers PINNED in the same PR.

Some of these may stay unlimited for a reason (health probes); say so in the row's comment.
"""

from fastapi import FastAPI

from app.main import create_app
from conftest import make_settings
from tests.test_route_permissions import _dependencies, api_routes

# Lower this in the same PR that removes a row; never raise it.
PINNED = 16

KNOWN_UNLIMITED = frozenset(
    {
        "GET /api/v1/account/security",  # identity_access.api.account
        "GET /api/v1/auth/dev/personas",  # identity_access.bff.quick
        "POST /api/v1/auth/dev/sign-in",  # identity_access.bff.quick
        "GET /api/v1/realtime/lists/{name}",  # identity_access.bff.realtime
        "POST /api/v1/realtime/connection-token",  # identity_access.bff.realtime
        "POST /api/v1/realtime/subscription-token",  # identity_access.bff.realtime
        "DELETE /api/v1/auth/sessions/{listed_id}",  # identity_access.bff.routes
        "GET /api/v1/auth/account-action",  # identity_access.bff.routes
        "GET /api/v1/auth/me",  # identity_access.bff.routes
        "GET /api/v1/auth/sessions",  # identity_access.bff.routes
        "POST /api/v1/auth/logout",  # identity_access.bff.routes
        "POST /api/v1/auth/mobile/exchange",  # identity_access.bff.routes
        "POST /api/v1/auth/password-reset",  # identity_access.bff.routes
        "POST /api/v1/auth/switch-tenant",  # identity_access.bff.routes
        "GET /api/v1/health",  # system: a probe; kubelet calls it, never limited
        "GET /api/v1/ready",  # system: a probe; a 429 would fail readiness, never limited
    }
)


def _limited(dependant: object) -> bool:
    return any(
        getattr(call, "__qualname__", "").startswith(("rate_limit.", "ip_rate_limit."))
        for call in _dependencies(dependant)
    )


def unlimited_routes(app: FastAPI) -> set[str]:
    """`METHOD path` of every API route with no rate-limit dependency."""
    return {
        f"{method} {path}"
        for method, path, dependant, _ in api_routes(app)
        if not _limited(dependant)
    }


def test_every_route_is_rate_limited_or_a_known_exception() -> None:
    app = create_app(make_settings())
    found = unlimited_routes(app)
    assert len(list(api_routes(app))) > 500  # the walker really sees the routes
    assert sorted(found - KNOWN_UNLIMITED) == [], "new routes without rate_limit(group)"
    assert sorted(KNOWN_UNLIMITED - found) == [], "fixed, renamed or removed: delete the row"


def test_the_exception_list_only_shrinks() -> None:
    assert len(KNOWN_UNLIMITED) <= PINNED


def test_the_automation_and_custom_field_routes_are_limited() -> None:
    """Audit #14's lane C part: the workflow designer and custom fields, every method."""
    app = create_app(make_settings())
    paths = {
        f"{method} {path}"
        for method, path, _, _ in api_routes(app)
        if path.startswith(("/api/v1/automation", "/api/v1/custom-fields"))
    }
    assert len(paths) > 40
    assert paths.isdisjoint(unlimited_routes(app))
