"""Event contracts published by the work_items module (WP-020; docs/architecture/events.md).

Payloads carry IDs, codes and changed field *names* only, never subjects or descriptions
(architecture.md §8.2). `audience_before` lists where the record was visible before the change
(group, site, technician, unassigned site queue), so live lists can drop a row that moved away
from a viewer's audience as well as add it where it arrived.
"""

import uuid
from typing import ClassVar

from pydantic import BaseModel

from app.shared.events import DomainEvent


class Audience(BaseModel):
    """Where a record was visible: its group, site, people and whether it was unassigned."""

    group_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    technician_id: uuid.UUID | None = None
    unassigned: bool = False


class _WorkItemEvent(DomainEvent):
    aggregate_type: ClassVar[str] = "work_item"

    work_item_id: uuid.UUID
    type: str
    display_id: str
    status: str
    status_category: str


class WorkItemCreated(_WorkItemEvent):
    """A new work item was saved."""

    event_type: ClassVar[str] = "work_items.work_item.created"
    schema_version: ClassVar[int] = 1


class WorkItemUpdated(_WorkItemEvent):
    """Fields changed (names only)."""

    event_type: ClassVar[str] = "work_items.work_item.updated"
    schema_version: ClassVar[int] = 1

    changed_fields: list[str]
    audience_before: Audience


class WorkItemStatusChanged(_WorkItemEvent):
    """A status action ran (by a person, or automatically after an assignment)."""

    event_type: ClassVar[str] = "work_items.work_item.status_changed"
    schema_version: ClassVar[int] = 1

    action: str
    from_status: str
    to_status: str
    automatic: bool = False


class WorkItemAssigned(_WorkItemEvent):
    """The group or technician changed (assign, reassign, take, unassign)."""

    event_type: ClassVar[str] = "work_items.work_item.assigned"
    schema_version: ClassVar[int] = 1

    group_id: uuid.UUID | None
    technician_id: uuid.UUID | None
    audience_before: Audience


class WorkItemDeleted(_WorkItemEvent):
    """Moved to the trash (soft delete)."""

    event_type: ClassVar[str] = "work_items.work_item.deleted"
    schema_version: ClassVar[int] = 1


class WorkItemRestored(_WorkItemEvent):
    """Taken back out of the trash."""

    event_type: ClassVar[str] = "work_items.work_item.restored"
    schema_version: ClassVar[int] = 1


class WorkItemSettingsChanged(DomainEvent):
    """A type's configuration changed (prefix, default priority, categories ...)."""

    event_type: ClassVar[str] = "work_items.settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item_settings"

    type: str
    changed_fields: list[str]


EVENTS: tuple[type[DomainEvent], ...] = (
    WorkItemCreated,
    WorkItemUpdated,
    WorkItemStatusChanged,
    WorkItemAssigned,
    WorkItemDeleted,
    WorkItemRestored,
    WorkItemSettingsChanged,
)
