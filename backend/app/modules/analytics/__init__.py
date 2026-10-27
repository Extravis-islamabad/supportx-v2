"""Analytics module (architecture.md §6.1, §6.10; WP-035, ADR-033): the reporting engine.

Reports run over reporting sources that the owning modules register (`app/shared/reporting`):
each source is the module's own scope-filtered list query, so a report shows only records the
viewer could list. Queries run read-only as `supportx_report` on their own small pool with a
statement time limit. Built-in reports ship as definitions in code; saved reports, shared
folders and favourites are tables of this module.

No module-wide licence feature: each run checks the feature of the entity it reports on.

Public interface for other modules: none yet (dashboards, WP-036, are part of this module).
"""

from fastapi import FastAPI

from app.core.authorization import PermissionSpec, Scope
from app.core.database import Database
from app.core.modules import ModuleSpec
from app.modules.analytics.api.routes import REPORTING_DB_STATE, SLOTS_STATE, router
from app.modules.analytics.events import EVENTS
from app.modules.analytics.service.exports import EXPORT
from app.modules.analytics.service.jobs import on_export_requested, set_subject_loader
from app.modules.analytics.service.library import CREATE, MANAGE_FOLDERS, VIEW
from app.modules.analytics.service.realtime import ROUTES
from app.modules.analytics.service.runner import TenantSlots
from app.modules.identity_access import subject_for
from app.shared.events import ConsumerSpec

_NOT_OWN: tuple[Scope, ...] = ("all", "site", "group")
_OWN: tuple[Scope, ...] = ("own",)

# reports.view moved here from identity_access's reserved list (it was reserved for this module).
# Managing shared folders stays with admins (and custom roles) until the product owner says
# otherwise; admins hold every permission.
PERMISSIONS = (
    PermissionSpec(VIEW, None, _NOT_OWN, defaults=(("technician", "all"),)),
    PermissionSpec(CREATE, None, _OWN, defaults=(("technician", "own"),)),
    PermissionSpec(MANAGE_FOLDERS, None, ("all",)),
    PermissionSpec(EXPORT, None, ("all",), defaults=(("technician", "all"),)),
)


# The worker rebuilds the requester's permissions exactly as the API does (lane B, #82).
set_subject_loader(subject_for)


async def _startup(app: FastAPI) -> None:
    settings = app.state.settings
    setattr(app.state, REPORTING_DB_STATE, Database.reporting_from_settings(settings))
    setattr(app.state, SLOTS_STATE, TenantSlots(settings.report_concurrent_per_tenant))


async def _shutdown(app: FastAPI) -> None:
    database: Database | None = getattr(app.state, REPORTING_DB_STATE, None)
    if database is not None:
        await database.dispose()


module = ModuleSpec(
    name="analytics",
    routers=[router],
    events=EVENTS,
    permissions=PERMISSIONS,
    realtime=ROUTES,
    consumers=[
        ConsumerSpec(
            name="analytics__export",
            event_types=("analytics.report_export.requested",),
            handler=on_export_requested,
            ack_wait_seconds=900,
        )
    ],
    on_startup=[_startup],
    on_shutdown=[_shutdown],
)

__all__ = ["module"]
