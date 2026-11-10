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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound
from app.modules.identity_access import subject_for, user_names, worker_policy
from app.modules.organization import users_in_groups
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.lifecycle import StatusCategory, WorkItemAction
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.events import (
    ServiceRequestReadyToFulfil,
    WorkItemApprovalChanged,
    WorkItemCreated,
    WorkItemStatusChanged,
)
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval
from app.modules.work_items.service import approvals
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.access import APPROVE_ANY
from app.modules.work_items.service.file_access import sees_private
from app.modules.work_items.service.realtime import RECORD_KIND
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
READY = "service_request.ready_to_fulfil"  # D-154 "E1 follows d": to its group, in the app
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
    )

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """An approval opened (its approver or the administrators), or the requester's news."""
        payload = envelope.payload
        if envelope.event_type == WorkItemApprovalChanged.event_type:
            if not _opened(envelope):
                return ()
            return (REQUESTED,) if payload.get("approver_id") else (FALLBACK,)
        if payload.get("type") != SERVICE_REQUEST.code.value:
            return ()
        if envelope.event_type == ServiceRequestReadyToFulfil.event_type:
            return (READY,)
        if envelope.event_type == WorkItemCreated.event_type:
            return (RECEIVED,)
        return _status_event(payload)

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The request now, and who is told now (a decided approval tells nobody)."""
        if event_code in REQUESTER_EVENTS:
            return await _requester_context(session, event_code, envelope)
        if event_code == READY:
            return await _ready_context(session, envelope)
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
        subject = await subject_for(session, tenant, user_id)
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
        return {
            "approval_link": LinkRequest(
                recipient_id=recipient_id,
                action=approvals.LINK_ACTION,
                object_type=approvals.LINK_OBJECT,
                object_id=row.id,
                object_version=row.version,
            )
        }


REQUESTER_EVENTS = frozenset({RECEIVED, APPROVED, REJECTED, WITHDRAWN, FULFILLED})


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
