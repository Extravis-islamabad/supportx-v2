"""Work items module (architecture.md §6.1, §6.2; WP-020; ADR-026).

The one engine for every ticket-like record. A type (incident now; service request, problem,
change and release later) is a registry entry in `domain/types.py` with its own API path, licence
feature and permission namespace, served by the same services, tables and realtime channels.

Licensing: no module-wide feature; each type's router is guarded by its own feature
(`router_features`: `incident` for incidents), so a plan with problems but not changes gets
exactly those routes.

Public interface for other modules: none yet (notes, tasks, links and the SLA module will use
the work item service through here in WP-020b+). Files (WP-022): the module answers the files
service's access questions for records, replies and notes (`service/file_access.py`), registered
at startup.
"""

from fastapi import FastAPI

from app.core.modules import ModuleSpec
from app.modules.work_items.api.routes import build_router
from app.modules.work_items.domain.closure import OpenItem, OpenWorkKind
from app.modules.work_items.domain.types import TYPES
from app.modules.work_items.events import EVENTS
from app.modules.work_items.service import (
    bulk,
    inbound_mail,
    notifications,
    report_names,
    resolution,
)
from app.modules.work_items.service.access import permissions
from app.modules.work_items.service.automated import register_triggers
from app.modules.work_items.service.automation import register_types
from app.modules.work_items.service.closing import (
    register_open_work,
    register_requester_channel,
    resolution_notified,
    unregister_open_work,
    unregister_requester_channel,
)
from app.modules.work_items.service.conversations import add_requester_reply
from app.modules.work_items.service.file_access import FILE_ACCESS
from app.modules.work_items.service.realtime import CHANNELS, ROUTES
from app.modules.work_items.service.reporting import register_sources, unregister_sources
from app.modules.work_items.service.usage import register_record_usage
from app.shared.files.ports import register_owner_access, unregister_owner_access
from app.shared.schedules import ScheduleSpec


async def _startup(app: FastAPI) -> None:
    del app
    register_owner_access(FILE_ACCESS)
    register_sources()  # again after a shutdown (tests start and stop the app)


async def _shutdown(app: FastAPI) -> None:
    del app
    unregister_owner_access(FILE_ACCESS.owner_types)
    unregister_sources()


register_record_usage()
register_types()
register_triggers()
# At import, not only at app startup: the consumers worker imports modules without running
# their startup hooks, and report exports run there (lane C, WP-035 session 3).
register_sources()

# Names for report files (WP-035): at import, so the consumers worker has them too.
report_names.register()
# Incident notifications (WP-023, lane B with lane A's review): at import, for the worker too.
notifications.register()
# Incidents from mail (WP-024, lane B with lane A's review): at import, for the worker too.
inbound_mail.register()

module = ModuleSpec(
    name="work_items",
    routers=[build_router(wtype) for wtype in TYPES.values()],
    router_features=[wtype.feature for wtype in TYPES.values()],
    events=EVENTS,
    permissions=tuple(spec for wtype in TYPES.values() for spec in permissions(wtype)),
    channels=CHANNELS,
    realtime=ROUTES,
    on_startup=[_startup],
    on_shutdown=[_shutdown],
    # REQ-INC-096: resolved records the requester was told about close after N business days.
    schedules=[
        ScheduleSpec("work_items__auto_close", 900, resolution.auto_close_schedule),
        # Bulk jobs (WP-020d): picked up within seconds of being asked for, like people imports.
        ScheduleSpec("work_items__bulk_jobs", 5, bulk.run_bulk_jobs),
    ],
)

# Ports for other modules (WP-020f): open work on a record, and channels that tell requesters.
__all__ = [
    "OpenItem",
    "OpenWorkKind",
    "add_requester_reply",
    "module",
    "register_open_work",
    "register_requester_channel",
    "resolution_notified",
    "unregister_open_work",
    "unregister_requester_channel",
]
