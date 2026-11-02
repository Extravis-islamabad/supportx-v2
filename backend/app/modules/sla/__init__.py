"""SLA module (architecture.md §6.1; WP-025, D-115, ADR-037).

Owns working calendars, holiday lists and holidays (session 1); policies, targets, the
per-record SLA state, pauses and escalation runs follow in sessions 2 and 3. It never reads
work-item tables: record types register with it (wp-025-plan.md §3.1).

All business-time maths goes through one service, `domain/calendar.py` (REQ-SLA-014), pinned
by the published table in docs/architecture/sla-business-time.md.

Public interface for other modules: `calendar_for_maths` (a calendar ready for business-time
maths), `system_calendar_id`, `SystemCalendar`, `Calendar` (its `add`, `between`,
`working_at`); `SlaRecordType` and `register_record_type`, for a module whose
records have SLAs. Sites and support groups name their calendar through organization, which asks
this module whether an ID is usable (`register_calendar_check`, registered at import).
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules import organization
from app.modules.sla.api.routes import router
from app.modules.sla.domain.calendar import Calendar
from app.modules.sla.domain.setup import SystemCalendar
from app.modules.sla.events import EVENTS
from app.modules.sla.service.access import MANAGE, VIEW
from app.modules.sla.service.calendars import (
    calendar_exists,
    calendar_for_maths,
    system_calendar_id,
)
from app.modules.sla.service.realtime import ROUTES
from app.modules.sla.service.registry import SlaRecordType, register_record_type

FEATURE = "sla"  # in every edition (licensing catalogue): SLAs have no licence gate beyond it

# Technicians read the set-up (the SLA panel names the calendar); admins change it.
PERMISSIONS = (
    PermissionSpec(VIEW, FEATURE, defaults=(("technician", "all"),)),
    PermissionSpec(MANAGE, FEATURE),
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
)

__all__ = [
    "Calendar",
    "SlaRecordType",
    "SystemCalendar",
    "calendar_for_maths",
    "module",
    "register_record_type",
    "system_calendar_id",
]
