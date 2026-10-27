"""Event contract of the mail service (registered by the `system` module, hence the prefix).

The payload carries the message's ID and purpose only: never addresses, subjects or bodies.
"""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class MailQueued(DomainEvent):
    """A message was queued; the mail worker sends it."""

    event_type: ClassVar[str] = "system.mail.queued"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "mail_message"

    mail_id: uuid.UUID
    kind: str


EVENTS: tuple[type[DomainEvent], ...] = (MailQueued,)
