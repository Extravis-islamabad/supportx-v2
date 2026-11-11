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

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.ai import (
    register_conversation_source,
    register_embedding_source,
    register_record_access,
    unregister_conversation_source,
    unregister_embedding_source,
    unregister_record_access,
)
from app.modules.identity_access import SERVICE_DESK_MANAGER
from app.modules.work_items.api.approval_settings_routes import router as approval_settings_router
from app.modules.work_items.api.change_board_routes import router as change_board_router
from app.modules.work_items.api.change_child_routes import router as change_child_router
from app.modules.work_items.api.change_window_routes import (
    calendar_router as change_calendar_router,
)
from app.modules.work_items.api.change_window_routes import (
    change_router as change_window_change_router,
)
from app.modules.work_items.api.change_window_routes import (
    release_calendar_router,
)
from app.modules.work_items.api.change_window_routes import (
    release_router as release_window_router,
)
from app.modules.work_items.api.change_window_routes import router as change_window_router
from app.modules.work_items.api.portal_home_routes import router as portal_home_router
from app.modules.work_items.api.portal_request_routes import router as portal_request_router
from app.modules.work_items.api.portal_routes import router as portal_router
from app.modules.work_items.api.repeat_routes import router as repeat_router
from app.modules.work_items.api.routes import build_router
from app.modules.work_items.domain.closure import OpenItem, OpenWorkKind
from app.modules.work_items.domain.types import (
    CHANGE,
    INCIDENT,
    PERMISSION_TYPES,
    PROBLEM,
    RELEASE,
    SERVICE_REQUEST,
    TYPES,
)
from app.modules.work_items.events import EVENTS
from app.modules.work_items.service import (
    ai_sources,
    audit_subtype,
    bulk,
    inbound_mail,
    notifications,
    parts,
    portal,
    problem_notifications,
    record_facts,
    release_duties,
    repeat_rules,
    report_names,
    request_notifications,
    resolution,
    rule_step_notifications,
    staff_reply_notifications,
)
from app.modules.work_items.service.access import permissions
from app.modules.work_items.service.approvals import APPROVER_LEFT, inactive_approvers_schedule
from app.modules.work_items.service.automated import register_triggers
from app.modules.work_items.service.automation import register_types
from app.modules.work_items.service.change_guard import register as register_change_guard
from app.modules.work_items.service.closing import (
    register_open_work,
    register_requester_channel,
    resolution_notified,
    unregister_open_work,
    unregister_requester_channel,
)
from app.modules.work_items.service.conversations import RequesterReply, add_requester_reply
from app.modules.work_items.service.file_access import FILE_ACCESS
from app.modules.work_items.service.realtime import CHANNELS, ROUTES
from app.modules.work_items.service.reporting import register_sources, unregister_sources
from app.modules.work_items.service.sla import register_sla
from app.modules.work_items.service.stage_approvals import register as register_stage_approvals
from app.modules.work_items.service.usage import register_record_usage
from app.shared.files.ports import register_owner_access, unregister_owner_access
from app.shared.schedules import ScheduleSpec


def _register_parts() -> None:
    """Open tasks are the record's open work (WP-020f port).

    Workers close records too (bulk), so this runs at import as well as at app startup (after a
    test unregistered it).
    """
    register_open_work(OpenWorkKind.TASKS, parts.open_tasks, parts.complete_tasks)


_register_parts()


def _register_ai() -> None:
    """What AI may read of an incident (WP-038): the record page's own rules, through here."""
    register_record_access(INCIDENT.code, ai_sources.may_view_incident)
    register_conversation_source(INCIDENT.code, ai_sources.conversation_for)
    register_embedding_source(INCIDENT.code, ai_sources.incident_texts, ai_sources.incident_ids)


async def _startup(app: FastAPI) -> None:
    del app
    _register_parts()
    register_owner_access(FILE_ACCESS)
    register_sources()  # again after a shutdown (tests start and stop the app)
    _register_ai()


async def _shutdown(app: FastAPI) -> None:
    del app
    unregister_owner_access(FILE_ACCESS.owner_types)
    unregister_sources()
    unregister_record_access(INCIDENT.code)
    unregister_conversation_source(INCIDENT.code)
    unregister_embedding_source(INCIDENT.code)


register_record_usage()
_register_ai()  # at import too: the consumers worker runs the re-embed sweep without startup
register_types()
register_triggers()
register_stage_approvals(tuple(TYPES.values()))  # WP-058a s5: releases' stage approval guard
register_change_guard(tuple(TYPES.values()))  # WP-045a D4: approvals and the outcome
# Release roles as open duties in the role editor's preview (REQ-REL-024 AC2, lane B's #223).
release_duties.register()
register_sla()
# At import, not only at app startup: the consumers worker imports modules without running
# their startup hooks, and report exports run there (lane C, WP-035 session 3).
register_sources()

