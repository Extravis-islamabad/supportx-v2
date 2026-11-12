"""Procurement module (architecture.md §2.11, §6.1; parity 07 §29): vendors for now.

WP-049a session 2 brings the minimal part assets need: vendors as first-class records
(REQ-PUR-001), with their own list and API. WP-054 adds purchase requests, orders and contracts
here, with no ADR (the approved WP-049 plan). Licensed with the `procurement` feature.

Public interface for other modules: `vendor_problem` (may a record name this vendor: not found,
or inactive and not already its vendor), `vendor_names` (for display), and
`register_vendor_usage` (a module whose records name vendors says how many do, so a vendor in
use cannot be deleted). WP-049b S4b (REQ-AST-053, the vendor import from the asset screens):
`create_vendor` and `update_vendor` (the same calls as the API, with their permissions),
`find_vendor` and `find_vendor_id` (by name), and the permissions `VENDORS_CREATE` and
`VENDORS_MANAGE`.
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.procurement.api.routes import router
from app.modules.procurement.events import EVENTS
from app.modules.procurement.service.realtime import ROUTES
from app.modules.procurement.service.vendors import (
    CREATE,
    MANAGE,
    VIEW,
    create_vendor,
    find_vendor,
    find_vendor_id,
    register_vendor_usage,
    update_vendor,
    vendor_names,
    vendor_problem,
    vendor_report_names,
)
from app.shared.reporting import register_names

FEATURE = "procurement"

# Technicians see vendors (asset forms show and pick them); adding and changing vendors is for
# admins and the roles they make, until the product owner says otherwise.
PERMISSIONS = (
    PermissionSpec(VIEW, FEATURE, defaults=(("technician", "all"),)),
    PermissionSpec(CREATE, FEATURE),
    PermissionSpec(MANAGE, FEATURE),
)

# Vendor names in report files (assets group by vendor): at import, for the consumers worker too.
register_names("vendor", vendor_report_names)

module = ModuleSpec(
    name="procurement",
    routers=[router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    realtime=ROUTES,
)

VENDORS_CREATE = CREATE
VENDORS_MANAGE = MANAGE

__all__ = [
    "VENDORS_CREATE",
    "VENDORS_MANAGE",
    "create_vendor",
    "find_vendor",
    "find_vendor_id",
    "module",
    "register_vendor_usage",
    "update_vendor",
    "vendor_names",
    "vendor_problem",
]
