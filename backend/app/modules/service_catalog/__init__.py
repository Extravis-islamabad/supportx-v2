"""Service catalog module (WP-030 s1, WP-031 s1; architecture.md §6.1, §2.15).

The items people request: their form questions, approval, fulfilment plan, priority, SLA and
group (REQ-SR-001: every service request has an item), in a tree of categories, with a life
(draft, published, retired, planned), search and a starter catalog for new tenants (D-138).
Licensed with `service_request` (Essentials, catalog basics, D-133); the advanced parts need
`catalog` (Professional).

Public interface for other modules: `item_decides` (an existing request's item, for the
approval engine), `request_item` (what an item decides for a new service request, with its
form's answers checked), `RequestItem`, `PlanStep`, `rules_of`, `catalog_settings` (the tenant's
catalog settings), and the ports `register_item_usage` / `register_template_check` (work_items
answers them: it depends on the catalog, so the catalog cannot ask it directly).
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.service_catalog.api.routes import router
from app.modules.service_catalog.events import EVENTS
from app.modules.service_catalog.infra import models  # noqa: F401 - registers the tables
from app.modules.service_catalog.service.catalog import (
    MANAGE,
    PlanStep,
    RequestItem,
    item_decides,
    request_item,
    rules_of,
)
from app.modules.service_catalog.service.ports import (
    register_item_usage,
    register_request_counts,
    register_template_check,
)
from app.modules.service_catalog.service.realtime import ROUTES
from app.modules.service_catalog.service.schedule import SCHEDULE_EVERY, run_schedule
from app.modules.service_catalog.service.settings import read as catalog_settings
from app.modules.service_catalog.service.starter import on_tenant_provisioned
from app.shared.events import ConsumerSpec
from app.shared.schedules import ScheduleSpec

FEATURE = "service_request"

# Admins hold it (every permission); a catalog manager role can be made from it.
PERMISSIONS = (PermissionSpec(MANAGE, FEATURE),)

module = ModuleSpec(
    name="service_catalog",
    routers=[router],
    events=EVENTS,
    consumers=[
        ConsumerSpec(
            name="service_catalog__starter",
            event_types=("organization.tenant.provisioned",),
            handler=on_tenant_provisioned,
        )
    ],
    schedules=[ScheduleSpec("service_catalog__lifecycle", SCHEDULE_EVERY, run_schedule)],
    feature=FEATURE,
    permissions=PERMISSIONS,
    realtime=ROUTES,
)

__all__ = [
    "PlanStep",
    "RequestItem",
    "catalog_settings",
    "item_decides",
    "module",
    "register_item_usage",
    "register_request_counts",
    "register_template_check",
    "request_item",
    "rules_of",
]
