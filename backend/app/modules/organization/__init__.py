"""Organization module (architecture.md §6.1).

Tenants; sites and support groups with their members (WP-016: the `site` and `group` scopes of
the policy layer). Departments and business hours arrive with later work packages.

Public interface for other modules: `get_current_tenant`, `TenantView`, `TenantStatus`,
`memberships`, `Memberships`, `users_in_sites`, `users_in_groups`.
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.organization.api.routes import router
from app.modules.organization.api.units import groups_router, sites_router
from app.modules.organization.domain.tenant import TenantStatus, TenantView
from app.modules.organization.events import EVENTS
from app.modules.organization.service.tenants import get_current_tenant
from app.modules.organization.service.units import (
    Memberships,
    memberships,
    users_in_groups,
    users_in_sites,
)

PERMISSIONS = (
    PermissionSpec("sites.view"),
    PermissionSpec("sites.manage"),
    PermissionSpec("groups.view"),
    PermissionSpec("groups.manage"),
    PermissionSpec("settings.manage"),
)

module = ModuleSpec(
    name="organization",
    routers=[router, sites_router, groups_router],
    events=EVENTS,
    permissions=PERMISSIONS,
)

__all__ = [
    "Memberships",
    "TenantStatus",
    "TenantView",
    "get_current_tenant",
    "memberships",
    "module",
    "users_in_groups",
    "users_in_sites",
]
