"""Event contracts published by the work_items module (WP-020; docs/architecture/events.md).

Payloads carry IDs, codes and changed field *names* only, never subjects or descriptions
(architecture.md §8.2). `audience_before` lists where the record was visible before the change
(group, site, technician, unassigned site queue), so live lists can drop a row that moved away
from a viewer's audience as well as add it where it arrived.
"""

import uuid
from typing import ClassVar, Literal

from pydantic import BaseModel, Field

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

    # Who it was assigned to on creation (notifications tell them; WP-023). Additive: older
    # events have none.
    technician_id: uuid.UUID | None = None


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


class _ConversationEvent(DomainEvent):
    aggregate_type: ClassVar[str] = "work_item_conversation"

    work_item_id: uuid.UUID
    entry_id: uuid.UUID
    kind: str
    visibility: str


class WorkItemConversationAdded(_ConversationEvent):
    """A reply or note was saved (WP-020b). Notifications (WP-023) and email (WP-024) start here.

    `mentioned_ids` holds only people who may see the record (REQ-INC-063 AC2); `first_response`
    is true when this entry stamped the record's first response (REQ-INC-065).
    """

    event_type: ClassVar[str] = "work_items.conversation.added"
    schema_version: ClassVar[int] = 1

    delivery_state: str | None = None
    first_response: bool = False
    mentioned_ids: list[uuid.UUID] = Field(default_factory=list)
    # An automatic reply (an out-of-office): recorded, it moves nothing and notifies nobody
    # (REQ-INC-024 AC2; WP-024). Additive: older events read as False.
    automatic: bool = False


class WorkItemConversationVisibilityChanged(_ConversationEvent):
    """A note was made public or private (REQ-INC-061 AC3). `visibility` is the new one."""

    event_type: ClassVar[str] = "work_items.conversation.visibility_changed"
    schema_version: ClassVar[int] = 1

    from_visibility: str


class _FollowerEvent(DomainEvent):
    aggregate_type: ClassVar[str] = "work_item_follower"

    work_item_id: uuid.UUID
    user_id: uuid.UUID
    reason: str
    grants_access: bool


class WorkItemFollowerAdded(_FollowerEvent):
    """Someone follows the record now (REQ-INC-056/151)."""

    event_type: ClassVar[str] = "work_items.follower.added"
    schema_version: ClassVar[int] = 1


class WorkItemFollowerRemoved(_FollowerEvent):
    """Someone stopped following (themselves, or removed by someone allowed to)."""

    event_type: ClassVar[str] = "work_items.follower.removed"
    schema_version: ClassVar[int] = 1


class WorkItemReplyTemplatesChanged(DomainEvent):
    """A reply template was added, changed or removed (open composers reload the list)."""

    event_type: ClassVar[str] = "work_items.reply_templates.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item_reply_template"

    type: str
    template_id: uuid.UUID


class WorkItemViewChanged(DomainEvent):
    """A saved view was added, changed or removed (WP-020d; the view menus reload)."""

    event_type: ClassVar[str] = "work_items.view.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item_view"

    view_id: uuid.UUID
    type: str
    owner_id: uuid.UUID
    visibility: str


class WorkItemListSettingsChanged(DomainEvent):
    """A user's columns, sort or page size of one view changed (their other windows follow)."""

    event_type: ClassVar[str] = "work_items.list_settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item_list_setting"

    user_id: uuid.UUID
    type: str
    view_key: str


class WorkItemBulkJobProgressed(DomainEvent):
    """A bulk job started, finished a batch or ended (REQ-INC-120 AC3; counts only)."""

    event_type: ClassVar[str] = "work_items.bulk_job.progressed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item_bulk_job"

    job_id: uuid.UUID
    type: str
    requested_by: uuid.UUID | None
    status: str
    processed: int
    total: int


class WorkItemPartChanged(DomainEvent):
    """A task, worklog or link of a record was added, changed or removed (WP-020e).

    The record's screens refresh that part; IDs only, never the part's content.
    """

    event_type: ClassVar[str] = "work_items.part.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item"

    work_item_id: uuid.UUID
    part: Literal["task", "worklog", "link"]
    part_id: uuid.UUID
    change: Literal["added", "changed", "removed"]


EVENTS: tuple[type[DomainEvent], ...] = (
    WorkItemCreated,
    WorkItemUpdated,
    WorkItemStatusChanged,
    WorkItemAssigned,
    WorkItemDeleted,
    WorkItemRestored,
    WorkItemSettingsChanged,
    WorkItemConversationAdded,
    WorkItemConversationVisibilityChanged,
    WorkItemFollowerAdded,
    WorkItemFollowerRemoved,
    WorkItemReplyTemplatesChanged,
    WorkItemViewChanged,
    WorkItemListSettingsChanged,
    WorkItemBulkJobProgressed,
    WorkItemPartChanged,
)
