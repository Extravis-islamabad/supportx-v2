"""Mail admins hear about mailbox trouble (WP-024 session 2; REQ-INT-050, D-109 (3)).

A mailbox that stops working (a refused sign-in, an expired secret, a revoked consent) and an OAuth
credential that expires soon notify the people who manage mailboxes, in the app and by e-mail.
On by default; admins tune them on the notification rules page like any other event. The mail
page shows the state all the time, so nothing waits silently.
"""

import uuid
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.identity_access import subject_for, worker_policy
from app.modules.integrations.events import (
    MailboxCredentialExpiring,
    MailboxFailing,
    MailboxMailHeld,
)
from app.modules.integrations.infra.models import Mailbox
from app.modules.integrations.service.mailboxes import MANAGE
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    LabelRef,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

RECORD_TYPE = "mailbox"
MAIL_ADMINS = "mail_admins"
ADMINS_LIMIT = 200  # people told about one mailbox; a tenant has a handful of mail admins
FAILING = "mailbox.failing"
EXPIRING = "mailbox.credential_expiring"
HELD = "mailbox.mail_held"  # a sender over the flood limit (REQ-NTF-023)

_VARIABLES = (
    Variable("record.title", "notification_variable.mailbox.address"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


class MailboxNotifications:
    """The notification source of mailboxes (record type "mailbox")."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = "mailbox"
    events: ClassVar[tuple[NotificationEvent, ...]] = (
        NotificationEvent(
            FAILING,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(MAIL_ADMINS,)),
            variables=(Variable("mailbox.reason", "notification_variable.mailbox.reason"),),
        ),
        NotificationEvent(
            EXPIRING,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(MAIL_ADMINS,)),
            variables=(Variable("mailbox.expires_at", "notification_variable.mailbox.expires_at"),),
        ),
        NotificationEvent(
            HELD,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(MAIL_ADMINS,)),
        ),
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (MAIL_ADMINS,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (
        MailboxFailing.event_type,
        MailboxCredentialExpiring.event_type,
        MailboxMailHeld.event_type,
    )

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notification event per domain event."""
        return {
            MailboxFailing.event_type: (FAILING,),
            MailboxCredentialExpiring.event_type: (EXPIRING,),
            MailboxMailHeld.event_type: (HELD,),
        }.get(envelope.event_type, ())

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The mailbox and the people who manage mailboxes, now."""
        mailbox_id = uuid.UUID(str(envelope.payload["mailbox_id"]))
        mailbox = await session.get(Mailbox, mailbox_id)
        if mailbox is None or mailbox.deleted_at is not None:
            return None
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        admins = await worker_policy().holders(session, tenant, MANAGE, limit=ADMINS_LIMIT)
        values: dict[str, VariableValue] = {
            "record.title": mailbox.address,
            "record.link": "/admin/mail",
        }
        if event_code == FAILING:
            values["mailbox.reason"] = LabelRef(f"mailbox_reason.{envelope.payload['reason']}")
        elif event_code == EXPIRING:
            values["mailbox.expires_at"] = mailbox.credential_expires_at
        return RecordContext(
            record_id=mailbox.id,
            display_id=mailbox.address,
            link="/admin/mail",
            variables=values,
            public_variables=values,
            relatives={MAIL_ADMINS: frozenset(user_id for user_id, _ in admins)},
            conditions={},
            event_code=event_code,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for people who manage mailboxes (checked at send time), NONE for anyone else."""
        del record_id
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        return RecordAccess.FULL if subject.holds(MANAGE) else RecordAccess.NONE


SOURCE = MailboxNotifications()


def register() -> None:
    """Make mailboxes notify (idempotent; called when the integrations module is imported)."""
    register_record_source(SOURCE)
