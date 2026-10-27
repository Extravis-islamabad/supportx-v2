"""Event contracts published by automation (WP-029). IDs and codes only, never record values."""

import uuid
from typing import ClassVar, Literal

from app.shared.events import DomainEvent


class AutomationChanged(DomainEvent):
    """A business rule, routing rule, trigger or setting was added, changed, reordered or removed.

    Admin screens reload the list; the engine reads definitions per save, so nothing is cached.
    """

    event_type: ClassVar[str] = "automation.definition.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "automation"

    kind: Literal[
        "business_rule", "routing_rule", "routing_settings", "assignment_settings", "trigger"
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


EVENTS: tuple[type[DomainEvent], ...] = (
    AutomationChanged,
    AvailabilityChanged,
    AssignmentWaiting,
    AutomationStopped,
)
