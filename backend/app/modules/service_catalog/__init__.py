"""Service catalog module (WP-030 s1, plan D2; architecture.md §6.1, §2.15).

The items people request: their form questions, approval, fulfilment plan, priority, SLA and
group (REQ-SR-001: every service request has an item). WP-030 builds the minimal model and its
API; WP-031 adds the admin screens, versions and the rest of REQ-CAT. Licensed with
`service_request` (Essentials, catalog basics); the advanced parts need `catalog` (plan D3,
pending the product owner).

Public interface for other modules: none yet (work_items will read an item's rules here).
"""

from app.core.modules import ModuleSpec
from app.modules.service_catalog.infra import models  # noqa: F401 - registers the tables

FEATURE = "service_request"

module = ModuleSpec(name="service_catalog", feature=FEATURE)

__all__ = ["module"]
