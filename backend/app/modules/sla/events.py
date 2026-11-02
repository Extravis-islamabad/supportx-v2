"""Event contracts published by the sla module (WP-025; docs/architecture/events.md).

Payloads carry IDs and changed field names only, never names or dates (rule c). The set-up and
clock events (sessions 1 and 2), and `warning`, `breached` and `escalated` (session 3).
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


class SlaApplied(DomainEvent):
    """A record got its SLA policy, or another one after a change (`kinds`: targets started)."""

    event_type: ClassVar[str] = "sla.record.applied"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "sla_record"

    record_type: str
    record_id: uuid.UUID
    policy_id: uuid.UUID | None
    reason: str
    kinds: list[str]


class _ClockEvent(DomainEvent):
    """One target clock of one record changed state."""

    aggregate_type: ClassVar[str] = "sla_record"
    schema_version: ClassVar[int] = 1

    record_type: str
    record_id: uuid.UUID
    kind: str


class SlaPaused(_ClockEvent):
    """The record entered an on-hold status: the target's clock stopped counting."""

    event_type: ClassVar[str] = "sla.target.paused"


class SlaResumed(_ClockEvent):
    """The record left the on-hold status: the clock counts again, with a new due moment."""

    event_type: ClassVar[str] = "sla.target.resumed"


class SlaMet(_ClockEvent):
    """The target was met (on time, late, or by the resolution)."""

    event_type: ClassVar[str] = "sla.target.met"


class SlaStopped(_ClockEvent):
    """Closed or canceled before the target was met; never a breach by itself."""

    event_type: ClassVar[str] = "sla.target.stopped"


class SlaRecalculated(_ClockEvent):
    """A new due moment: priority, policy, calendar or reopen."""

    event_type: ClassVar[str] = "sla.target.recalculated"


class SlaSetByHand(_ClockEvent):
    """A person set the due date by hand, or cleared it (REQ-SLA-028; who and why on the target)."""

    event_type: ClassVar[str] = "sla.target.set_by_hand"


class SlaWarning(_ClockEvent):
    """The target reached its warning point (REQ-SLA-019)."""

    event_type: ClassVar[str] = "sla.target.warning"


class SlaBreached(_ClockEvent):
    """The target's due moment passed while it was open (REQ-SLA-020); the stamp stays."""

    event_type: ClassVar[str] = "sla.target.breached"


class SlaEscalated(_ClockEvent):
    """An escalation level ran, once (REQ-SLA-022). `run_id` names the run and its level.

    `notify` False: the level only acted, or the tenant-wide switch held its messages.
    """

    event_type: ClassVar[str] = "sla.target.escalated"

    run_id: uuid.UUID
    position: int
    notify: bool


EVENTS: tuple[type[DomainEvent], ...] = (
    SlaCalendarSaved,
    SlaCalendarDeleted,
    SlaHolidayListSaved,
    SlaHolidayListDeleted,
    SlaPolicySaved,
    SlaPolicyDeleted,
    SlaPoliciesReordered,
    SlaSettingsSaved,
    SlaApplied,
    SlaPaused,
    SlaResumed,
    SlaMet,
    SlaStopped,
    SlaSetByHand,
    SlaRecalculated,
    SlaWarning,
    SlaBreached,
    SlaEscalated,
)
