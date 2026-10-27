"""Automation module (WP-029; architecture.md §6.1, §6.7; ADR-035).

Business rules, triggers, routing and auto-assignment.

Business rules run inside a record's save; triggers after the commit, from its events. Routing
picks a group; auto-assignment picks a technician inside that group only. Every automated change
names its rule, method and reason (REQ-WI-004), and nothing can loop forever (REQ-RUL-028).

The module owns definitions and settings; it never reads another module's tables. A record type
(incidents first) registers its rule fields and value checks here; the type's own module calls
the public interface below inside its save, in the documented order (REQ-RUL-006).

Public interface: `register_record_type(RecordType(...))`; inside a save
`run_business_rules(...)` (then `refusal_error(...)` for a refusal, `log_trace(...)`),
`route_record(...)` and `auto_assign(...)`.
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.automation.api.routes import router
from app.modules.automation.domain.assignment import AssignmentChoice, RoutingChoice
from app.modules.automation.domain.rules import (
    FieldKind,
    RuleEvent,
    RuleField,
    RulesOutcome,
    TraceLine,
)
from app.modules.automation.events import EVENTS
from app.modules.automation.infra import models as _models  # noqa: F401 - registers the tables
from app.modules.automation.service.assignment import (
    AssignmentResult,
    Member,
    auto_assign,
)
from app.modules.automation.service.business_rules import (
    RulesRun,
    log_trace,
    refusal_error,
    run_business_rules,
)
from app.modules.automation.service.jobs import purge_runs
from app.modules.automation.service.realtime import ROUTES
from app.modules.automation.service.registry import RecordType, register_record_type
from app.modules.automation.service.routing import route_record
from app.modules.automation.service.usage import register_usage_checks
from app.shared.schedules import ScheduleSpec

FEATURE = "incident"  # rules work on incidents first; other types join with their modules

PERMISSIONS = (
    PermissionSpec("automation.view", feature=FEATURE),
    PermissionSpec("automation.manage", feature=FEATURE),
)

register_usage_checks()

module = ModuleSpec(
    name="automation",
    routers=[router],
    events=EVENTS,
    permissions=PERMISSIONS,
    realtime=ROUTES,
    schedules=[ScheduleSpec("automation__purge_runs", 3600, purge_runs)],
)

__all__ = [
    "AssignmentChoice",
    "AssignmentResult",
    "FieldKind",
    "Member",
    "RecordType",
    "RoutingChoice",
    "RuleEvent",
    "RuleField",
    "RulesOutcome",
    "RulesRun",
    "TraceLine",
    "auto_assign",
    "log_trace",
    "module",
    "refusal_error",
    "register_record_type",
    "route_record",
    "run_business_rules",
]
