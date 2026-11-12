"""Event contracts published by the work_items module (WP-020; docs/architecture/events.md).

Payloads carry IDs, codes and changed field *names* only, never subjects or descriptions
(architecture.md §8.2). `audience_before` lists where the record was visible before the change
(group, site, technician, unassigned site queue), so live lists can drop a row that moved away
from a viewer's audience as well as add it where it arrived.
"""

import uuid
from datetime import datetime
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


class ServiceRequestReadyToFulfil(_WorkItemEvent):
    """A request's last required task is done and nobody is on it (D-154, "E1 follows d").

    It is not fulfilled by itself; its group is told once, in the app, to assign someone.
    """

    event_type: ClassVar[str] = "work_items.service_request.ready_to_fulfil"
    schema_version: ClassVar[int] = 1

    group_id: uuid.UUID | None


class WorkItemStageChanged(_WorkItemEvent):
    """A staged record entered another stage (ADR-041 §6), with the status move that did it.

    `stages_entered` lists every stage entered in order (an automatic advance from a completing
    status can pass through more than one); `entry_id` is the entry of the stage it is in now.
    """

    event_type: ClassVar[str] = "work_items.work_item.stage_changed"
    schema_version: ClassVar[int] = 1

    from_stage: str
    to_stage: str
    stages_entered: list[str]
    entry_id: uuid.UUID
    path: str
    automatic: bool = False


class WorkItemRolesChanged(_WorkItemEvent):
    """Who holds a named role on the record changed (WP-058a s4; REQ-REL-023).

    The holders before and after, as IDs, so the lists of both the old and the new holders
    refresh (lane B's review).
    """

    event_type: ClassVar[str] = "work_items.work_item.roles_changed"
    schema_version: ClassVar[int] = 1

    role: str
    users_before: list[uuid.UUID]
    users_after: list[uuid.UUID]
    groups_before: list[uuid.UUID]
    groups_after: list[uuid.UUID]


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


class WorkItemPortalSettingsChanged(DomainEvent):
    """The tenant's portal settings changed (WP-032 D8): open portals reload them live."""

    event_type: ClassVar[str] = "work_items.portal_settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item_portal_settings"

    changed_fields: list[str]


class WorkItemApprovalSettingsChanged(DomainEvent):
    """The tenant's approval settings changed (the D-146 chair): open settings pages reload."""

    event_type: ClassVar[str] = "work_items.approval_settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item_approval_settings"

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


class WorkItemConversationDeliveryChanged(_ConversationEvent):
    """A reply's e-mail moved: waiting, queued, retrying, sent or failed (REQ-INC-059).

    Raised when the notification engine learns how the e-mail to the requester went; the timeline
    refetches the entry (codes only, never an address or the server's text).
    """

    event_type: ClassVar[str] = "work_items.conversation.delivery_changed"
    schema_version: ClassVar[int] = 1

    delivery_state: str
    delivery_reason: str | None = None


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


class WorkItemWorkflowNotice(DomainEvent):
    """A workflow's notify node tells people about the record (WP-048b S2, REQ-WF-022).

    The one notification engine sends it (work_items' record source maps it to
    `<type>.workflow_notice`): access checked at send time, personal preferences, the delivery
    log. The audience is resolved then; the texts are the node's own, per language.
    """

    event_type: ClassVar[str] = "work_items.workflow.notice"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item"

    record_id: uuid.UUID
    type: str
    instance_id: uuid.UUID
    audience: dict[str, list[str]]  # relatives, user_ids, group_ids
    subject: dict[str, str]
    body: dict[str, str]


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
    # Tasks only, additive (WP-048b, lane C's task node waits for "done"): the task's status
    # after the change, a code (open, in_progress, done, ...); None for other parts.
    task_status: str | None = None


