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
from app.modules.work_items.domain.types import TYPES
from app.modules.work_items.events import EVENTS
from app.modules.work_items.service import report_names
from app.modules.work_items.service.access import permissions
from app.modules.work_items.service.automated import register_triggers
from app.modules.work_items.service.automation import register_types
from app.modules.work_items.service.file_access import FILE_ACCESS
from app.modules.work_items.service.realtime import CHANNELS, ROUTES
from app.modules.work_items.service.reporting import register_sources, unregister_sources
from app.modules.work_items.service.usage import register_record_usage
from app.shared.files.ports import register_owner_access, unregister_owner_access


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
)

__all__ = ["module"]
