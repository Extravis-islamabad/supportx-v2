"""Change notifications: what the notification engine may know of a change (WP-045d S3).

Registered through `app.shared.notifications.ports` like problems. The engine does rules,
recipients, templates and channels; this source says which events notify, who is relative to
the change now, and how much of it each person may see. The defaults are Appendix A of
docs/specs/parity/05-changes.md (REQ-CHG-104), and the reminders come from the sweep in
`change_reminders` (REQ-CHG-091, -105).

Who sees what (lane B's review of the design, 2026-11-11):
- staff who may see the change get it in full;
- its requester gets the public side: the number, the title and the status, never CAB names,
  risk details, plans, failure notes or internal notes;
- someone who holds a live approval on it (pending, theirs or the administrators') gets the
  public side too, with their own one-time approval link by e-mail, so an approver without
  `changes.view` (a line manager, a business owner on the CAB) is still told. A decided or
  withdrawn approval gives nothing any more;
- anyone else gets nothing, whatever a rule names (RecordAccess decides per recipient).

Role holders are resolved when the event is sent (REQ-CHG-103 AC2), from the change's own role
holders and the members of the groups holding a role, at most HOLDER_LIMIT per kind; the engine
drops anyone inactive. Replies are delegated to the staff-reply source (lane B's #359), which
keeps their own rule, off by default.
"""

import html
import uuid
from collections.abc import Mapping
from datetime import datetime

import nh3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound, PermissionDenied
from app.modules.identity_access import subject_for, user_names, worker_policy
from app.modules.organization import users_in_groups
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.conversation import EntryKind
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.types import CHANGE
from app.modules.work_items.events import (
    ChangeApprovalNotice,
    ChangeReminderDue,
    WorkItemApprovalChanged,
    WorkItemAssigned,
    WorkItemConversationAdded,
    WorkItemCreated,
    WorkItemStatusChanged,
)
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemApproval,
    WorkItemConversation,
    WorkItemRoleHolder,
    WorkItemStageSchedule,
)
from app.modules.work_items.service import approvals
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import APPROVE_ANY
from app.modules.work_items.service.change_reminders import (
    CAB_STAGE,
    CAB_WAITING,
    IMPLEMENTATION,
    IMPLEMENTED,
    OVERDUE,
    REVIEW,
    REVIEW_DUE,
    WINDOW_START,
)
from app.modules.work_items.service.file_access import sees_private
from app.modules.work_items.service.realtime import RECORD_KIND
from app.modules.work_items.service.staff_reply_notifications import StaffReplyNotifications
from app.shared.action_links import LinkRequest
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    LabelRef,
    NotificationCategory,
    NotificationChannel,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

EXCERPT = 500
HOLDER_LIMIT = 200  # people resolved for one recipient kind (lane B, as the rule-step source)

# Recipient kinds: the change's roles (REQ-CHG-034), its CAB, and who an event names.
REQUESTER = "requester"
OWNER = "change_owner"
MANAGER = "change_manager"
LINE_MANAGER = "line_manager"
IMPLEMENTER = "implementer"
REVIEWER = "reviewer"
CAB = "cab"
APPROVER = "approver"
ADMINISTRATORS = "approval_administrators"
MENTIONED = "mentioned"
MEMBER = "cab_member"
_HELD_ROLES = (MANAGER, LINE_MANAGER, IMPLEMENTER, REVIEWER)
RECIPIENT_KINDS = (
    REQUESTER,
    OWNER,
    *_HELD_ROLES,
    CAB,
    APPROVER,
    ADMINISTRATORS,
    MENTIONED,
    MEMBER,
)

SUBMITTED = "change.submitted"
APPROVAL_REQUESTED = "change.approval_requested"
APPROVAL_FALLBACK = "change.approval_fallback"
APPROVED = "change.approved"
REJECTED = "change.rejected"
CLARIFICATION = "change.clarification"
ASSIGNED = "change.assigned"
IMPLEMENTED_EVENT = "change.implemented"
FAILED = "change.implementation_failed"
BACKED_OUT = "change.backed_out"
CLOSED = "change.closed"
STATUS_ENTERED = "change.status_entered"
SENT_BACK = "change.sent_back"
OVERRIDDEN = "change.overridden"
BOARD_EMPTY = "change.board_empty"
REMINDER_WINDOW = "change.window_reminder"
REMINDER_OVERDUE = "change.implementation_overdue"
REMINDER_CAB = "change.cab_reminder"
REMINDER_REVIEW = "change.review_due"
MENTION = "change.mentioned"
NOTE = "change.note"

