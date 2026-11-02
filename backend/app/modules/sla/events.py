"""Event contracts published by the sla module (WP-025; docs/architecture/events.md).

Payloads carry IDs and changed field names only, never names or dates (rule c). Session 1 has
the set-up events; the clock events (`sla.applied`, `warning`, `paused`, `resumed`, `met`,
`breached`, `escalated`, `recalculated`, `stopped`) come with sessions 2 and 3.
"""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class SlaCalendarSaved(DomainEvent):
    """A working calendar was created or changed (its week, zone, name or holiday lists)."""

    event_type: ClassVar[str] = "sla.calendar.saved"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sla_calendar"

    calendar_id: uuid.UUID
    created: bool
    changed_fields: list[str]


class SlaCalendarDeleted(DomainEvent):
    """A working calendar went to the trash (only when no site, group or policy uses it)."""

    event_type: ClassVar[str] = "sla.calendar.deleted"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sla_calendar"

    calendar_id: uuid.UUID


class SlaHolidayListSaved(DomainEvent):
    """A holiday list or its holidays changed (`holiday_ids`: the holidays added or changed)."""

    event_type: ClassVar[str] = "sla.holiday_list.saved"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sla_holiday_list"

    list_id: uuid.UUID
    created: bool
    changed_fields: list[str]
    holiday_ids: list[uuid.UUID]
    # The calendars that use the list: their business time changed too.
    calendar_ids: list[uuid.UUID]


class SlaHolidayListDeleted(DomainEvent):
    """A holiday list went to the trash; the calendars that used it no longer do."""

    event_type: ClassVar[str] = "sla.holiday_list.deleted"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sla_holiday_list"

    list_id: uuid.UUID
    calendar_ids: list[uuid.UUID]


class SlaPolicySaved(DomainEvent):
    """A policy was created or changed (conditions, targets, enabled, name)."""

    event_type: ClassVar[str] = "sla.policy.saved"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sla_policy"

    policy_id: uuid.UUID
    record_type: str
    created: bool
    changed_fields: list[str]


class SlaPolicyDeleted(DomainEvent):
    """A policy went to the trash (never the fallback)."""

    event_type: ClassVar[str] = "sla.policy.deleted"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sla_policy"

    policy_id: uuid.UUID
    record_type: str


class SlaPoliciesReordered(DomainEvent):
    """The order of a record type's policies changed (first match wins)."""

    event_type: ClassVar[str] = "sla.policies.reordered"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sla_policy"

    record_type: str
    policy_ids: list[uuid.UUID]


class SlaSettingsSaved(DomainEvent):
    """A record type's SLA settings changed (warning point, priority-change or reopen rule)."""

    event_type: ClassVar[str] = "sla.settings.saved"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sla_settings"

    record_type: str
    changed_fields: list[str]


EVENTS: tuple[type[DomainEvent], ...] = (
    SlaCalendarSaved,
    SlaCalendarDeleted,
    SlaHolidayListSaved,
    SlaHolidayListDeleted,
    SlaPolicySaved,
    SlaPolicyDeleted,
    SlaPoliciesReordered,
    SlaSettingsSaved,
)
