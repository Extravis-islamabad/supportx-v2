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
from app.core.modules import discover_modules
from app.main import create_app
from app.modules.identity_access.domain.permissions import SYSTEM_ROLES, Catalogue

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / "docs" / "security" / "route-permissions.md"
PERMISSION_PREFIX = "permission:"
# The tenant's first-run answer: technicians see their groups, or everything (D-052, D-073).
TECHNICIAN_SCOPES: tuple[Scope, ...] = ("group", "all")


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


def access_table(app: FastAPI) -> dict[str, str]:
    """`METHOD path` → 'permission:<keys>', 'signed_in', 'public' (or 'None': unprotected)."""
    return {
        f"{method} {path}": str(declared_access(list(route_dependencies(dependant)), endpoint))
        for method, path, dependant, endpoint in api_routes(app)
    }


def build_app() -> FastAPI:
    """The app with every module's routes; nothing connects at build time."""
    return create_app(Settings.load(env_file=None, profile="test", tracing_enabled=False))


def build_catalogue() -> Catalogue:
    """Every module's permissions, as identity_access compiles them at startup."""
    specs = [p for m in discover_modules() for p in m.permissions]
    return Catalogue.build(specs, frozenset(s.feature for s in specs if s.feature))


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _route_rows(table: dict[str, str], catalogue: Catalogue) -> list[str]:
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
        rows.append(f"| {method} | `{_cell(path)}` | {shown} | {scopes} |")
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


def render(table: dict[str, str], catalogue: Catalogue) -> str:
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
            "`signed_in` (the caller's own data, browser session only) or `public` (no session).",
            "Routes carry no machine-readable scope rule of their own: which records a caller",
            "reaches is filtered in the module's service by the scope the caller holds the",
            "permission at. The Scopes column lists the scopes each permission can be granted",
            "with, broadest first (`all`, `site`, `group`, `own`), from the permission catalogue.",
            "",
            "| Method | Path | Access | Scopes |",
            "|---|---|---|---|",
            *_route_rows(table, catalogue),
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
    return render(access_table(build_app()), build_catalogue())


def main() -> int:  # pragma: no cover - thin CLI over the tested generate
    """Write the page."""
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(generate(), encoding="utf-8")
    sys.stdout.write(f"route-permissions: wrote {TARGET.relative_to(REPO)}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