_TO_STATUS: Mapping[str, str] = {
    "submission_submitted": SUBMITTED,
    "submission_accepted": APPROVED,
    "planning_plan_approved": APPROVED,
    "cab_approved": APPROVED,
    "submission_rejected": REJECTED,
    "planning_plan_rejected": REJECTED,
    "cab_rejected": REJECTED,
    "submission_more_info": CLARIFICATION,
    "cab_clarification": CLARIFICATION,
    IMPLEMENTED: IMPLEMENTED_EVENT,
    "implementation_failed": FAILED,
    "implementation_backed_out": BACKED_OUT,
    "closure_closed": CLOSED,
}
_TO_STATUS_SUBMITTED = frozenset({"submission_submitted"})  # a change may start submitted
_NOTICES: Mapping[str, str] = {
    "sent_back": SENT_BACK,
    "overridden": OVERRIDDEN,
    "board_has_no_members": BOARD_EMPTY,
}
_REMINDERS: Mapping[str, str] = {
    WINDOW_START: REMINDER_WINDOW,
    OVERDUE: REMINDER_OVERDUE,
    CAB_WAITING: REMINDER_CAB,
    REVIEW_DUE: REMINDER_REVIEW,
}
# The requester's own news: rendered from the public side only (the status, never the why).
PUBLIC_EVENTS = frozenset(
    {APPROVED, REJECTED, CLARIFICATION, IMPLEMENTED_EVENT, FAILED, BACKED_OUT, CLOSED}
)
APPROVAL_EVENTS = frozenset({APPROVAL_REQUESTED, APPROVAL_FALLBACK, REMINDER_CAB})

_CONVERSATION = (
    Variable("conversation.author", "notification_variable.conversation.author"),
    Variable("conversation.excerpt", "notification_variable.conversation.excerpt"),
)
_APPROVAL = (Variable("approval_link", "notification_variable.approval_link"),)
_WINDOW = (Variable("window.start", "notification_variable.window.start"),)


def _event(  # noqa: PLR0913 - one event's facts, explicit
    code: str,
    category: NotificationCategory,
    recipients: tuple[str, ...],
    *,
    enabled: bool = True,
    required: bool = False,
    public: bool = False,
    variables: tuple[Variable, ...] = (),
) -> NotificationEvent:
    return NotificationEvent(
        code,
        category,
        EventDefault(enabled=enabled, recipients=recipients),
        required=required,
        public=public,
        variables=variables,
    )


_C = NotificationCategory
EVENTS: tuple[NotificationEvent, ...] = (
    _event(SUBMITTED, _C.CREATED, (MANAGER,)),
    _event(
        APPROVAL_REQUESTED,
        _C.APPROVAL,
        (APPROVER,),
        required=True,
        public=True,
        variables=_APPROVAL,
    ),
    _event(APPROVAL_FALLBACK, _C.APPROVAL, (ADMINISTRATORS,), public=True),
    _event(APPROVED, _C.STATUS, (REQUESTER, OWNER), public=True),
    _event(REJECTED, _C.STATUS, (REQUESTER, OWNER), public=True),
    _event(CLARIFICATION, _C.STATUS, (OWNER, REQUESTER), public=True),
    _event(ASSIGNED, _C.ASSIGNMENT, (OWNER,), required=True),
    _event(IMPLEMENTED_EVENT, _C.STATUS, (REQUESTER, MANAGER, REVIEWER), public=True),
    _event(FAILED, _C.STATUS, (REQUESTER, MANAGER, REVIEWER), public=True),
    _event(BACKED_OUT, _C.STATUS, (REQUESTER, MANAGER, REVIEWER), public=True),
    _event(CLOSED, _C.STATUS, (REQUESTER,), public=True),
    # REQ-CHG-103: one rule per status (its `status` condition), off until an admin turns it on.
    _event(STATUS_ENTERED, _C.STATUS, (OWNER,), enabled=False),
    _event(SENT_BACK, _C.APPROVAL, (IMPLEMENTER, OWNER, CAB)),
    _event(OVERRIDDEN, _C.APPROVAL, (MANAGER,)),
    _event(BOARD_EMPTY, _C.APPROVAL, (MANAGER,)),
    _event(REMINDER_WINDOW, _C.STATUS, (IMPLEMENTER, OWNER), variables=_WINDOW),
    _event(REMINDER_OVERDUE, _C.STATUS, (OWNER, MANAGER), variables=_WINDOW),
    _event(REMINDER_CAB, _C.APPROVAL, (MEMBER,), public=True, variables=(*_APPROVAL, *_WINDOW)),
    _event(REMINDER_REVIEW, _C.STATUS, (OWNER, REVIEWER)),
    _event(MENTION, _C.MENTION, (MENTIONED,), required=True, variables=_CONVERSATION),
    _event(NOTE, _C.CONVERSATION, (OWNER,), enabled=False, variables=_CONVERSATION),
)

