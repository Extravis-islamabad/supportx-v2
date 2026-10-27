"""Event contracts published by the metadata module (WP-026; docs/architecture/events.md).

Payloads carry the field's ID, entity, key and changed setting names only.
"""

import uuid
from typing import ClassVar

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


EVENTS: tuple[type[DomainEvent], ...] = (CustomFieldChanged,)
