"""Event contracts published by the notifications module (WP-023; docs/architecture/events.md).

Payloads carry IDs and codes only, never titles, addresses or text (architecture.md §8.2): the
notification centre fetches an entry by its ID, with the person's own permissions.
"""

import uuid
from datetime import datetime
from typing import ClassVar

from app.shared.events import DomainEvent


class NotificationCreated(DomainEvent):
    """A new entry in a person's notification centre (their personal channel shows it live)."""

    event_type: ClassVar[str] = "notifications.notification.created"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "notification"

    notification_id: uuid.UUID
    user_id: uuid.UUID
    urgent: bool


class NotificationsRead(DomainEvent):
    """A person read entries (one, or all of them): their other devices update the badge."""

    event_type: ClassVar[str] = "notifications.notification.read"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "notification"

    user_id: uuid.UUID
    notification_ids: list[uuid.UUID]  # empty: every unread entry
    all: bool


class DeliveryRecorded(DomainEvent):
    """A notification was sent, held back or failed for a record (the record's log, REQ-INC-134)."""

    event_type: ClassVar[str] = "notifications.delivery.recorded"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "notification_delivery"

    delivery_id: uuid.UUID
    record_type: str
    record_id: uuid.UUID
    channel: str
    state: str


class RuleChanged(DomainEvent):
    """An admin changed the rule of one event (on/off, recipients, channels, conditions)."""

    event_type: ClassVar[str] = "notifications.rule.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "notification_rule"

    event_code: str
    changed_fields: list[str]


class PreferencesChanged(DomainEvent):
    """A person changed their notification preferences (every device applies them at once)."""

    event_type: ClassVar[str] = "notifications.preferences.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "notification_preferences"

    user_id: uuid.UUID


class MailNotSentSummary(DomainEvent):
    """One run gave up on e-mails that waited 7 days for outgoing mail to be set up (D-157).

    One per run and tenant, whatever the count: the people who set mail up hear it once, in the
    app (the summary is no e-mail: there is no mail to send it with). Counts and a time only.
    """

    event_type: ClassVar[str] = "notifications.mail.not_sent_summary"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "notification_delivery"

    summary_id: uuid.UUID
    count: int
    oldest_at: datetime


EVENTS: tuple[type[DomainEvent], ...] = (
    NotificationCreated,
    NotificationsRead,
    DeliveryRecorded,
    RuleChanged,
    PreferencesChanged,
    MailNotSentSummary,
)
