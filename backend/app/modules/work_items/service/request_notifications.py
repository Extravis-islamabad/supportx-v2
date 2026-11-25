"""Service request notifications: approvals waiting for someone (WP-030 s3; REQ-SR-025, -026).

Registered through `app.shared.notifications.ports` like incidents (service/notifications.py),
under lane B's review (2026-11-04):

- `service_request.approval_requested`: to the approval's own approver, in-app and by e-mail;
  urgent (never held for a digest) and required. The e-mail carries that approver's own
  one-time link: `recipient_links` names it and the mail sender makes the token at send
  (D-132), so no token sits in the outbox, a stored body or a log; the in-app entry has the
  record link only.
- `service_request.approval_fallback`: an approval held by the approval administrators
  (REQ-SR-023), to everyone with `work_items.approve_any`, in-app only and with no link, as no
  single person holds it.

The requester's own (QA10): received, approved, rejected (with the approver's comment unless it
is private), withdrawn and fulfilled, to the requester and the person it is for, in-app and by
e-mail through the one mail sender. Received and withdrawn reach the requester even when they did
it themself: it is their acknowledgement.
"""

import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound
from app.core.tenancy import ANY_SOURCE
from app.modules.identity_access import person_placement, subject_for, user_names, worker_policy
from app.modules.organization import users_in_groups
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.conversation import EntryKind
from app.modules.work_items.domain.lifecycle import StatusCategory, WorkItemAction
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.events import (
    ServiceRequestReadyToFulfil,
    WorkItemApprovalChanged,
    WorkItemApprovalClarification,
    WorkItemApprovalRestarted,
    WorkItemConversationAdded,
    WorkItemCreated,
    WorkItemStatusChanged,
)
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval, WorkItemConversation
from app.modules.work_items.service import approvals
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import APPROVE_ANY
from app.modules.work_items.service.file_access import sees_private
from app.modules.work_items.service.notifications import move_reply_delivery, reply_excerpt
from app.modules.work_items.service.realtime import RECORD_KIND
from app.shared import action_links
from app.shared.action_links import LinkRequest
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    NotificationCategory,
    NotificationChannel,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

REQUESTED = "service_request.approval_requested"
FALLBACK = "service_request.approval_fallback"
RECEIVED = "service_request.received"
APPROVED = "service_request.approved"
REJECTED = "service_request.rejected"
WITHDRAWN = "service_request.withdrawn"
FULFILLED = "service_request.fulfilled"
REPLY = "service_request.public_reply"  # a reply to the requester, by e-mail (lane B's #359)
READY = "service_request.ready_to_fulfil"  # D-154 "E1 follows d": to its group, in the app
# WP-047a S3a (REQ-SR-037 AC2): the approver who asked is told their question was answered;
# the notice names the request, never the answer (the coordinator's condition 4).
ANSWERED = "service_request.clarification_answered"
# WP-047a S3b (REQ-SR-041; the coordinator's condition 3): the approvers of a round that ended
# with a restart are told it no longer needs them (their links were revoked).
RESTARTED = "service_request.approval_restarted"
# WP-047a S4 (REQ-SR-017 AC2): made from mail with required answers missing. One who may sign in
# gets the portal page that asks only the missing questions; one who may not (a requester made
# from mail, lane B) gets no link and is told their service desk gives portal access.
# WP-047a S4 (REQ-SR-038; lane B's #627 condition 2): a reply to the approval mail decided, so
# its approver hears of it at the address on file; a forged reply would then be noticed.
DECIDED_BY_MAIL = "service_request.approval_decided_by_mail"
ANSWERS_NEEDED = "service_request.answers_needed"
ANSWERS_NO_ACCESS = "service_request.answers_needed_no_access"
GROUP = "group"  # the request's group
REQUESTER = "requester"  # the requester and the person it is for
APPROVER = "approver"
ADMINISTRATORS = "approval_administrators"
LINK_PATH = "requests/approval-link#"
ADMIN_LIMIT = 200  # approval administrators told of one fallback approval

EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent(
        REQUESTED,
        NotificationCategory.APPROVAL,
        EventDefault(enabled=True, recipients=(APPROVER,)),
        required=True,
        variables=(Variable("approval_link", "notification_variable.approval_link"),),
    ),
    NotificationEvent(
        FALLBACK,
        NotificationCategory.APPROVAL,
        EventDefault(
            enabled=True, recipients=(ADMINISTRATORS,), channels=(NotificationChannel.IN_APP,)
        ),
        required=True,
    ),
    NotificationEvent(
        RECEIVED,
        NotificationCategory.CREATED,
        EventDefault(enabled=True, recipients=(REQUESTER,), notify_actor=True),
    ),
    # Required: without it the request waits on answers nobody asked for.
    NotificationEvent(
        DECIDED_BY_MAIL,
        NotificationCategory.APPROVAL,
        EventDefault(enabled=True, recipients=(APPROVER,), notify_actor=True),
        required=True,  # the only sign a forged reply was applied in their name
    ),
    NotificationEvent(
        ANSWERS_NEEDED,
        NotificationCategory.CREATED,
        EventDefault(enabled=True, recipients=(REQUESTER,), notify_actor=True),
        required=True,
    ),
    NotificationEvent(
        ANSWERS_NO_ACCESS,
        NotificationCategory.CREATED,
        EventDefault(enabled=True, recipients=(REQUESTER,), notify_actor=True),
        required=True,
    ),
    NotificationEvent(
        APPROVED, NotificationCategory.STATUS, EventDefault(enabled=True, recipients=(REQUESTER,))
    ),
    NotificationEvent(
        REJECTED,
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=(REQUESTER,)),
        variables=(Variable("approval.comment", "notification_variable.approval.comment"),),
    ),
    NotificationEvent(
        WITHDRAWN,
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=(REQUESTER,), notify_actor=True),
    ),
    NotificationEvent(
        FULFILLED, NotificationCategory.STATUS, EventDefault(enabled=True, recipients=(REQUESTER,))
    ),
    # A technician's reply reaches the requester, as on incidents; its e-mail carries the reply,
    # so the reply's delivery state follows it (it never stays queued).
    NotificationEvent(
        REPLY,
        NotificationCategory.CONVERSATION,
        EventDefault(enabled=True, recipients=(REQUESTER,)),
        variables=(
            Variable("conversation.author", "notification_variable.conversation.author"),
            Variable("conversation.excerpt", "notification_variable.conversation.excerpt"),
        ),
    ),
    NotificationEvent(
        RESTARTED,
        NotificationCategory.APPROVAL,
        EventDefault(enabled=True, recipients=(APPROVER,)),
        required=True,  # condition 3: the old approvers are always told
    ),
    NotificationEvent(
        ANSWERED,
        NotificationCategory.APPROVAL,
        EventDefault(enabled=True, recipients=(APPROVER,)),
    ),
    NotificationEvent(
        READY,
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=(GROUP,), channels=(NotificationChannel.IN_APP,)),
    ),
)
VARIABLES = (
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("requester.name", "notification_variable.requester.name"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


def _opened(envelope: EventEnvelope) -> bool:
    payload = envelope.payload
    return (
        payload.get("type") == SERVICE_REQUEST.code.value
        and payload.get("change") == "opened"
        and payload.get("state") == rules.ApprovalState.PENDING.value
    )


class ServiceRequestNotifications:
    """`RecordSource` for service requests (approvals only, for now)."""

    record_type = "service_request"
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = (APPROVER, ADMINISTRATORS, REQUESTER, GROUP)
    variables = VARIABLES
    conditions = ("priority",)
    event_types = (
        WorkItemApprovalChanged.event_type,
        WorkItemCreated.event_type,
        WorkItemStatusChanged.event_type,
        ServiceRequestReadyToFulfil.event_type,
        WorkItemConversationAdded.event_type,
        WorkItemApprovalClarification.event_type,
        WorkItemApprovalRestarted.event_type,
    )

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:  # noqa: PLR0911 - one return per event family, flat
        """An approval opened (its approver or the administrators), or the requester's news."""
        payload = envelope.payload
        if envelope.event_type == WorkItemConversationAdded.event_type:
            # No type on the event: `context` answers only for a request's outbound reply.
            automatic = payload.get("automatic")
            return () if automatic or payload.get("kind") != EntryKind.REPLY else (REPLY,)
        if envelope.event_type == WorkItemApprovalRestarted.event_type:
            return (RESTARTED,) if payload.get("approver_ids") else ()
        if envelope.event_type == WorkItemApprovalClarification.event_type:
            return (ANSWERED,) if payload.get("change") == "answered" else ()
        if envelope.event_type == WorkItemApprovalChanged.event_type:
            if (
                payload.get("change") == "decided"
                and payload.get("type") == SERVICE_REQUEST.code.value
            ):
                return (DECIDED_BY_MAIL,)  # `context` keeps it to a decision made by reply
            if not _opened(envelope):
                return ()
            return (REQUESTED,) if payload.get("approver_id") else (FALLBACK,)
        if payload.get("type") != SERVICE_REQUEST.code.value:
            return ()
        if envelope.event_type == ServiceRequestReadyToFulfil.event_type:
            return (READY,)
        if envelope.event_type == WorkItemCreated.event_type:
            # One of the three answers (`context`): received, or which answers-needed notice.
            return (RECEIVED, ANSWERS_NEEDED, ANSWERS_NO_ACCESS)
        return _status_event(payload)

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The request now, and who is told now (a decided approval tells nobody)."""
        if event_code in REQUESTER_EVENTS:
            pick = _created_context if event_code in CREATED_EVENTS else _requester_context
            return await pick(session, event_code, envelope)
        special = {
            DECIDED_BY_MAIL: _decided_by_mail_context,  # WP-047a S4
            READY: _ready_context,
            REPLY: _reply_context,
            ANSWERED: _answered_context,  # WP-047a S3a
            RESTARTED: _restarted_context,  # WP-047a S3b
        }.get(event_code)
        if special is not None:
            return await special(session, envelope)
        payload = envelope.payload
        row = await session.get(WorkItemApproval, uuid.UUID(str(payload["approval_id"])))
        record = await session.get(WorkItem, uuid.UUID(str(payload["work_item_id"])))
        if (
            row is None
            or record is None
            or record.deleted_at is not None
            or row.state != rules.ApprovalState.PENDING
        ):
            return None
        if row.approver_id is not None:
            relatives = {APPROVER: frozenset({row.approver_id})}
        else:
            tenant = session.info[SESSION_TENANT_KEY].tenant_id
            held = await worker_policy().holders(session, tenant, APPROVE_ANY, limit=ADMIN_LIMIT)
            relatives = {ADMINISTRATORS: frozenset(user for user, _name in held)}
        names = await user_names(session, [str(record.requester_id)])
        variables: dict[str, VariableValue] = {
            "record.display_id": record.display_id,
            "record.title": record.subject,
            "record.link": f"/requests/{record.id}",
            "requester.name": names.get(str(record.requester_id)),
        }
        return RecordContext(
            record_id=record.id,
            display_id=record.display_id,
            link=f"/requests/{record.id}",
            # An approver without console access opens it in the portal, read-only (QA10-P2-06).
            public_link=f"/service-requests/{record.id}",
            variables=variables,
            public_variables=variables,
            relatives=relatives,
            conditions={"priority": record.priority},
            urgent=True,  # lane B: never held for a digest, so each e-mail has its own link
            event_code=event_code,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """Staff who see the request in full; its approvers and requesters its summary."""
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id, source=ANY_SOURCE)
        try:
            await items.visible_record(session, subject, SERVICE_REQUEST, record_id)
        except NotFound:
            record = await session.get(WorkItem, record_id)
            if record is not None and user_id in {record.requester_id, record.on_behalf_of_id}:
                return RecordAccess.PUBLIC  # the requester's side: what they see in the portal
            holds = await session.scalar(
                select(WorkItemApproval.id)
                .where(
                    WorkItemApproval.work_item_id == record_id,
                    WorkItemApproval.deleted_at.is_(None),
                    (WorkItemApproval.approver_id == user_id)
                    | WorkItemApproval.approver_id.is_(None),
                )
                .limit(1)
            )
            return RecordAccess.PUBLIC if holds is not None else RecordAccess.NONE
        return RecordAccess.FULL if sees_private(subject, SERVICE_REQUEST) else RecordAccess.PUBLIC

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
        """A request's reply follows its e-mail, as an incident's does (lane B's #359)."""
        await move_reply_delivery(
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
        if channel is not NotificationChannel.EMAIL or not _opened(envelope):
            return {}
        row = await session.get(WorkItemApproval, uuid.UUID(str(envelope.payload["approval_id"])))
        if row is None or row.approver_id != recipient_id:
            return {}  # only the approval's own approver, never anyone else on the message
        # WP-047a S3a (lane C's #604 review): a reminder mails the approval again, so the links
        # earlier mails carried are revoked here, before this mail's own is minted at its send.
        # The approver holds one live no-sign-in link per approval, never one per reminder.
        await action_links.revoke_for(session, approvals.LINK_OBJECT, row.id)
        return {
            "approval_link": LinkRequest(
                recipient_id=recipient_id,
                action=approvals.LINK_ACTION,
                object_type=approvals.LINK_OBJECT,
                object_id=row.id,
                object_version=row.version,
            )
        }


# What a new request tells its requester: one of these three (`_created_context`).
CREATED_EVENTS = frozenset({RECEIVED, ANSWERS_NEEDED, ANSWERS_NO_ACCESS})
REQUESTER_EVENTS = CREATED_EVENTS | {APPROVED, REJECTED, WITHDRAWN, FULFILLED}


async def _restarted_context(
    session: AsyncSession, envelope: EventEnvelope
) -> RecordContext | None:
    """The approvers of the round that ended, told the request's approval started again."""
    payload = envelope.payload
    record = await session.get(WorkItem, uuid.UUID(str(payload["work_item_id"])))
    if record is None or record.deleted_at is not None:
        return None
    told = frozenset(uuid.UUID(str(p)) for p in payload.get("approver_ids") or [])
    if not told:
        return None
    variables: dict[str, VariableValue] = {
        "record.display_id": record.display_id,
        "record.title": record.subject,
        "record.link": f"/requests/{record.id}",
    }
    return RecordContext(
        record_id=record.id,
        display_id=record.display_id,
        link=f"/requests/{record.id}",
        public_link=f"/service-requests/{record.id}",
        variables=variables,
        public_variables=variables,
        relatives={APPROVER: told},
        conditions={"priority": record.priority},
        event_code=RESTARTED,
    )


async def _answered_context(session: AsyncSession, envelope: EventEnvelope) -> RecordContext | None:
    """The approver who asked, while their approval still waits (decided: nobody is told)."""
    payload = envelope.payload
    row = await session.get(WorkItemApproval, uuid.UUID(str(payload["approval_id"])))
    record = await session.get(WorkItem, uuid.UUID(str(payload["work_item_id"])))
    if (
        row is None
        or record is None
        or record.deleted_at is not None
        or row.state != rules.ApprovalState.PENDING
    ):
        return None
    variables: dict[str, VariableValue] = {
        "record.display_id": record.display_id,
        "record.title": record.subject,
        "record.link": f"/requests/{record.id}",
    }
    return RecordContext(
        record_id=record.id,
        display_id=record.display_id,
        link=f"/requests/{record.id}",
        public_link=f"/service-requests/{record.id}",
        variables=variables,
        public_variables=variables,
        relatives={APPROVER: frozenset({uuid.UUID(str(payload["approver_id"]))})},
        conditions={"priority": record.priority},
        event_code=ANSWERED,
    )


async def _ready_context(session: AsyncSession, envelope: EventEnvelope) -> RecordContext | None:
    """Its group, while the request is still open with nobody on it (D-154, "E1 follows d")."""
    record = await session.get(WorkItem, uuid.UUID(str(envelope.payload["work_item_id"])))
    if (
        record is None
        or record.deleted_at is not None
        or record.technician_id is not None  # someone took it meanwhile: no news
        or record.group_id is None
        or StatusCategory(record.status_category) is not StatusCategory.OPEN
    ):
        return None
    members = frozenset(await session.scalars(users_in_groups(frozenset({record.group_id}))))
    names = await user_names(session, [str(record.requester_id)])
    variables: dict[str, VariableValue] = {
        "record.display_id": record.display_id,
        "record.title": record.subject,
        "record.link": f"/requests/{record.id}",
        "requester.name": names.get(str(record.requester_id)),
    }
    return RecordContext(
        record_id=record.id,
        display_id=record.display_id,
        link=f"/requests/{record.id}",
        variables=variables,
        public_variables=variables,
        relatives={GROUP: members},
        conditions={"priority": record.priority},
        event_code=READY,
    )


def _status_event(payload: Mapping[str, object]) -> tuple[str, ...]:
    """A status move's news for the requester: approved, rejected, withdrawn, fulfilled."""
    action = payload.get("action")
    if action == WorkItemAction.APPROVE.value:
        return (APPROVED,)
    if action == WorkItemAction.REJECT.value:
        return (REJECTED,)
    if action == WorkItemAction.CANCEL.value:
        return (WITHDRAWN,)  # only when the requester withdrew: checked on the record
    if payload.get("status_category") == StatusCategory.RESOLVED.value:
        return (FULFILLED,)
    return ()


async def _created_context(
    session: AsyncSession, event_code: str, envelope: EventEnvelope
) -> RecordContext | None:
    """The acknowledgement, or (made from mail with answers missing) how to give them.

    Exactly one of the three answers for a new request (WP-047a S4, REQ-SR-017 AC2): received
    when nothing is missing; else answers-needed with the portal page when the requester may
    sign in, or with no link when they may not (`person_placement`, which fails closed).
    """
    record = await session.get(WorkItem, uuid.UUID(str(envelope.payload["work_item_id"])))
    if record is None or record.deleted_at is not None:
        return None
    waiting = record.approval_status == ApprovalStatus.AWAITING_ANSWERS.value
    if not waiting:
        chosen = RECEIVED
    elif (await person_placement(session, record.requester_id)).can_sign_in:
        chosen = ANSWERS_NEEDED
    else:
        chosen = ANSWERS_NO_ACCESS
    if chosen != event_code:
        return None
    found = await _requester_context(session, event_code, envelope)
    if found is None or chosen != ANSWERS_NEEDED:
        return found
    page = f"/service-requests/{record.id}/complete"  # asks only the missing questions
    variables = {**found.variables, "record.link": page}
    return replace(found, public_link=page, variables=variables, public_variables=variables)


async def _requester_context(
    session: AsyncSession, event_code: str, envelope: EventEnvelope
) -> RecordContext | None:
    record = await session.get(WorkItem, uuid.UUID(str(envelope.payload["work_item_id"])))
    if record is None or record.deleted_at is not None:
        return None
    if event_code == WITHDRAWN and record.approval_status != ApprovalStatus.WITHDRAWN.value:
        return None  # canceled by the desk: not a withdrawal (the incident-style news covers it)
    names = await user_names(session, [str(record.requester_id)])
    variables: dict[str, VariableValue] = {
        "record.display_id": record.display_id,
        "record.title": record.subject,
        "record.link": f"/requests/{record.id}",
        "requester.name": names.get(str(record.requester_id)),
    }
    if event_code == REJECTED:
        variables["approval.comment"] = await _public_comment(session, record.id)
    people = frozenset(p for p in (record.requester_id, record.on_behalf_of_id) if p is not None)
    return RecordContext(
        record_id=record.id,
        display_id=record.display_id,
        link=f"/requests/{record.id}",
        public_link=f"/service-requests/{record.id}",
        variables=variables,
        public_variables=variables,
        relatives={REQUESTER: people},
        conditions={"priority": record.priority},
        event_code=event_code,
    )


async def _decided_by_mail_context(
    session: AsyncSession, envelope: EventEnvelope
) -> RecordContext | None:
    """The approver, when their approval was decided by a reply to its mail (lane B's #627)."""
    row = await session.get(WorkItemApproval, uuid.UUID(str(envelope.payload["approval_id"])))
    if row is None or row.channel != rules.DecisionChannel.EMAIL_REPLY or row.approver_id is None:
        return None
    record = await session.get(WorkItem, row.work_item_id)
    if record is None or record.deleted_at is not None:
        return None
    variables: dict[str, VariableValue] = {
        "record.display_id": record.display_id,
        "record.title": record.subject,
        "record.link": f"/requests/{record.id}",
    }
    return RecordContext(
        record_id=record.id,
        display_id=record.display_id,
        link=f"/requests/{record.id}",
        variables=variables,
        public_variables=variables,
        relatives={APPROVER: frozenset({row.approver_id})},
        conditions={"priority": record.priority},
        event_code=DECIDED_BY_MAIL,
    )


async def _reply_context(session: AsyncSession, envelope: EventEnvelope) -> RecordContext | None:
    """A reply on a request, for its requester (and the person it is for).

    Not a request (incidents have their own source), not a reply, or the requester's own:
    nothing to send.
    """
    payload = envelope.payload
    record = await session.get(WorkItem, uuid.UUID(str(payload["work_item_id"])))
    if record is None or record.deleted_at is not None or record.type != SERVICE_REQUEST.code.value:
        return None
    entry = await session.get(WorkItemConversation, uuid.UUID(str(payload["entry_id"])))
    if entry is None or entry.deleted_at is not None or entry.kind != EntryKind.REPLY:
        return None
    people = frozenset(p for p in (record.requester_id, record.on_behalf_of_id) if p is not None)
    if entry.created_by in people:
        return None  # the requester's own reply tells the desk, not themselves
    author = str(entry.created_by) if entry.created_by else None
    names = await user_names(session, [str(record.requester_id), *([author] if author else [])])
    variables: dict[str, VariableValue] = {
        "record.display_id": record.display_id,
        "record.title": record.subject,
        "record.link": f"/requests/{record.id}",
        "requester.name": names.get(str(record.requester_id)),
        "conversation.author": names.get(author) if author else None,
        "conversation.excerpt": reply_excerpt(entry.body),
    }
    return RecordContext(
        record_id=record.id,
        display_id=record.display_id,
        link=f"/requests/{record.id}",
        public_link=f"/service-requests/{record.id}",
        variables=variables,
        public_variables=variables,
        relatives={REQUESTER: people},
        conditions={"priority": record.priority},
        event_code=REPLY,
        entry_id=entry.id,
    )


async def _public_comment(session: AsyncSession, record_id: uuid.UUID) -> str | None:
    """The rejecting approver's comment, unless they marked it private."""
    row = await session.scalar(
        select(WorkItemApproval)
        .where(
            WorkItemApproval.work_item_id == record_id,
            WorkItemApproval.state == rules.ApprovalState.REJECTED.value,
            WorkItemApproval.deleted_at.is_(None),
        )
        .order_by(WorkItemApproval.decided_at.desc().nulls_last())
        .limit(1)
    )
    if row is None or row.comment_private:
        return None
    return row.comment


SOURCE = ServiceRequestNotifications()


def register() -> None:
    """Make service request approvals notify (idempotent; called when work_items is imported)."""
    register_record_source(SOURCE)
