"""Event contracts published by the metadata module (WP-026; docs/architecture/events.md).

Payloads carry the field's ID, entity, key and changed setting names only.
"""

import uuid
from typing import ClassVar, Literal

from app.shared.events import DomainEvent


class CustomFieldChanged(DomainEvent):
    """A custom field was added, changed, retired, brought back, removed or reordered."""

    event_type: ClassVar[str] = "metadata.custom_field.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "custom_field"

    custom_field_id: uuid.UUID
    entity: str
    key: str
    change: str  # created, updated, retired, restored, deleted, reordered, index_requested
    changed_fields: list[str]


class CustomFieldSealChanged(DomainEvent):
    """A field's values started or finished being sealed or opened (WP-057 S3b-2b).

    The state and counts only, never a value (the coordinator, S3b-2b).
    """

    event_type: ClassVar[str] = "metadata.custom_field.seal_changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "custom_field"

    custom_field_id: uuid.UUID
    entity: str
    key: str
    seal_state: Literal["plain", "sealing", "sealed", "opening"]
    records: int  # records holding a value of the field
    unreadable: int = 0  # values the job could not open (when opening): left sealed


class CustomFieldSealPaused(DomainEvent):
    """Sealing or opening a field's values paused: the keys are unavailable (WP-057 S3b-2b).

    Once per outage (lane B): the admins are told, and the job tries again by itself.
    """

    event_type: ClassVar[str] = "metadata.custom_field.seal_paused"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "custom_field"

    custom_field_id: uuid.UUID
    entity: str
    key: str
    seal_state: Literal["sealing", "opening"]


EVENTS: tuple[type[DomainEvent], ...] = (
    CustomFieldChanged,
    CustomFieldSealChanged,
    CustomFieldSealPaused,
)