class WorkItemAssetLinkChanged(DomainEvent):
    """An asset was linked to a record or unlinked (REQ-AST-025). IDs only.

    The record's screens refresh its assets; the assets module may hear it too (an asset's
    "linked to my tickets" scope, D-153).
    """

    event_type: ClassVar[str] = "work_items.asset_link.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item"

    work_item_id: uuid.UUID
    asset_id: uuid.UUID
    change: Literal["added", "removed"]
    # Linked as the record was made, from a form prefilled on the asset page (WP-049b S4):
    # the asset's history says "INC-n raised from this asset". Additive; false for older events.
    at_creation: bool = False


class WorkItemPartChangedV2(DomainEvent):
    """As WorkItemPartChanged, with staged records' plan sections, schedules and downtimes.

    WP-058a s4. New allowed values retype `part`, so a new schema version
    (docs/architecture/events.md "Versioning"); v1 stays registered, and tasks, worklogs and
    links still publish it.
    """

    event_type: ClassVar[str] = "work_items.part.changed"
    schema_version: ClassVar[int] = 2
    aggregate_type: ClassVar[str] = "work_item"

    work_item_id: uuid.UUID
    part: Literal["task", "worklog", "link", "plan_section", "stage_schedule", "downtime"]
    part_id: uuid.UUID
    change: Literal["added", "changed", "removed"]


ApprovalChange = Literal["opened", "decided", "closed"]


class WorkItemPartChangedV3(DomainEvent):
    """As V2, with a record's checklists, personal reminders and timers (WP-046a S2/S3).

    New allowed values retype `part`, so a new schema version (docs/architecture/events.md
    "Versioning"); v1 and v2 stay registered and keep publishing their parts. A reminder or a
    running timer (REQ-INC-082, -069) is its owner's only: realtime tells their personal
    channel, never the record's. `timer` is reserved here for S3, so S3 needs no V4.
    """

    event_type: ClassVar[str] = "work_items.part.changed"
    schema_version: ClassVar[int] = 3
    aggregate_type: ClassVar[str] = "work_item"

    work_item_id: uuid.UUID
    part: Literal[
        "task",
        "worklog",
        "link",
        "plan_section",
        "stage_schedule",
        "downtime",
        "checklist",
        "reminder",
        "timer",
    ]
    part_id: uuid.UUID
    change: Literal["added", "changed", "removed"]


class WorkItemApprovalChanged(DomainEvent):
    """An approval was opened, decided, closed or withdrawn (WP-030 s2, REQ-SR-024).

    `approver_id` None: the approval administrators hold it. IDs and codes only, never the
    comment; the record's screens and the approver's drawer refetch through the API.
    """

    event_type: ClassVar[str] = "work_items.approval.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item"

    work_item_id: uuid.UUID
    type: str
    approval_id: uuid.UUID
    approver_id: uuid.UUID | None
    state: str
    change: ApprovalChange


class ChangeBoardChanged(DomainEvent):
    """A change advisory board was added, changed or removed (WP-045b S2; settings reload)."""

    event_type: ClassVar[str] = "work_items.change_board.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "change_board"

    board_id: uuid.UUID
    change: str


class ChangeWindowChanged(DomainEvent):
    """A freeze or maintenance window was added, changed or removed (WP-045c; ADR-042).

    Open calendars and settings pages refetch; IDs only, never the window's text (rule 5c).
    """

    event_type: ClassVar[str] = "work_items.change_window.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "change_window"

    window_id: uuid.UUID
    change: str


class ChangeApprovalNotice(DomainEvent):
    """Someone must hear about a change's approval (WP-045b; REQ-CHG-040, -053; D-144).

    `notice`: `sent_back` (an approved change needs approval again: the implementer, the owner
    and the board are told), `overridden` (the emergency override was used) or
    `board_has_no_members` (the change manager is told). Recorded now; the change
    notifications (WP-056) send it. IDs only: recipients are worked out when it is sent.
    """

    event_type: ClassVar[str] = "work_items.change.approval_notice"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item"

    work_item_id: uuid.UUID
    notice: str
    stage: str | None
    fields: list[str]
    board_id: uuid.UUID | None


