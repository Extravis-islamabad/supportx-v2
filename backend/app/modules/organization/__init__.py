"""Organization module (architecture.md §6.1).

Tenants; sites and support groups with their members (WP-016: the `site` and `group` scopes of
the policy layer); tenant branding and addresses (WP-017: logo, colours, texts, custom domains,
the tenant an address belongs to). Departments and business hours arrive with later work
packages. Files (WP-022): the module answers the files service's access questions for brand
uploads (`service/file_access.py`), registered at startup.

Public interface for other modules: `get_current_tenant`, `TenantView`, `TenantStatus`,
`memberships`, `Memberships`, `users_in_sites`, `users_in_groups`, `tenant_for_host`,
`HostTenant` (sign-in hint, WP-017), `get_branding`, `BrandingView` (e-mails).
"""

from fastapi import FastAPI

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.organization.api.branding import public_router as public_branding_router
from app.modules.organization.api.branding import router as branding_router
from app.modules.organization.api.routes import router
from app.modules.organization.api.units import groups_router, sites_router
from app.modules.organization.domain.tenant import TenantStatus, TenantView
from app.modules.organization.events import EVENTS
from app.modules.organization.service.branding import BrandingView, get_branding
from app.modules.organization.service.file_access import FILE_ACCESS
from app.modules.organization.service.hosts import HostTenant, tenant_for_host
from app.modules.organization.service.realtime import ROUTES
from app.modules.organization.service.tenants import get_current_tenant
from app.modules.organization.service.units import (
    Memberships,
    existing_unit_ids,
    memberships,
    users_in_groups,
    users_in_sites,
)
from app.shared.files.ports import register_owner_access, unregister_owner_access

PERMISSIONS = (
    PermissionSpec("sites.view"),
    PermissionSpec("sites.manage"),
    PermissionSpec("groups.view"),
    PermissionSpec("groups.manage"),
    PermissionSpec("settings.manage"),
    PermissionSpec("branding.manage"),
)


async def _startup(app: FastAPI) -> None:
    del app
    register_owner_access(FILE_ACCESS)


async def _shutdown(app: FastAPI) -> None:
    del app
    unregister_owner_access(FILE_ACCESS.owner_types)


module = ModuleSpec(
    name="organization",
    routers=[router, sites_router, groups_router, branding_router, public_branding_router],
    events=EVENTS,
    permissions=PERMISSIONS,
    realtime=ROUTES,
    on_startup=[_startup],
    on_shutdown=[_shutdown],
)

__all__ = [
    "BrandingView",
    "HostTenant",
    "Memberships",
    "TenantStatus",
    "TenantView",
    "existing_unit_ids",
    "get_branding",
    "get_current_tenant",
    "memberships",
    "module",
    "tenant_for_host",
    "users_in_groups",
    "users_in_sites",
]
