"""Event contracts published by the integrations module (WP-024).

Payloads carry IDs and codes only (architecture.md §8.2): never an address, a password or mail.
"""

import uuid
from typing import ClassVar, Literal

from app.shared.events import DomainEvent


class MailboxChanged(DomainEvent):
    """A mailbox was added, changed or removed, or a fetch changed its state or its mail."""

    event_type: ClassVar[str] = "integrations.mailbox.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "mailbox"

    mailbox_id: uuid.UUID
    change: Literal["added", "changed", "removed", "fetched"]


EVENTS: tuple[type[DomainEvent], ...] = (MailboxChanged,)
