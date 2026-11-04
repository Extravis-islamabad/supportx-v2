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
"""

import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound
from app.modules.identity_access import subject_for, user_names, worker_policy
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.events import WorkItemApprovalChanged
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
    recipient_kinds = (APPROVER, ADMINISTRATORS)
    variables = VARIABLES
    conditions = ("priority",)
    event_types = (WorkItemApprovalChanged.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """An approval opened: its approver hears of it, or the administrators do."""
        if not _opened(envelope):
            return ()
        return (REQUESTED,) if envelope.payload.get("approver_id") else (FALLBACK,)

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The request now, and who holds its approval now (a decided one tells nobody)."""
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


SOURCE = ServiceRequestNotifications()


def register() -> None:
    """Make service request approvals notify (idempotent; called when work_items is imported)."""
    register_record_source(SOURCE)