class ChangeReminderDue(DomainEvent):
    """A change's reminder is due (WP-045d S3; REQ-CHG-091, -105), claimed once by the sweep.

    `kind`: `window_start` (an hour before the implementation window), `implementation_overdue`
    (the window ended with implementation not complete), `cab_waiting` (it starts within a day
    and `member_id` has not decided) or `review_due`. `window_start` is the window it was
    claimed for: the source re-reads the change at send time and says nothing if the window
    moved meanwhile (lane B). IDs and times only.
    """

    event_type: ClassVar[str] = "work_items.change.reminder_due"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item"

    work_item_id: uuid.UUID
    kind: str
    window_start: datetime | None = None
    member_id: uuid.UUID | None = None


class WorkItemReminderDue(DomainEvent):
    """A person's own reminder on a record alerts them (WP-046a S2; REQ-INC-082 AC1).

    Raised once by the sweep at its time minus its lead. IDs only; the source re-reads the
    reminder at send time and says nothing if it moved, was completed, or its owner can no
    longer see the record (the coordinator).
    """

    event_type: ClassVar[str] = "work_items.reminder.due"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "work_item"

    work_item_id: uuid.UUID
    reminder_id: uuid.UUID
    user_id: uuid.UUID
    remind_at: datetime


class ProblemRepeatDetected(DomainEvent):
    """A repeat incident rule found a new set (WP-044c D16, REQ-PRB-068): the group is told.

    IDs and a count only; the incidents are read through the API by who may create problems.
    """

    event_type: ClassVar[str] = "work_items.problem_repeat.detected"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "problem_repeat_hit"

    hit_id: uuid.UUID
    rule_id: uuid.UUID
    group_id: uuid.UUID | None
    incident_count: int


class ProblemRepeatChanged(DomainEvent):
    """A repeat rule or hit was added, changed, handled or removed (screens refetch)."""

    event_type: ClassVar[str] = "work_items.problem_repeat.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "problem_repeat"

    kind: Literal["rule", "hit"]
    id: uuid.UUID


class WorkItemAssigneeUnavailable(_WorkItemEvent):
    """A rule or escalation could not put the person it names on the record (D-154 "rules").

    The record went to the step's group with nobody on it; the step's owner (or, with none,
    the administrators) is told once, in the app. `reason`: inactive, away or not_in_group.
    """

    event_type: ClassVar[str] = "work_items.work_item.assignee_unavailable"
    schema_version: ClassVar[int] = 1

    person_id: uuid.UUID
    reason: str
    step: str  # the history ref's kind: business_rule, trigger or sla_escalation
    owner_id: uuid.UUID | None = None


EVENTS: tuple[type[DomainEvent], ...] = (
    ServiceRequestReadyToFulfil,
    WorkItemAssetLinkChanged,
    WorkItemAssigneeUnavailable,
    WorkItemCreated,
    WorkItemWorkflowNotice,
    WorkItemUpdated,
    WorkItemStatusChanged,
    WorkItemStageChanged,
    WorkItemRolesChanged,
    WorkItemAssigned,
    WorkItemDeleted,
    WorkItemRestored,
    WorkItemSettingsChanged,
    WorkItemPortalSettingsChanged,
    WorkItemApprovalSettingsChanged,
    WorkItemConversationAdded,
    WorkItemConversationVisibilityChanged,
    WorkItemConversationDeliveryChanged,
    WorkItemFollowerAdded,
    WorkItemFollowerRemoved,
    WorkItemReplyTemplatesChanged,
    WorkItemViewChanged,
    WorkItemListSettingsChanged,
    WorkItemBulkJobProgressed,
    WorkItemPartChanged,
    WorkItemPartChangedV2,
    WorkItemPartChangedV3,
    WorkItemReminderDue,
    WorkItemApprovalChanged,
    ChangeBoardChanged,
    ChangeWindowChanged,
    ChangeApprovalNotice,
    ChangeReminderDue,
    ProblemRepeatDetected,
    ProblemRepeatChanged,
)
