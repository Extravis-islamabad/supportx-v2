"""Organization module (architecture.md §6.1).

Tenants; sites and support groups with their members (WP-016: the `site` and `group` scopes of
the policy layer), their details, departments and desks (WP-021, ADR-032); tenant branding and
addresses (WP-017: logo, colours, texts, custom domains, the tenant an address belongs to).
Sites and groups name their working calendar (`calendar_id`, WP-025); the calendars are the
sla module's. Files (WP-022): the module answers the files
service's access questions for brand uploads (`service/file_access.py`), registered at startup.

Public interface for other modules: `get_current_tenant`, `TenantView`, `TenantStatus`,
`memberships`, `Memberships`, `users_in_sites`, `users_in_groups`, `existing_unit_ids`,
`active_unit_ids`, `existing_departments`, `department_site`, `default_desk_id`, `default_site`,
`find_site`, `find_department` (directory sync and sign-in mapping, WP-039 D6), `leave_groups`,
`register_usage` (modules that point at a site, group or department say how many rows use it),
`site_names` (sites' names by ID, read only; the new-device notice names a mapped site),
`tenant_for_host`, `HostTenant` (sign-in hint, WP-017), `get_branding`, `BrandingView`,
`email_branding`, `EmailBranding`, `header_html` (e-mails), `register_calendar_check`,
`calendar_users`, `CalendarUsers`, `unit_calendars` (WP-025: which calendar a site or group
names); `leads_group`, `led_groups`, `may_manage_group`, `require_group_manager`, `GroupActor`
(D-152: a team lead manages only the groups they lead); `erase_person_units` (the
organisation's part of a GDPR erasure, ADR-052: memberships go, leadership to the successor).
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
from app.modules.organization.service.calendars import (
    CalendarUsers,
    calendar_users,
    register_calendar_check,
    unit_calendars,
)
from app.modules.organization.service.email_branding import (
    EmailBranding,
    email_branding,
    header_html,
)
from app.modules.organization.service.erasure import erase_person_units
from app.modules.organization.service.file_access import FILE_ACCESS
from app.modules.organization.service.hosts import (
    HostTenant,
    link_tenant,
    tenant_for_host,
    tenant_for_slug,
)
from app.modules.organization.service.instance import (
    RegionalDefaults,
    base_currency,
    offered_languages,
    regional_defaults,
)
from app.modules.organization.service.leadership import (
    GroupActor,
    leads_group,
    led_groups,
    may_manage_group,
    require_group_manager,
)
from app.modules.organization.service.realtime import ROUTES
from app.modules.organization.service.structure import (
    SiteDefaults,
    active_unit_ids,
    count_desks,
    default_desk_id,
    default_site,
    department_site,
    existing_departments,
    find_department,
    find_group,
    find_site,
    heads_department,
    leave_groups,
    register_group_disable_guard,
    register_site_people_counter,
    site_defaults,
    site_names,
    unit_heads,
    unregister_group_disable_guard,
    unregister_site_people_counter,
)
from app.modules.organization.service.tenants import get_current_tenant, record_tenant_provisioned
from app.modules.organization.service.units import (
    SYSTEM_PATH,
    Memberships,
    active_groups,
    add_member,
    existing_unit_ids,
    memberships,
    register_member_guard,
    remove_member,
    unregister_member_guard,
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
    # The groups you lead only (D-152): availability, assignment, templates, views, dashboards.
    PermissionSpec("groups.manage_own", defaults=(("team_lead", "all"),)),
    PermissionSpec(
        "departments.view",
        defaults=(("technician", "all"), ("service_desk_manager", "all"), ("site_admin", "all")),
    ),
    PermissionSpec("departments.manage"),
    PermissionSpec("settings.manage"),
    # Per-area configure rights (WP-042, REQ-ADM-019); settings.manage grants every area.
    PermissionSpec("config.organisation"),
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
    "SYSTEM_PATH",
    "BrandingView",
    "CalendarUsers",
    "EmailBranding",
    "GroupActor",
    "HostTenant",
    "Memberships",
    "RegionalDefaults",
    "SiteDefaults",
    "TenantStatus",
    "TenantView",
    "active_groups",
    "active_unit_ids",
    "add_member",
    "base_currency",
    "calendar_users",
    "default_desk_id",
    "default_site",
    "department_site",
    "email_branding",
    "erase_person_units",
    "existing_departments",
    "existing_unit_ids",
    "find_department",
    "find_group",
    "find_site",
    "get_branding",
    "get_current_tenant",
    "header_html",
    "heads_department",
    "leads_group",
    "leave_groups",
    "led_groups",
    "link_tenant",
    "may_manage_group",
    "memberships",
    "module",
    "offered_languages",
    "record_tenant_provisioned",
    "regional_defaults",
    "register_calendar_check",
    "register_group_disable_guard",
    "register_member_guard",
    "register_site_people_counter",
    "register_usage",
    "remove_member",
    "require_group_manager",
    "site_defaults",
    "site_names",
    "tenant_for_host",
    "tenant_for_slug",
    "unit_calendars",
    "unit_heads",
    "unregister_group_disable_guard",
    "unregister_member_guard",
    "unregister_site_people_counter",
    "users_in_groups",
    "users_in_sites",
]
