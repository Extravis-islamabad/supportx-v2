"""Guard: every API route declares who may call it (WP-016, architecture.md §11.2).

A route must have `require_permission(...)` or `require_signed_in()` among its dependencies, or
be marked `@public_route` (health probes, the login flow). A route with none fails here: no
endpoint can ship without an authorization decision.
"""

from collections.abc import Callable, Iterator
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from app.core.authorization import declared_access, public_route, require_permission
from app.core.modules import ModuleRegistry, ModuleSpec, discover_modules
from app.main import create_app
from conftest import make_settings


def _dependencies(dependant: Any) -> Iterator[Callable[..., Any]]:  # noqa: ANN401 - FastAPI Dependant
    stack = list(dependant.dependencies)
    while stack:
        current = stack.pop()
        if current.call is not None:
            yield current.call
        stack.extend(current.dependencies)


def api_routes(app: FastAPI) -> Iterator[tuple[str, str, Any, Callable[..., Any]]]:
    """(method, path, dependant, endpoint) of every API route, included routers flattened."""
    for context in iter_route_contexts(app.routes):
        if not isinstance(context.original_route, APIRoute) or not str(context.path).startswith(
            "/api/v1"
        ):
            continue
        endpoint = context.endpoint
        if endpoint is None:  # pragma: no cover - API routes always have one
            continue
        for method in sorted(context.methods or ()):
            yield method, str(context.path), context.dependant, endpoint


def unprotected_routes(app: FastAPI) -> list[str]:
    """`METHOD path` of every route without a declared access rule."""
    return [
        f"{method} {path}"
        for method, path, dependant, endpoint in api_routes(app)
        if declared_access(list(_dependencies(dependant)), endpoint) is None
    ]


def access_table(app: FastAPI) -> dict[str, str]:
    return {
        f"{method} {path}": str(declared_access(list(_dependencies(dependant)), endpoint))
        for method, path, dependant, endpoint in api_routes(app)
    }


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
