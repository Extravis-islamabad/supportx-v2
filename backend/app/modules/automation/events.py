"""Event contracts published by automation (WP-029). IDs and codes only, never record values."""

import uuid
from typing import Any, ClassVar, Literal

from pydantic import Field

from app.shared.events import DomainEvent


class AutomationChanged(DomainEvent):
    """A business rule, routing rule, trigger or setting was added, changed, reordered or removed.

    Admin screens reload the list; the engine reads definitions per save, so nothing is cached.
    """

    event_type: ClassVar[str] = "automation.definition.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "automation"

    kind: Literal[
        "business_rule",
        "routing_rule",
        "routing_settings",
        "assignment_settings",
        "trigger",
        "transition_settings",
    ]
    definition_id: uuid.UUID | None
    record_type: str | None
    change: Literal["created", "updated", "deleted", "reordered"]


class AvailabilityChanged(DomainEvent):
    """A technician set themselves (or was set) Available or Away (REQ-ASG-006 AC3: live)."""

    event_type: ClassVar[str] = "automation.availability.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "user"

    user_id: uuid.UUID
    state: Literal["available", "away"]


class AssignmentWaiting(DomainEvent):
    """Auto-assignment found nobody (REQ-ASG-011): the record waits in its group's queue.

    The group head is told (notifications, WP-023) once per record; the record is offered again
    when a member becomes available.
    """

    event_type: ClassVar[str] = "automation.assignment.waiting"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item"

    record_type: str
    record_id: uuid.UUID
    group_id: uuid.UUID
    reason: Literal["nobody_available", "all_at_cap", "no_members"]


class AutomationStopped(DomainEvent):
    """A loop cap was hit (REQ-RUL-028): the chain stopped; the record and owners are told."""

    event_type: ClassVar[str] = "automation.loop.stopped"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item"

    record_type: str
    record_id: uuid.UUID
    cap: Literal["chain_depth", "per_minute"]
    automation_ids: list[uuid.UUID]


class WorkflowInstanceChanged(DomainEvent):
    """A workflow instance moved on, waited, failed or ended (WP-048b, REQ-WF-023, -025).

    The record's execution view and the overview refresh; IDs and codes only.
    """

    event_type: ClassVar[str] = "automation.workflow_instance.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "workflow_instance"

    instance_id: uuid.UUID
    workflow_id: uuid.UUID
    record_type: str
    record_id: uuid.UUID
    status: Literal["running", "waiting", "failed", "finished", "cancelled"]
    version: int


class WorkflowChanged(DomainEvent):
    """A workflow was made, its draft saved, published, enabled or disabled (WP-048b).

    The workflows list and an open designer refresh; IDs and codes only.
    """

    event_type: ClassVar[str] = "automation.workflow.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "workflow"

    workflow_id: uuid.UUID
    record_type: str
    change: Literal["created", "draft_saved", "published", "enabled", "disabled"]
    version: int


class WorkflowCommandFinished(DomainEvent):
    """A workflow command an owning module accepted for later is done (WP-048b S2, REQ-WF-014).

    Written by the owning module in the transaction that finished it (an approval's deciding
    vote), through `automation.command_finished`; automation's consumer then continues the
    node: `port` is the output it leaves by (approved, rejected), or `error` refuses it.
    """

    event_type: ClassVar[str] = "automation.workflow.command_finished"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "workflow_instance"

    instance_id: uuid.UUID
    command: str
    ok: bool
    port: str | None = None
    error: str | None = None
    # A function node's outputs, by the variables the node keeps them in (never record data).
    outputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowFunctionRequested(DomainEvent):
    """A function node asks the worker to run a custom function (WP-048b S2; §6.7).

    Never run in the API process: the worker's consumer calls the installation's runner and
    reports back as `WorkflowCommandFinished`. The inputs are the node's own values and the
    names of record fields, read by the worker; `assign` maps outputs to variables.
    """

    event_type: ClassVar[str] = "automation.workflow.function_requested"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "workflow_instance"

    instance_id: uuid.UUID
    command: str
    record_type: str
    record_id: uuid.UUID
    function: str
    inputs: dict[str, Any]
    assign: dict[str, str]
    timeout_seconds: int


class WorkflowWebhookRequested(DomainEvent):
    """A webhook node asks the worker to make one guarded call (WP-048b S2; ADR-043 §8).

    Never sent from a request: the worker's consumer sends it through the shared egress client
    and reports back as `WorkflowCommandFinished`. The record's fields are read by the worker,
    so the outbox holds only their names.
    """

    event_type: ClassVar[str] = "automation.workflow.webhook_requested"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "workflow_instance"

    instance_id: uuid.UUID
    command: str
    record_type: str
    record_id: uuid.UUID
    url: str
    method: str
    headers: dict[str, str]
    fields: list[str]
    status_variable: str | None = None


EVENTS: tuple[type[DomainEvent], ...] = (
    WorkflowChanged,
    WorkflowWebhookRequested,
    WorkflowFunctionRequested,
    WorkflowCommandFinished,
    WorkflowInstanceChanged,
    AutomationChanged,
    AvailabilityChanged,
    AssignmentWaiting,
    AutomationStopped,
)
