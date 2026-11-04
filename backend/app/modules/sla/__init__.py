"""SLA module (architecture.md §6.1; WP-025, D-115, ADR-037).

Owns working calendars, holiday lists and holidays (session 1); policies, targets, the
per-record SLA state, pauses and escalation runs follow in sessions 2 and 3. It never reads
work-item tables: record types register with it (wp-025-plan.md §3.1).

All business-time maths goes through one service, `domain/calendar.py` (REQ-SLA-014), pinned
by the published table in docs/architecture/sla-business-time.md.

Public interface for other modules: `calendar_for_maths` (a calendar ready for business-time
maths), `system_calendar_id`, `SystemCalendar`, `Calendar` (its `add`, `between`,
`working_at`); `SlaRecordType`, `register_record_type`, `on_change`, `set_due_by_hand` and
`SlaStamp`, for a module whose records have SLAs (it calls `on_change` inside every save);
`record_sla` (with `SlaRecordView`, `SlaTargetView`) for the record page's SLA panel;
`record_calendar` for a record's own business-day rules (auto-close). Sites and
support groups name their calendar through organization, which asks this module whether an
ID is usable (`register_calendar_check`, registered at import).

Session 3: `fire` and `next_wake` (the waker: Temporal's `workers/sla_timers`, and the
`sla__safety_net` schedule), `Fired` (what a record type's `on_fired` hook hears), the
escalation `Level` with its recipients and actions (for its `run_actions` hook and the
notification source), `escalation_run`, and the `SlaWarning`, `SlaBreached` and `SlaEscalated`
events.
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules import organization
from app.modules.sla.api.routes import router
from app.modules.sla.domain.calendar import Calendar, CalendarError
from app.modules.sla.domain.escalation import Action, ActionKind, Level, Recipient, RecipientKind
from app.modules.sla.domain.setup import SystemCalendar
from app.modules.sla.events import EVENTS, SlaBreached, SlaEscalated, SlaWarning
from app.modules.sla.service.access import MANAGE, VIEW
from app.modules.sla.service.calendars import (
    calendar_exists,
    calendar_for_maths,
    system_calendar_id,
)
from app.modules.sla.service.clock import SlaStamp, on_change, set_due_by_hand
from app.modules.sla.service.policies import existing_policy_ids
from app.modules.sla.service.realtime import ROUTES
from app.modules.sla.service.records import (
    SlaRecordView,
    SlaTargetView,
    record_calendar,
    record_sla,
)
from app.modules.sla.service.registry import Fired, SlaRecordType, register_record_type
from app.modules.sla.service.scheduler import SCHEDULER
from app.modules.sla.service.timers import escalation_run, fire, next_wake, safety_net
from app.shared.schedules import ScheduleSpec

FEATURE = "sla"  # in every edition (licensing catalogue): SLAs have no licence gate beyond it

# Technicians read the set-up (the SLA panel names the calendar); admins change it.
PERMISSIONS = (
    PermissionSpec(
        VIEW, FEATURE, defaults=(("technician", "all"), ("service_desk_manager", "all"))
    ),
    PermissionSpec(MANAGE, FEATURE, defaults=(("service_desk_manager", "all"),)),
)

# Sites and groups name a calendar; organization asks here whether the ID is one (D-115 D3).
organization.register_calendar_check(calendar_exists)

module = ModuleSpec(
    name="sla",
    routers=[router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    realtime=ROUTES,
    # The safety net behind the Temporal waker (D-115 D5): anything over two minutes late.
    schedules=[ScheduleSpec("sla__safety_net", 60, safety_net)],
    # Saves that move clocks wake the record's Temporal workflow (off without Temporal).
    consumers=[SCHEDULER],
)

__all__ = [
    "Action",
    "ActionKind",
    "Calendar",
    "CalendarError",
    "Fired",
    "Level",
    "Recipient",
    "RecipientKind",
    "SlaBreached",
    "SlaEscalated",
    "SlaRecordType",
    "SlaRecordView",
    "SlaStamp",
    "SlaTargetView",
    "SlaWarning",
    "SystemCalendar",
    "calendar_for_maths",
    "escalation_run",
    "existing_policy_ids",
    "fire",
    "module",
    "next_wake",
    "on_change",
    "record_calendar",
    "record_sla",
    "register_record_type",
    "set_due_by_hand",
    "system_calendar_id",
]
