"""Event contracts of the list-settings store (registered by the `system` module, hence the prefix).

IDs and keys only: never a view's name or filter.
"""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class ListSettingsChanged(DomainEvent):
    """A person's settings or saved view of one list changed: their other windows follow."""

    event_type: ClassVar[str] = "system.list_settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "list_setting"

    user_id: uuid.UUID
    list_key: str
    view_key: str
    change: str  # "saved" or "removed"


EVENTS: tuple[type[DomainEvent], ...] = (ListSettingsChanged,)
