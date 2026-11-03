"""Every holder of settings.manage keeps every right (WP-042, REQ-ADM-019; coordinator, Q1).

The per-area configure rights (`config.<area>`) are added beside settings.manage, never instead
of it: every route that accepts a configure right also accepts settings.manage. Permanent.
"""

from typing import Any

from app.core.authorization import PERMISSION_ATTR
from app.core.modules import ModuleRegistry, discover_modules
from app.main import create_app
from conftest import make_settings


def route_permissions(dependant: Any) -> list[tuple[str, ...]]:  # noqa: ANN401 - FastAPI's Dependant
    """The permission keys each permission dependency of a route accepts (any one suffices)."""
    found: list[tuple[str, ...]] = []
    for child in dependant.dependencies:
        keys = getattr(child.call, PERMISSION_ATTR, None)
        if keys is not None:
            found.append(tuple(keys))
        found += route_permissions(child)
    return found


def all_routes(routes: list[Any]) -> list[Any]:
    """Every route, inside mounted sub-applications too (the API lives under /api/v1)."""
    found: list[Any] = []
    for route in routes:
        if getattr(route, "dependant", None) is not None:
            found.append(route)
            continue
        # Included routers (FastAPI keeps the original) and mounted applications.
        holder = getattr(route, "original_router", None) or getattr(route, "app", None)
        inner = getattr(holder, "routes", None)
        if inner is not None:
            found += all_routes(list(inner))
    return found


def test_every_route_taking_a_configure_right_still_takes_settings_manage() -> None:
    app = create_app(make_settings(), ModuleRegistry.from_specs(discover_modules()))
    narrowed = []
    configured = 0
    for route in all_routes(list(app.routes)):
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for keys in route_permissions(dependant):
            if any(key.startswith("config.") for key in keys):
                configured += 1
                if "settings.manage" not in keys:
                    narrowed.append(f"{getattr(route, 'path', route)}: {keys}")
    assert configured > 0  # the test looks at real routes
    assert narrowed == []
