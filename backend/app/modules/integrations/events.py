"""Event contracts published by the integrations module (WP-024, WP-040).

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


class MailBlockRuleChanged(DomainEvent):
    """A block rule for unwanted mail was added, changed or removed (WP-046a S6; REQ-INC-026)."""

    event_type: ClassVar[str] = "integrations.mail_block_rule.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "mail_block_rule"

    rule_id: uuid.UUID
    change: Literal["added", "changed", "removed"]


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


class ConnectorFailing(DomainEvent):
    """A connector turned failing: its admins are told once per failure (REQ-INT-005, WP-040).

    Replaces `integrations.mailbox.failing` for mailboxes (kept, and still handled, until the
    contract step).
    """

    event_type: ClassVar[str] = "integrations.connector.failing"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "connector"

    kind: str  # the catalogue code ("mailbox")
    instance_id: uuid.UUID
    reason: str  # a code; the notification shows its label


class ConnectorRecovered(DomainEvent):
    """A failing connector works again: its admins are told once (REQ-INT-005 AC2)."""

    event_type: ClassVar[str] = "integrations.connector.recovered"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "connector"

    kind: str
    instance_id: uuid.UUID


class DirectoryChanged(DomainEvent):
    """A directory connector was added, changed or removed, or a sync run finished (WP-040)."""

    event_type: ClassVar[str] = "integrations.directory.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "directory_connector"

    directory_id: uuid.UUID
    change: Literal["added", "changed", "removed", "synced"]


class ConnectorSettingsChanged(DomainEvent):
    """A tenant's connector defaults were saved (WP-040, D-041): the settings card refetches."""

    event_type: ClassVar[str] = "integrations.connector_settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "connector_settings"

    changed_fields: list[str]


EVENTS: tuple[type[DomainEvent], ...] = (
    MailboxChanged,
    MailboxFailing,
    MailboxCredentialExpiring,
    MailboxMailHeld,
    ConnectorFailing,
    ConnectorRecovered,
    DirectoryChanged,
    ConnectorSettingsChanged,
    MailBlockRuleChanged,
)
