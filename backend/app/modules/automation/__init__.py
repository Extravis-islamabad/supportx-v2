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
from app.modules.automation.api.workflows import router as workflows_router
from app.modules.automation.domain.assignment import AssignmentChoice, RoutingChoice
from app.modules.automation.domain.rules import (
    FieldKind,
    RuleEvent,
    RuleField,
    RulesOutcome,
    TraceLine,
)
from app.modules.automation.domain.triggers import People, Relative, TriggerEvent
from app.modules.automation.events import (
    EVENTS,
    WorkflowCommandFinished,
    WorkflowFunctionRequested,
    WorkflowWebhookRequested,
)
from app.modules.automation.infra import models as _models  # noqa: F401 - registers the tables
from app.modules.automation.service import (
    person_data,
    workflow_events,
    workflow_jobs,
    workflow_scheduler,
)
from app.modules.automation.service.assignment import (
    AssignmentResult,
    Member,
    auto_assign,
    away_user_ids,
    step_owner,
)
from app.modules.automation.service.business_rules import (
    RulesRun,
    log_trace,
    record_runs,
    refusal_error,
    run_business_rules,
)
from app.modules.automation.service.functions import (
    FunctionOutcome,
    FunctionRunner,
    register_function_runner,
)
from app.modules.automation.service.jobs import purge_runs
from app.modules.automation.service.realtime import CHANNELS, ROUTES
from app.modules.automation.service.registry import (
    Applier,
    AutomatedChange,
    CommandResult,
    CommandRunner,
    FactsReader,
    Noter,
    RecordEditCheck,
    RecordEvent,
    RecordLabeler,
    RecordType,
    RecordViewCheck,
    TemplateCheck,
    record_type,
    register_event_reader,
    register_record_type,
)
from app.modules.automation.service.routing import route_record
from app.modules.automation.service.transitions import NOT_FOR_YOU as TRANSITION_NOT_FOR_YOU
from app.modules.automation.service.transitions import Audience as TransitionAudience
from app.modules.automation.service.transitions import audience as transition_audience
from app.modules.automation.service.transitions import list_settings as transition_settings
from app.modules.automation.service.transitions import refusal as transition_refusal
from app.modules.automation.service.triggers import TRIGGER_EVENT_TYPES, on_record_event
from app.modules.automation.service.usage import register_usage_checks
from app.modules.automation.service.workflow_events import command_finished
from app.shared.events import ConsumerSpec
from app.shared.schedules import ScheduleSpec

FEATURE = "incident"  # rules work on incidents first; other types join with their modules

WORKFLOWS = "workflows"  # the licence feature visual workflows sit behind (Professional)

PERMISSIONS = (
    PermissionSpec("automation.view", feature=FEATURE, defaults=(("service_desk_manager", "all"),)),
    PermissionSpec(
        "automation.manage", feature=FEATURE, defaults=(("service_desk_manager", "all"),)
    ),
    # WP-048b: designing and publishing workflows; starting one on a record and reading its runs.
    PermissionSpec(
        "workflows.manage", feature=WORKFLOWS, defaults=(("service_desk_manager", "all"),)
    ),
    PermissionSpec(
        "workflows.run",
        feature=WORKFLOWS,
        defaults=(("service_desk_manager", "all"), ("technician", "all")),
    ),
)

register_usage_checks()

# Automation's slice of a person's erasure (ADR-052): at import.
person_data.register()

module = ModuleSpec(
    name="automation",
    routers=[router, workflows_router],
    router_features=[None, WORKFLOWS],
    events=EVENTS,
    permissions=PERMISSIONS,
    realtime=ROUTES,
    channels=CHANNELS,
    # Triggers and a move's "after" actions run after the commit, from its events (REQ-RUL-009).
    consumers=[
        ConsumerSpec(
            name="automation__triggers",
            event_types=TRIGGER_EVENT_TYPES,
            handler=on_record_event,
        ),
        # An instance that moved on wakes its Temporal waker (off without Temporal).
        workflow_scheduler.SCHEDULER,
        # Waiting workflow instances hear their record's committed changes (ADR-043 §5).
        ConsumerSpec(
            name="automation__workflow_events",
            event_types=TRIGGER_EVENT_TYPES,
            handler=workflow_events.on_record_event,
        ),
        # A webhook node's call, sent by the worker through the guarded client (ADR-043 §8).
        ConsumerSpec(
            name="automation__workflow_webhooks",
            event_types=(WorkflowWebhookRequested.event_type,),
            handler=workflow_events.on_webhook_requested,
        ),
        # A function node's request, run by the worker through the runner port (§6.7).
        ConsumerSpec(
            name="automation__workflow_functions",
            event_types=(WorkflowFunctionRequested.event_type,),
            handler=workflow_events.on_function_requested,
        ),
        # A command decided later (an approval node) continues its node (REQ-WF-014).
        ConsumerSpec(
            name="automation__workflow_commands",
            event_types=(WorkflowCommandFinished.event_type,),
            handler=workflow_events.on_command_finished,
        ),
    ],
    schedules=[
        ScheduleSpec("automation__purge_runs", 3600, purge_runs),
        # Due workflow timers, the net beneath Temporal's waker (ADR-043 §5).
        ScheduleSpec("automation__workflow_wake", 60, workflow_events.wake_due),
        # Bulk retry and cancel of instances (WP-048b S3b, REQ-WF-025 AC2).
        ScheduleSpec("automation__workflow_jobs", 5, workflow_jobs.run_jobs),
    ],
)

__all__ = [
    "TRANSITION_NOT_FOR_YOU",
    "Applier",
    "AssignmentChoice",
    "AssignmentResult",
    "AutomatedChange",
    "CommandResult",
    "CommandRunner",
    "FactsReader",
    "FieldKind",
    "FunctionOutcome",
    "FunctionRunner",
    "Member",
    "Noter",
    "People",
    "RecordEditCheck",
    "RecordEvent",
    "RecordLabeler",
    "RecordType",
    "RecordViewCheck",
    "Relative",
    "RoutingChoice",
    "RuleEvent",
    "RuleField",
    "RulesOutcome",
    "RulesRun",
    "TemplateCheck",
    "TraceLine",
    "TransitionAudience",
    "TriggerEvent",
    "auto_assign",
    "away_user_ids",
    "command_finished",
    "log_trace",
    "module",
    "record_runs",
    "record_type",
    "refusal_error",
    "register_event_reader",
    "register_function_runner",
    "register_record_type",
    "route_record",
    "run_business_rules",
    "step_owner",
    "transition_audience",
    "transition_refusal",
    "transition_settings",
]