# Names for report files (WP-035): at import, so the consumers worker has them too.
report_names.register()
# Incident notifications (WP-023, lane B with lane A's review): at import, for the worker too.
notifications.register()
request_notifications.register()
problem_notifications.register()  # WP-044c D15
rule_step_notifications.register()  # D-154 rules: every type's rule-step notice
staff_reply_notifications.register()  # change and release replies settle (lane B's #359)
# What other modules may ask about incidents (D-121, knowledge links): at import, as above.
record_facts.register()
# Which kind of work item a save was, for the audit log (WP-064, ADR-045): at import, as above.
audit_subtype.register()
# Incidents from mail (WP-024, lane B with lane A's review): at import, for the worker too.
inbound_mail.register()
# Who may reach work item files: at import too, since mail attachments upload in the worker.
register_owner_access(FILE_ACCESS)

module = ModuleSpec(
    name="work_items",
    routers=[
        *(build_router(wtype) for wtype in TYPES.values()),
        portal_router,
        portal_request_router,  # WP-030 D9
        portal_home_router,  # WP-032 D1
        approval_settings_router,  # D-146: the approval chair (WP-048b S2)
        change_board_router,  # WP-045b S2
        repeat_router,  # WP-044c D16: the problem module's
        change_window_router,  # WP-045c: freeze and maintenance windows (ADR-042)
        change_window_change_router,  # WP-045c: a change's conflicts and freeze override
        change_child_router,  # WP-045d S1: child changes and releases
        change_calendar_router,  # WP-045c S3: the change calendar
        release_calendar_router,  # WP-058b S1: the release calendar (same query)
        release_window_router,  # WP-058b S2: a release's freeze override
    ],
    router_features=[
        *(wtype.feature for wtype in TYPES.values()),
        INCIDENT.feature,
        SERVICE_REQUEST.feature,
        INCIDENT.feature,  # the portal home's summary: the portal is the incident feature's
        None,  # approval settings: the engine is core, every type with approvals uses them
        CHANGE.feature,  # change advisory boards
        PROBLEM.feature,  # repeat incident rules (D-140 item 5: not in Essentials)
        CHANGE.feature,  # change windows
        CHANGE.feature,  # a change's conflicts and freeze override
        CHANGE.feature,  # child changes and releases
        CHANGE.feature,  # the change calendar
        RELEASE.feature,  # the release calendar
        RELEASE.feature,  # a release's freeze override
    ],
    events=EVENTS,
    permissions=(
        *(spec for wtype in PERMISSION_TYPES for spec in permissions(wtype)),
        # Configure the service desk (WP-042, REQ-ADM-019): levels, categories, templates, reply
        # templates and custom fields; settings.manage still grants every area.
        PermissionSpec(
            "config.service_desk", "incident", defaults=((SERVICE_DESK_MANAGER, "all"),)
        ),
        *portal.PERMISSIONS,  # WP-028 D2 (pending the product owner)
    ),
    channels=CHANNELS,
    realtime=ROUTES,
    # REQ-SR-023 AC2: a deactivated approver's pending approvals go to the fallback.
    consumers=[APPROVER_LEFT],
    on_startup=[_startup],
    on_shutdown=[_shutdown],
    # REQ-INC-096: resolved records the requester was told about close after N business days.
    schedules=[
        ScheduleSpec("work_items__auto_close", 900, resolution.auto_close_schedule),
        # REQ-SR-023 AC3: daily, no approval waits on someone no longer active.
        ScheduleSpec("work_items__inactive_approvers", 86400, inactive_approvers_schedule),
        # Bulk jobs (WP-020d): picked up within seconds of being asked for, like people imports.
        ScheduleSpec("work_items__bulk_jobs", 5, bulk.run_bulk_jobs),
        # WP-044c D16 (REQ-PRB-068): repeat incident rules, every 15 minutes, without AI.
        ScheduleSpec("work_items__repeat_incidents", 900, repeat_rules.repeat_schedule),
    ],
)

# Ports for other modules (WP-020f): open work on a record, and channels that tell requesters.
__all__ = [
    "OpenItem",
    "OpenWorkKind",
    "RequesterReply",
    "add_requester_reply",
    "module",
    "register_open_work",
    "register_requester_channel",
    "resolution_notified",
    "unregister_open_work",
    "unregister_requester_channel",
]
