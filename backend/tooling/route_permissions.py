"""`make route-permissions`: the route-permission map and role matrix, from code (D-168).

Writes docs/security/route-permissions.md (committed and code-owned): every /api/v1 route with the
access it declares (`require_permission`, `require_signed_in`, `@public_route`), and every built-in
role's permissions at the scope it holds them. D-168 owns this file instead of every module's
api/ folder: a new route or a changed permission changes the map, so it needs the security
review, while feature PRs that leave access alone don't. tests/test_route_permission_map.py fails
when the committed file is stale; tests/test_route_permissions.py uses the same route walker.
"""

import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from app.core.authorization import Scope, declared_access
from app.core.config import Settings
from app.core.entitlements import FEATURE_ATTR, MODULE_LEVEL, ROUTE_LEVEL
from app.core.modules import discover_modules
from app.main import create_app
from app.modules.identity_access.bff.routes import current_session
from app.modules.identity_access.domain.permissions import SYSTEM_ROLES, Catalogue

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / "docs" / "security" / "route-permissions.md"
PERMISSION_PREFIX = "permission:"
# The tenant's first-run answer: technicians see their groups, or everything (D-052, D-073).
TECHNICIAN_SCOPES: tuple[Scope, ...] = ("group", "all")
# A `@public_route` that still takes the BFF's own session dependency (`CurrentSession`: /auth/me,
# /auth/logout, /auth/sessions ...) answers 401 without a valid session cookie. Shown as 'public'
# a reviewer would read it as open to anyone, so the map names what it really checks.
BFF_SESSION = "session (BFF)"


def route_dependencies(dependant: Any) -> Iterator[Callable[..., Any]]:  # noqa: ANN401 - FastAPI Dependant
    """Every dependency callable of a route, nested ones included."""
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
        if declared_access(list(route_dependencies(dependant)), endpoint) is None
    ]


def route_access(dependant: Any, endpoint: Callable[..., Any]) -> str:  # noqa: ANN401 - FastAPI Dependant
    """The access a route declares; a public route behind the BFF session shows as BFF_SESSION."""
    dependencies = list(route_dependencies(dependant))
    access = declared_access(dependencies, endpoint)
    # By the dependency callable itself (FastAPI's resolved graph), not by parameter names.
    if access == "public" and any(call is current_session for call in dependencies):
        return BFF_SESSION
    return str(access)


def access_table(app: FastAPI) -> dict[str, str]:
    """`METHOD path` → 'permission:<keys>', 'signed_in', 'session (BFF)', 'public' or 'None'.

    'None' marks an unprotected route (tests/test_route_permissions.py fails on any).
    """
    return {
        f"{method} {path}": route_access(dependant, endpoint)
        for method, path, dependant, endpoint in api_routes(app)
    }


# The Feature column's sources, in the order shown: the module's (or router's) feature, a single
# route's `requires_feature`, and the licence feature of each permission the route accepts.
PERMISSION_LEVEL = "permission"
LEVELS = (MODULE_LEVEL, ROUTE_LEVEL, PERMISSION_LEVEL)


def declared_features(dependant: Any) -> list[tuple[str, str]]:  # noqa: ANN401 - FastAPI Dependant
    """(feature, level) of every entitlement guard on a route (app/core/entitlements.py)."""
    found: list[tuple[str, str]] = []
    for call in route_dependencies(dependant):
        tag = getattr(call, FEATURE_ATTR, None)
        if isinstance(tag, tuple) and len(tag) == 2 and tag[0] is not None:  # noqa: PLR2004 - (feature, level)
            found.append((str(tag[0]), str(tag[1])))
    return found


def feature_table(app: FastAPI, catalogue: Catalogue) -> dict[str, str]:
    """`METHOD path` → the Feature cell: each feature once, with the levels that name it."""
    table: dict[str, str] = {}
    for method, path, dependant, endpoint in api_routes(app):
        named = declared_features(dependant)
        access = route_access(dependant, endpoint)
        if access.startswith(PERMISSION_PREFIX):
            for key in access.removeprefix(PERMISSION_PREFIX).split(","):
                spec = catalogue.get(key)
                if spec is not None and spec.feature is not None:
                    named.append((spec.feature, PERMISSION_LEVEL))
        levels: dict[str, set[str]] = {}
        for feature, level in named:
            levels.setdefault(feature, set()).add(level)
        table[f"{method} {path}"] = (
            "; ".join(
                f"`{feature}` ({', '.join(lv for lv in LEVELS if lv in levels[feature])})"
                for feature in sorted(levels)
            )
            or "-"
        )
    return table


def build_app() -> FastAPI:
    """The app with every module's routes; nothing connects at build time."""
    return create_app(Settings.load(env_file=None, profile="test", tracing_enabled=False))


