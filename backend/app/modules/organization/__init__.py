"""Organization module (architecture.md §6.1).

Tenants; sites and support groups with their members (WP-016: the `site` and `group` scopes of
the policy layer), their details, departments and desks (WP-021, ADR-032); tenant branding and
addresses (WP-017: logo, colours, texts, custom domains, the tenant an address belongs to).
Business hours arrive with a later work package. Files (WP-022): the module answers the files
service's access questions for brand uploads (`service/file_access.py`), registered at startup.

Public interface for other modules: `get_current_tenant`, `TenantView`, `TenantStatus`,
`memberships`, `Memberships`, `users_in_sites`, `users_in_groups`, `existing_unit_ids`,
`active_unit_ids`, `existing_departments`, `department_site`, `default_desk_id`, `default_site`,
`find_site`, `find_department` (directory sync and sign-in mapping, WP-039 D6), `leave_groups`,
`register_usage` (modules that point at a site, group or department say how many rows use it),
`tenant_for_host`, `HostTenant` (sign-in hint, WP-017), `get_branding`, `BrandingView`,
`email_branding`, `EmailBranding`, `header_html` (e-mails).
"""

from fastapi import FastAPI

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.organization.api.branding import public_router as public_branding_router
from app.modules.organization.api.branding import router as branding_router
from app.modules.organization.api.domains import public_router as domain_check_router
from app.modules.organization.api.domains import router as domains_router
from app.modules.organization.api.routes import router
from app.modules.organization.api.structure import departments, desks, groups, sites
from app.modules.organization.api.units import groups_router, sites_router
from app.modules.organization.domain.tenant import TenantStatus, TenantView
from app.modules.organization.events import EVENTS
from app.modules.organization.service import report_names
from app.modules.organization.service.branding import BrandingView, get_branding
from app.modules.organization.service.email_branding import (
    EmailBranding,
    email_branding,
    header_html,
)
from app.modules.organization.service.file_access import FILE_ACCESS
from app.modules.organization.service.hosts import HostTenant, tenant_for_host
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
from app.shared.files.ports import register_owner_access, unregister_owner_access

PERMISSIONS = (
    PermissionSpec("sites.view"),
    PermissionSpec("sites.manage"),
    PermissionSpec("groups.view"),
    PermissionSpec("groups.manage"),
    PermissionSpec("departments.view", defaults=(("technician", "all"),)),
    PermissionSpec("departments.manage"),
    PermissionSpec("settings.manage"),
    PermissionSpec("branding.manage"),
)


async def _startup(app: FastAPI) -> None:
    del app
    register_owner_access(FILE_ACCESS)


async def _shutdown(app: FastAPI) -> None:
    del app
    unregister_owner_access(FILE_ACCESS.owner_types)


# Names for report files (WP-035): at import, so the consumers worker has them too.
report_names.register()

module = ModuleSpec(
    name="organization",
    # The detailed routes first: they own GET/POST/PATCH/DELETE of sites and groups.
    routers=[
        router,
        sites,
        groups,
        departments,
        desks,
        sites_router,
        groups_router,
        branding_router,
        public_branding_router,
        domains_router,
        domain_check_router,
    ],
    events=EVENTS,
    permissions=PERMISSIONS,
    realtime=ROUTES,
    usage_counters={"desks": count_desks},
    on_startup=[_startup],
    on_shutdown=[_shutdown],
)

__all__ = [
    "BrandingView",
    "EmailBranding",
    "HostTenant",
    "Memberships",
    "TenantStatus",
    "TenantView",
    "active_unit_ids",
    "default_desk_id",
    "default_site",
    "department_site",
    "email_branding",
    "existing_departments",
    "existing_unit_ids",
    "find_department",
    "find_site",
    "get_branding",
    "get_current_tenant",
    "header_html",
    "leave_groups",
    "memberships",
    "module",
    "register_usage",
    "tenant_for_host",
    "users_in_groups",
    "users_in_sites",
]
