"""Event contract of the mail service (registered by the `system` module, hence the prefix).

The payload carries the message's ID and purpose only: never addresses, subjects or bodies.
"""

import uuid
from datetime import datetime
from typing import ClassVar, Literal

from app.shared.events import DomainEvent


class MailQueued(DomainEvent):
    """A message was queued; the mail worker sends it."""

    event_type: ClassVar[str] = "system.mail.queued"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "mail_message"

    mail_id: uuid.UUID
    kind: str


class MailStateChanged(DomainEvent):
    """A send attempt ended: sent, failed for good, or to be tried again (REQ-INC-059).

    The notification engine moves the delivery log and the record's message along with it.
    """

    event_type: ClassVar[str] = "system.mail.state_changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "mail_message"

    mail_id: uuid.UUID
    kind: str
    state: Literal["sent", "retrying", "failed"]
    failure: str | None = None  # a code (label `delivery_reason.<code>`), never server text
    at: datetime


EVENTS: tuple[type[DomainEvent], ...] = (MailQueued, MailStateChanged)
