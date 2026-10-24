"""Architecture tests for the audit log (WP-018, REQ-AUD-002 AC2, REQ-AUD-008 AC2).

* Every privileged write route is audited: a non-GET route that needs an administrative
  permission, or is a record action of REQ-WI-021, must carry `audited(...)`. A new admin route
  without it fails here, so coverage cannot silently drift.
* Nothing can change or delete an audit entry: the audit API has no such route.
"""

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, FastAPI

from app.core.authorization import declared_access, require_permission
from app.core.modules import ModuleRegistry, ModuleSpec, discover_modules
from app.main import create_app
from app.modules.audit.domain.catalogue import ACTIONS
from app.modules.audit.service.recording import AUDIT_ATTR, AuditRouteSpec
from conftest import make_settings
from tests.test_route_permissions import _dependencies, api_routes

# Permissions that make a write administrative (users, roles, organisation, settings, audit).
ADMIN_PERMISSIONS = frozenset(
    {
        "users.manage",
        "roles.manage",
        "sites.manage",
        "groups.manage",
        "settings.manage",
        "audit.manage",
        "audit.verify",
        "audit.export",
    }
)
# Record actions of REQ-WI-021 that are privileged whoever holds the permission.
RECORD_ACTIONS = (("DELETE", "/{record_id}"), ("POST", "/{record_id}/restore"))
# Writes with an administrative permission that are deliberately not audited: none today.
NOT_AUDITED: frozenset[str] = frozenset()


def _audit_spec(dependant: Any) -> AuditRouteSpec | None:  # noqa: ANN401 - FastAPI Dependant
    for call in _dependencies(dependant):
        spec = getattr(call, AUDIT_ATTR, None)
        if isinstance(spec, AuditRouteSpec):
            return spec
    return None


def _privileged(method: str, path: str, access: str) -> bool:
    if method == "GET":
        return False
    if (
        access.startswith("permission:")
        and set(access.split(":", 1)[1].split(",")) & ADMIN_PERMISSIONS
    ):
        return True
    return any(method == m and path.endswith(suffix) for m, suffix in RECORD_ACTIONS)


def privileged_routes(app: FastAPI) -> Iterator[tuple[str, AuditRouteSpec | None]]:
    for method, path, dependant, endpoint in api_routes(app):
        access = str(declared_access(list(_dependencies(dependant)), endpoint))
        if _privileged(method, path, access):
            yield f"{method} {path}", _audit_spec(dependant)


def test_every_privileged_write_is_audited() -> None:
    app = create_app(make_settings())
    found = dict(privileged_routes(app))
    assert found, "no privileged routes found: the filter is wrong"
    missing = sorted(
        route for route, spec in found.items() if spec is None and route not in NOT_AUDITED
    )
    assert missing == []


def test_audited_routes_name_registered_actions() -> None:
    app = create_app(make_settings())
    for route, spec in privileged_routes(app):
        if spec is not None:
            assert spec.action_code in ACTIONS, route


def test_the_check_catches_an_unaudited_admin_route() -> None:
    from fastapi import Depends  # noqa: PLC0415 - local to the synthetic module

    router = APIRouter()

    @router.post(
        "/synthetic/settings", dependencies=[Depends(require_permission("settings.manage"))]
    )
    async def change_settings() -> None:
        """An admin write that forgot `audited(...)`."""

    specs = [*discover_modules(), ModuleSpec(name="synthetic", routers=[router])]
    app = create_app(make_settings(), registry=ModuleRegistry.from_specs(specs))
    found = dict(privileged_routes(app))
    assert found["POST /api/v1/synthetic/settings"] is None


def test_no_route_changes_or_deletes_audit_entries() -> None:
    app = create_app(make_settings())
    writes = sorted(
        f"{method} {path}"
        for method, path, _dependant, _endpoint in api_routes(app)
        if path.startswith("/api/v1/audit") and method != "GET"
    )
    # The only writes: ask for a verification or an export, change settings, keep or drop your
    # own saved searches. Never an entry.
    assert writes == [
        "DELETE /api/v1/audit/saved-searches/{search_id}",
        "POST /api/v1/audit/exports",
        "POST /api/v1/audit/saved-searches",
        "POST /api/v1/audit/verification-runs",
        "PUT /api/v1/audit/settings",
    ]
