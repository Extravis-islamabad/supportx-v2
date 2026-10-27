"""Record types that automation works on (WP-029; REQ-RUL-008 shape, incidents first).

A module registers each of its record types once, at import: which fields rules may test and
set (with custom fields), and how to check values a rule would set *now* (a group made inactive
since the rule was saved). The engine never reads the module's tables itself (CLAUDE.md rule e).
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.automation.domain.rules import JsonValue, RuleField
from app.modules.automation.domain.triggers import TriggerEvent
from app.shared.events import EventEnvelope

FieldsProvider = Callable[[AsyncSession], Awaitable[Mapping[str, RuleField]]]
# field → problem code for the values given (only fields with a problem are returned).
ValueChecker = Callable[[AsyncSession, Mapping[str, JsonValue]], Awaitable[Mapping[str, str]]]


@dataclass(frozen=True)
class RecordType:
    """What automation needs to know about one record type."""

    code: str  # "incident"
    fields: FieldsProvider
    check_values: ValueChecker
    # Category → suggested group (routing, REQ-ASG-001), when the type has categories.
    category_group: Callable[[AsyncSession, str], Awaitable[str | None]] | None = None
    # Triggers and transition "after" actions (WP-029 part 2), run after the commit:
    facts: "FactsReader | None" = None
    apply: "Applier | None" = None
    add_note: "Noter | None" = None


@dataclass(frozen=True)
class AutomatedChange:
    """Who is making an automated change, for the record's history and the event's cause."""

    ref: Mapping[str, Any]  # automation_ref in history: kind, trigger or action, its name
    cause_id: uuid.UUID  # the run log entry; the change's event carries it as causation


# The record's current values as rules see them (None: gone or in the trash).
FactsReader = Callable[[AsyncSession, uuid.UUID], Awaitable[Mapping[str, JsonValue] | None]]
# Set fields through the record's own save path (business rules run again); returns the names
# of the fields that changed (empty: nothing to change).
Applier = Callable[
    [AsyncSession, uuid.UUID, Mapping[str, JsonValue], AutomatedChange], Awaitable[list[str]]
]
Noter = Callable[[AsyncSession, uuid.UUID, str, AutomatedChange], Awaitable[None]]


@dataclass(frozen=True)
class RecordEvent:
    """A committed event, read by the module that published it (REQ-RUL-009)."""

    record_type: str
    record_id: uuid.UUID
    event: TriggerEvent | None  # None: nothing a trigger reacts to (still "after" a move)
    changed: Sequence[str] = ()  # field names the event says changed
    known_before: Mapping[str, JsonValue] = field(default_factory=dict)  # old values it carries
    action: str | None = None  # the life-cycle action of a status move


EventReader = Callable[[AsyncSession, EventEnvelope], Awaitable[RecordEvent | None]]
_READERS: dict[str, EventReader] = {}


def register_event_reader(event_types: Sequence[str], reader: EventReader) -> None:
    """The publishing module says how to read its events for triggers (at import)."""
    for event_type in event_types:
        _READERS[event_type] = reader


def event_reader(event_type: str) -> EventReader | None:
    """The reader of an event type, or None."""
    return _READERS.get(event_type)


_TYPES: dict[str, RecordType] = {}


def register_record_type(record_type: RecordType) -> None:
    """Called by the owning module when it is imported (idempotent)."""
    _TYPES[record_type.code] = record_type


def record_type(code: str) -> RecordType | None:
    """A registered record type, or None."""
    return _TYPES.get(code)


def record_types() -> list[str]:
    """Every registered record type code."""
    return sorted(_TYPES)