def build_catalogue() -> Catalogue:
    """Every module's permissions, as identity_access compiles them at startup."""
    specs = [p for m in discover_modules() for p in m.permissions]
    return Catalogue.build(specs, frozenset(s.feature for s in specs if s.feature))


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _route_rows(table: dict[str, str], catalogue: Catalogue, features: dict[str, str]) -> list[str]:
    rows = []
    for route in sorted(table, key=lambda r: (r.split(" ", 1)[1], r.split(" ", 1)[0])):
        method, path = route.split(" ", 1)
        access = table[route]
        if access.startswith(PERMISSION_PREFIX):
            keys = access.removeprefix(PERMISSION_PREFIX).split(",")
            shown = " or ".join(f"`{k}`" for k in keys)
            scopes = "; ".join(
                f"{k}: {'/'.join(spec.scopes)}" if (spec := catalogue.get(k)) else f"{k}: unknown"
                for k in keys
            )
        else:
            shown, scopes = access, "-"
        feature = _cell(features.get(route, "-"))
        rows.append(f"| {method} | `{_cell(path)}` | {shown} | {scopes} | {feature} |")
    return rows


def _role_rows(catalogue: Catalogue) -> list[str]:
    by_answer: dict[str, dict[str, dict[str, list[str]]]] = {}
    for answer in TECHNICIAN_SCOPES:
        for role in SYSTEM_ROLES:
            grants = catalogue.system_grants(role, technician_scope=answer)
            found = by_answer.setdefault(role, {})
            for key in sorted({k for k, _ in grants}):
                found.setdefault(key, {})[answer] = sorted({s for k, s in grants if k == key})
    rows = []
    for role in sorted(by_answer):
        for key in sorted(by_answer[role]):
            held = by_answer[role][key]
            cells = [", ".join(held.get(answer, [])) or "-" for answer in TECHNICIAN_SCOPES]
            rows.append(f"| {role} | `{key}` | {cells[0]} | {cells[1]} |")
    return rows


def render(
    table: dict[str, str], catalogue: Catalogue, features: dict[str, str] | None = None
) -> str:
    """The Markdown page: routes sorted by path then method, roles by role then permission."""
    return "\n".join(
        [
            "# Route permissions and role matrix",
            "",
            "<!-- Generated by `make route-permissions` (backend/tooling/route_permissions.py).",
            "Do not edit: tests/test_route_permission_map.py fails when this file is stale. -->",
            "",
            "Code-owned (D-168): a new route, a changed route permission, a new permission or a",
            "changed role default changes this file, so it needs the security review.",
            "",
            "## Routes",
            "",
            "Access is what the route declares: one of the listed permissions (any scope),",
            "`signed_in` (the caller's own data, browser session only), `session (BFF)` (the",
            "sign-in layer's own routes: a valid session cookie, CSRF-checked on changes, or 401)",
            "or `public` (no session).",
            "Routes carry no machine-readable scope rule of their own: which records a caller",
            "reaches is filtered in the module's service by the scope the caller holds the",
            "permission at. The Scopes column lists the scopes each permission can be granted",
            "with, broadest first (`all`, `site`, `group`, `own`), from the permission catalogue.",
            "The Feature column is the licence feature a tenant's plan needs for the route",
            "(403 `entitlement_required` otherwise) and where it is declared: `module` (the",
            "module's or router's feature), `route` (`requires_feature` on that route) or",
            "`permission` (the feature of a permission the route accepts). A check made only",
            "inside a service is not shown here: declare it on the route too.",
            "",
            "| Method | Path | Access | Scopes | Feature |",
            "|---|---|---|---|---|",
            *_route_rows(table, catalogue, features or {}),
            "",
            "## Built-in roles",
            "",
            "Every built-in role's permissions and the scopes it holds them at, computed from the",
            "permission catalogue (each module's defaults) as at sign-in. Two columns: the",
            "tenant's first-run answer, technicians see their groups' records (`group`) or",
            "everything (`all`); `-` means the role lacks the permission under that answer.",
            "Pinned separately by app/modules/identity_access/tests/role_matrix.json.",
            "",
            "| Role | Permission | Technicians see their groups | Technicians see everything |",
            "|---|---|---|---|",
            *_role_rows(catalogue),
            "",
        ]
    )


def generate() -> str:
    """The page for the current code."""
    app = build_app()
    catalogue = build_catalogue()
    return render(access_table(app), catalogue, feature_table(app, catalogue))


def main() -> int:  # pragma: no cover - thin CLI over the tested generate
    """Write the page."""
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(generate(), encoding="utf-8")
    sys.stdout.write(f"route-permissions: wrote {TARGET.relative_to(REPO)}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
