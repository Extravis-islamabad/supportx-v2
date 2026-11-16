"""Guard: every API route declares who may call it (WP-016, architecture.md §11.2).

A route must have `require_permission(...)` or `require_signed_in()` among its dependencies, or
be marked `@public_route` (health probes, the login flow). A route with none fails here: no
endpoint can ship without an authorization decision. The route walker lives in
tooling/route_permissions.py, which also writes the code-owned route-permission map (D-168).
"""

from fastapi import APIRouter, Depends

from app.core.authorization import public_route, require_permission
from app.core.modules import ModuleRegistry, ModuleSpec, discover_modules
from app.main import create_app
from conftest import make_settings
from tooling.route_permissions import access_table, unprotected_routes


def test_every_route_declares_its_access() -> None:
    app = create_app(make_settings())
    assert len(access_table(app)) > 25  # the walker really sees the routes
    assert unprotected_routes(app) == []


def test_the_admin_api_requires_the_right_permissions() -> None:
    table = access_table(create_app(make_settings()))
    assert table["GET /api/v1/users"] == "permission:users.view"
    assert table["POST /api/v1/roles"] == "permission:roles.manage"
    assert table["PUT /api/v1/users/{user_id}/roles/{role_id}"] == "permission:users.manage"
    assert table["PATCH /api/v1/users/{user_id}"] == "permission:profile.edit"
    assert table["GET /api/v1/entitlements"] == "signed_in"
    assert table["GET /api/v1/health"] == "public"
    # @public_route with the BFF session dependency (CurrentSession): 401 without a session.
    assert table["POST /api/v1/auth/logout"] == "session (BFF)"
    assert table["GET /api/v1/auth/me"] == "session (BFF)"
    assert table["GET /api/v1/auth/callback"] == "public"


def test_the_guard_catches_an_unprotected_route() -> None:
    probe = APIRouter(prefix="/probe")

    @probe.get("/open")
    async def open_route() -> dict[str, str]:
        return {}

    @probe.get("/closed", dependencies=[Depends(require_permission("users.view"))])
    async def closed_route() -> dict[str, str]:
        return {}

    @probe.get("/public")
    @public_route
    async def public() -> dict[str, str]:
        return {}

    registry = ModuleRegistry.from_specs(
        [*discover_modules(), ModuleSpec(name="probe", routers=[probe])]
    )
    assert unprotected_routes(create_app(make_settings(), registry)) == ["GET /api/v1/probe/open"]
