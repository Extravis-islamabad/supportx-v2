"""Organization module (architecture.md §6.1).

Tenants; sites, support groups and their members (WP-016: the `site` and `group` scopes of the
policy layer); since WP-021 (ADR-032) their details, departments and desks.

Public interface for other modules: `get_current_tenant`, `TenantView`, `TenantStatus`,
`memberships`, `Memberships`, `users_in_sites`, `users_in_groups`, `existing_unit_ids`,
`existing_departments`, `department_site`, `default_desk_id`, `default_site`, `find_site`,
`find_department` (directory sync and sign-in mapping, WP-039 D6), `register_usage` (modules
that point at a site, group or department say how many rows use it).
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.organization.api.routes import router
from app.modules.organization.api.structure import departments, desks, groups, sites
from app.modules.organization.api.units import groups_router, sites_router
from app.modules.organization.domain.tenant import TenantStatus, TenantView
from app.modules.organization.events import EVENTS
from app.modules.organization.service.realtime import ROUTES
from app.modules.organization.service.structure import (
    active_unit_ids,
    count_desks,
    default_desk_id,
    default_site,
    department_site,
    existing_departments,
    find_department,
    find_site,
    leave_groups,
)
from app.modules.organization.service.tenants import get_current_tenant
from app.modules.organization.service.units import (
    Memberships,
    existing_unit_ids,
    memberships,
    users_in_groups,
    users_in_sites,
)
from app.modules.organization.service.usage import register_usage

PERMISSIONS = (
    PermissionSpec("sites.view"),
    PermissionSpec("sites.manage"),
    PermissionSpec("groups.view"),
    PermissionSpec("groups.manage"),
    PermissionSpec("departments.view", defaults=(("technician", "all"),)),
    PermissionSpec("departments.manage"),
    PermissionSpec("settings.manage"),
)

module = ModuleSpec(
    name="organization",
    # The detailed routes first: they own GET/POST/PATCH/DELETE of sites and groups.
    routers=[router, sites, groups, departments, desks, sites_router, groups_router],
    events=EVENTS,
    permissions=PERMISSIONS,
    realtime=ROUTES,
    usage_counters={"desks": count_desks},
)

__all__ = [
    "Memberships",
    "TenantStatus",
    "TenantView",
    "active_unit_ids",
    "default_desk_id",
    "default_site",
    "department_site",
    "existing_departments",
    "existing_unit_ids",
    "find_department",
    "find_site",
    "get_current_tenant",
    "leave_groups",
    "memberships",
    "module",
    "register_usage",
    "users_in_groups",
    "users_in_sites",
]
