"""Event contracts published by the integrations module (WP-024).

Payloads carry IDs and codes only (architecture.md §8.2): never an address, a password or mail.
"""

import uuid
from datetime import datetime
from typing import ClassVar, Literal

from app.shared.events import DomainEvent


class MailboxChanged(DomainEvent):
    """A mailbox was added, changed or removed, or a fetch changed its state or its mail."""

    event_type: ClassVar[str] = "integrations.mailbox.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "mailbox"

    mailbox_id: uuid.UUID
    change: Literal["added", "changed", "removed", "fetched"]


class MailboxFailing(DomainEvent):
    """A mailbox stopped working, or fails for a new reason: its admins are told (never silent)."""

    event_type: ClassVar[str] = "integrations.mailbox.failing"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "mailbox"

    mailbox_id: uuid.UUID
    reason: str  # a code; the notification shows its label


class MailboxCredentialExpiring(DomainEvent):
    """The OAuth app's secret or certificate expires within the warning period (REQ-INT-050)."""

    event_type: ClassVar[str] = "integrations.mailbox.credential_expiring"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "mailbox"

    mailbox_id: uuid.UUID
    expires_at: datetime


class MailboxMailHeld(DomainEvent):
    """A sender went over the flood limit: their mail waits in the review queue (REQ-NTF-023).

    Raised once per flood (the first message held for it in the hour), so admins are told once,
    not per message. No address in the payload: the review queue shows who it is.
    """

    event_type: ClassVar[str] = "integrations.mailbox.mail_held"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "mailbox"

    mailbox_id: uuid.UUID
    reason: str  # "sender_rate"


EVENTS: tuple[type[DomainEvent], ...] = (
    MailboxChanged,
    MailboxFailing,
    MailboxCredentialExpiring,
    MailboxMailHeld,
)
