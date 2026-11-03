"""Service catalog module (WP-030 s1, plan D2; architecture.md §6.1, §2.15).

The items people request: their form questions, approval, fulfilment plan, priority, SLA and
group (REQ-SR-001: every service request has an item). WP-030 builds the minimal model and its
API; WP-031 adds the admin screens, versions and the rest of REQ-CAT. Licensed with
`service_request` (Essentials, catalog basics); the advanced parts need `catalog` (plan D3,
pending the product owner).

Public interface for other modules: `request_item` (what an item decides for a new service
request, with its form's answers checked), `RequestItem`, `rules_of`.
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.service_catalog.api.routes import router
from app.modules.service_catalog.events import EVENTS
from app.modules.service_catalog.infra import models  # noqa: F401 - registers the tables
from app.modules.service_catalog.service.catalog import (
    MANAGE,
    RequestItem,
    request_item,
    rules_of,
)
from app.modules.service_catalog.service.realtime import ROUTES

FEATURE = "service_request"

# Admins hold it (every permission); a catalog manager role can be made from it.
PERMISSIONS = (PermissionSpec(MANAGE, FEATURE),)

module = ModuleSpec(
    name="service_catalog",
    routers=[router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    realtime=ROUTES,
)

__all__ = ["RequestItem", "module", "request_item", "rules_of"]
