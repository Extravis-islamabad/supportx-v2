"""Procurement module (architecture.md §2.11, §6.1; parity 07 §29): vendors for now.

WP-049a session 2 brings the minimal part assets need: vendors as first-class records
(REQ-PUR-001), with their own list and API. WP-054 adds purchase requests, orders and contracts
here, with no ADR (the approved WP-049 plan). Licensed with the `procurement` feature.

Public interface for other modules: `vendor_problem` (may a record name this vendor: not found,
or inactive and not already its vendor), `vendor_names` (for display), and
`register_vendor_usage` (a module whose records name vendors says how many do, so a vendor in
use cannot be deleted).
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
    register_vendor_usage,
    vendor_names,
    vendor_problem,
)

FEATURE = "procurement"

# Technicians see vendors (asset forms show and pick them); adding and changing vendors is for
# admins and the roles they make, until the product owner says otherwise.
PERMISSIONS = (
    PermissionSpec(VIEW, FEATURE, defaults=(("technician", "all"),)),
    PermissionSpec(CREATE, FEATURE),
    PermissionSpec(MANAGE, FEATURE),
)

module = ModuleSpec(
    name="procurement",
    routers=[router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    realtime=ROUTES,
)

__all__ = ["module", "register_vendor_usage", "vendor_names", "vendor_problem"]
