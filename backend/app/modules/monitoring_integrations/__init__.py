"""Monitoring integrations (WP-053 S6; ADR-017, D-001): reading MonetX, never monitoring.

SupportX does no polling and no alert correlation. Through this module only, it reads health,
problems and topology from MonetX (GET only, through `app/shared/egress`) to show live health on
CIs and impact maps and to keep the CMDB's monitored devices and links current.

Public interface for other modules: none yet (health is read over the API).
"""

from fastapi import FastAPI

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules import integrations
from app.modules.monitoring_integrations.api.routes import ROUTERS
from app.modules.monitoring_integrations.events import EVENTS
from app.modules.monitoring_integrations.service import catalogue
from app.modules.monitoring_integrations.service.connections import FEATURE, MANAGE
from app.modules.monitoring_integrations.service.health import ensure_cache, refresh_schedule
from app.modules.monitoring_integrations.service.realtime import ROUTES
from app.modules.monitoring_integrations.service.topology import topology_schedule
from app.shared.connectors.ports import ConnectorCategory
from app.shared.schedules import ScheduleSpec

catalogue.register()  # MonetX in the integrations catalogue (a `monitoring` kind)
# Monitoring connectors are set up through this module's own right, not integrations' (the
# coordinator's Q2 ruling, 2026-11-25; integrations' override map, lane A's WP-055).
integrations.register_set_up_permission(ConnectorCategory.MONITORING, MANAGE)


async def _startup(app: FastAPI) -> None:
    ensure_cache(app.state.settings)


module = ModuleSpec(
    name="monitoring_integrations",
    routers=list(ROUTERS),
    feature=FEATURE.value,
    # Health stays open without the feature: it answers `unmonitored` and never asks MonetX
    # (the service checks `has_feature`), so CI pages need no licence branch.
    router_features=[FEATURE.value, None],
    # Tenant admins hold every permission, as for integrations.manage (the coordinator's Q2).
    permissions=(PermissionSpec(MANAGE),),
    schedules=[
        # Every minute: each connection's hourly import, or its "run now".
        ScheduleSpec("monitoring_integrations__topology", 60, topology_schedule),
        # Every 15 s: the watched CIs' health, so a change reaches open screens live.
        ScheduleSpec("monitoring_integrations__health", 15, refresh_schedule),
    ],
    on_startup=[_startup],
    events=EVENTS,
    realtime=ROUTES,
)

__all__ = ["module"]