VARIABLES = (
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.status", "notification_variable.record.status"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("requester.name", "notification_variable.requester.name"),
    Variable("assignee.name", "notification_variable.assignee.name"),
    Variable("actor.name", "notification_variable.actor.name"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)

_REPLIES = StaffReplyNotifications(CHANGE)


def _actor(envelope: EventEnvelope) -> uuid.UUID | None:
    if envelope.actor.type != "user":
        return None
    try:
        return uuid.UUID(envelope.actor.id)
    except ValueError:
        return None


def _excerpt(body: str) -> str:
    text = html.unescape(nh3.clean(body.replace("</p>", "</p>\n"), tags=set())).strip()
    return text if len(text) <= EXCERPT else text[: EXCERPT - 1].rstrip() + "…"


def _opened(envelope: EventEnvelope) -> bool:
    payload = envelope.payload
    return (
        payload.get("type") == CHANGE.code.value
        and payload.get("change") == "opened"
        and payload.get("state") == rules.ApprovalState.PENDING.value
    )


async def _held(session: AsyncSession, record_id: uuid.UUID, role: str) -> frozenset[uuid.UUID]:
    """The people holding `role` on the change now: named, and members of holding groups."""
    rows = (
        await session.execute(
            select(WorkItemRoleHolder.user_id, WorkItemRoleHolder.group_id).where(
                WorkItemRoleHolder.work_item_id == record_id, WorkItemRoleHolder.role == role
            )
        )
    ).all()
    people = {r.user_id for r in rows if r.user_id is not None}
    groups = frozenset(r.group_id for r in rows if r.group_id is not None)
    if groups:
        people |= set(await session.scalars(users_in_groups(groups).limit(HOLDER_LIMIT)))
    return frozenset(sorted(people, key=str)[:HOLDER_LIMIT])


async def _cab(session: AsyncSession, record_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """The CAB members on the change's board approvals (its current round of them)."""
    rows = await session.scalars(
        select(WorkItemApproval.approver_id)
        .where(
            WorkItemApproval.work_item_id == record_id,
            WorkItemApproval.deleted_at.is_(None),
            WorkItemApproval.record_stage == CAB_STAGE,
            WorkItemApproval.board_id.is_not(None),
            WorkItemApproval.approver_id.is_not(None),
        )
        .limit(HOLDER_LIMIT)
    )
    return frozenset(r for r in rows if r is not None)


async def _relatives(
    session: AsyncSession, record: WorkItem, event_code: str, envelope: EventEnvelope
) -> dict[str, frozenset[uuid.UUID]] | None:
    """Who is who for this event, now; None when the event no longer stands."""
    payload = envelope.payload
    relatives: dict[str, frozenset[uuid.UUID]] = {
        REQUESTER: frozenset(
            p for p in (record.requester_id, record.on_behalf_of_id) if p is not None
        ),
        OWNER: frozenset({record.technician_id} if record.technician_id else ()),
    }
    for role in _HELD_ROLES:
        relatives[role] = await _held(session, record.id, role)
    if event_code in {SENT_BACK, STATUS_ENTERED}:
        relatives[CAB] = await _cab(session, record.id)
    if event_code == APPROVAL_REQUESTED:
        row = await session.get(WorkItemApproval, uuid.UUID(str(payload["approval_id"])))
        if row is None or row.state != rules.ApprovalState.PENDING or row.approver_id is None:
            return None  # decided or withdrawn before it went: nothing to ask
        relatives[APPROVER] = frozenset({row.approver_id})
    if event_code == APPROVAL_FALLBACK:
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        held = await worker_policy().holders(session, tenant, APPROVE_ANY, limit=HOLDER_LIMIT)
        relatives[ADMINISTRATORS] = frozenset(user for user, _name in held)
    if event_code == REMINDER_CAB:
        member = uuid.UUID(str(payload["member_id"]))
        if await _live_approval(session, record.id, member, CAB_STAGE) is None:
            return None  # they decided meanwhile
        relatives[MEMBER] = frozenset({member})
    if event_code == MENTION:
        relatives[MENTIONED] = frozenset(uuid.UUID(str(u)) for u in payload["mentioned_ids"])
    return relatives


async def _live_approval(
    session: AsyncSession, record_id: uuid.UUID, user_id: uuid.UUID, stage: str | None = None
) -> WorkItemApproval | None:
    """The person's pending approval on the change (or the administrators' one), if any."""
    query = select(WorkItemApproval).where(
        WorkItemApproval.work_item_id == record_id,
        WorkItemApproval.deleted_at.is_(None),
        WorkItemApproval.state == rules.ApprovalState.PENDING.value,
        WorkItemApproval.approver_id == user_id,
    )
    if stage is not None:
        query = query.where(WorkItemApproval.record_stage == stage)
    return await session.scalar(query.limit(1))


async def _reminder_stands(
    session: AsyncSession, record: WorkItem, payload: Mapping[str, object]
) -> bool:
    """A reminder still fits the change as it is now (lane B: never for a moved window)."""
    if StatusCategory(record.status_category) not in {StatusCategory.OPEN, StatusCategory.PAUSED}:
        return False
    kind = str(payload["kind"])
    if kind == REVIEW_DUE:
        return record.stage == REVIEW
    window = await session.scalar(
        select(WorkItemStageSchedule).where(
            WorkItemStageSchedule.work_item_id == record.id,
            WorkItemStageSchedule.stage == IMPLEMENTATION,
        )
    )
    if window is None or window.scheduled_start is None:
        return False
    claimed = payload.get("window_start")
    if claimed is None or window.scheduled_start != datetime.fromisoformat(str(claimed)):
        return False
    if kind == OVERDUE:
        return record.stage == IMPLEMENTATION and record.status != IMPLEMENTED
    return True


def _typed_events(envelope: EventEnvelope) -> tuple[str, ...]:
    """The events of a change's own record events (created, assigned, a status move)."""
    payload = envelope.payload
    kind = envelope.event_type
    if payload.get("type") != CHANGE.code.value:
        return ()
    if kind == WorkItemCreated.event_type:
        submitted = (SUBMITTED,) if payload.get("status") in _TO_STATUS_SUBMITTED else ()
        return (*submitted, *((ASSIGNED,) if payload.get("technician_id") else ()))
    if kind == WorkItemAssigned.event_type:
        return (ASSIGNED,) if payload.get("technician_id") else ()
    if kind == WorkItemStatusChanged.event_type:
        found = _TO_STATUS.get(str(payload.get("to_status")))
        return (STATUS_ENTERED, *((found,) if found else ()))
    return ()


class ChangeNotifications:
    """`RecordSource` for changes."""

    record_type = CHANGE.code.value
    channel_kind = RECORD_KIND
    events = (*EVENTS, *_REPLIES.events)
    recipient_kinds = RECIPIENT_KINDS
    variables = VARIABLES
    conditions = ("status", "status_category")
    event_types = (
        WorkItemCreated.event_type,
        WorkItemAssigned.event_type,
        WorkItemStatusChanged.event_type,
        WorkItemApprovalChanged.event_type,
        WorkItemConversationAdded.event_type,
        ChangeApprovalNotice.event_type,
        ChangeReminderDue.event_type,
    )

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:  # noqa: PLR0911 - one return per event family, flat
        """Notification events of one committed event (changes only)."""
        payload = envelope.payload
        kind = envelope.event_type
        if kind == ChangeReminderDue.event_type:
            found = _REMINDERS.get(str(payload.get("kind")))
            return (found,) if found else ()
        if kind == ChangeApprovalNotice.event_type:
            notice = _NOTICES.get(str(payload.get("notice")))
            return (notice,) if notice else ()
        if kind == WorkItemApprovalChanged.event_type:
            if not _opened(envelope):
                return ()
            return (APPROVAL_REQUESTED,) if payload.get("approver_id") else (APPROVAL_FALLBACK,)
        if kind == WorkItemConversationAdded.event_type:
            # No type on the event: `context` answers only for a change.
            if payload.get("kind") == EntryKind.REPLY:
                return _REPLIES.events_for(envelope)
            if payload.get("automatic"):
                return ()
            return (MENTION,) if payload.get("mentioned_ids") else (NOTE,)
        return _typed_events(envelope)

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The change as it is now, with the people relative to it for this event."""
        if event_code in {e.code for e in _REPLIES.events}:
            return await _REPLIES.context(session, event_code, envelope)
        payload = envelope.payload
        record_id = uuid.UUID(str(payload.get("work_item_id") or payload["record_id"]))
        record = await session.scalar(
            select(WorkItem).where(WorkItem.id == record_id, WorkItem.deleted_at.is_(None))
        )
        if record is None or record.type != CHANGE.code.value:
            return None
        if envelope.event_type == ChangeReminderDue.event_type and not await _reminder_stands(
            session, record, payload
        ):
            return None
        relatives = await _relatives(session, record, event_code, envelope)
        if relatives is None:
            return None
        actor = _actor(envelope)
        people = [p for p in (record.technician_id, record.requester_id, actor) if p is not None]
        names = await user_names(session, [str(p) for p in people])
        link = f"/changes/{record.id}"
        # The public side: what the requester's (and an approver's) own view shows, no more.
        public: dict[str, VariableValue] = {
            "record.display_id": record.display_id,
            "record.title": record.subject,
            "record.status": LabelRef(f"work_item_status.{record.status}"),
            "requester.name": names.get(str(record.requester_id)),
        }
        full: dict[str, VariableValue] = {
            **public,
            "record.link": link,
            "assignee.name": names.get(str(record.technician_id)) if record.technician_id else None,
            "actor.name": names.get(str(actor)) if actor else None,
        }
        if envelope.event_type == ChangeReminderDue.event_type and payload.get("window_start"):
            starts = datetime.fromisoformat(str(payload["window_start"]))
            full["window.start"] = starts
            public["window.start"] = starts
        if envelope.event_type == WorkItemConversationAdded.event_type:
            entry = await session.scalar(
                select(WorkItemConversation).where(
                    WorkItemConversation.id == uuid.UUID(str(payload["entry_id"])),
                    WorkItemConversation.deleted_at.is_(None),
                )
            )
            if entry is None:
                return None
            full["conversation.author"] = full["actor.name"]
            full["conversation.excerpt"] = _excerpt(entry.body)
        return RecordContext(
            record_id=record.id,
            display_id=record.display_id,
            link=link,
            # No portal page for a change yet (WP-045d S4): a public reader gets the portal's
            # home, never the console address they cannot open.
            public_link=None,
            variables=full,
            public_variables=public,
            relatives=relatives,
            conditions={"status": record.status, "status_category": record.status_category},
            urgent=event_code in APPROVAL_EVENTS,  # each approval e-mail keeps its own link
            event_code=event_code,
            entry_id=uuid.UUID(str(payload["entry_id"])) if "entry_id" in payload else None,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for staff who see the change; PUBLIC for its requester and live approvers."""
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        try:
            await items.visible_record(session, subject, CHANGE, record_id)
        except (NotFound, PermissionDenied):
            record = await session.get(WorkItem, record_id)
            if record is None or record.deleted_at is not None:
                return RecordAccess.NONE
            if user_id in {record.requester_id, record.on_behalf_of_id}:
                return RecordAccess.PUBLIC
            # Lane B: only an approval live at send time, never one decided or withdrawn.
            if await _live_approval(session, record_id, user_id) is not None:
                return RecordAccess.PUBLIC
            return RecordAccess.NONE
        return RecordAccess.FULL if sees_private(subject, CHANGE) else RecordAccess.PUBLIC

    async def delivery_changed(  # noqa: PLR0913 - the port's fields, explicit
        self,
        session: AsyncSession,
        *,
        record_id: uuid.UUID,
        entry_id: uuid.UUID,
        state: str,
        reason: str | None,
        at: datetime,
    ) -> None:
        """A reply follows its e-mail, as the staff-reply source settles it (#359)."""
        await _REPLIES.delivery_changed(
            session, record_id=record_id, entry_id=entry_id, state=state, reason=reason, at=at
        )

    async def recipient_links(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        recipient_id: uuid.UUID,
        channel: NotificationChannel,
    ) -> Mapping[str, LinkRequest]:
        """The approver's own one-time link, made by the mail sender at send (D-132)."""
        if channel is not NotificationChannel.EMAIL:
            return {}
        payload = envelope.payload
        if envelope.event_type == WorkItemApprovalChanged.event_type and _opened(envelope):
            row = await session.get(WorkItemApproval, uuid.UUID(str(payload["approval_id"])))
        elif envelope.event_type == ChangeReminderDue.event_type and payload.get("member_id"):
            row = await _live_approval(
                session, uuid.UUID(str(payload["work_item_id"])), recipient_id, CAB_STAGE
            )
        else:
            return {}
        if row is None or row.approver_id != recipient_id:
            return {}  # only the approval's own approver, never anyone else on the message
        return {
            "approval_link": LinkRequest(
                recipient_id=recipient_id,
                action=approvals.LINK_ACTION,
                object_type=approvals.LINK_OBJECT,
                object_id=row.id,
                object_version=row.version,
            )
        }


SOURCE = ChangeNotifications()


def register() -> None:
    """Make changes notify (idempotent; called when work_items is imported, after replies)."""
    register_record_source(SOURCE)
