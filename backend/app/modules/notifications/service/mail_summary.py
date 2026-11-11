"""The people who set mail up hear when e-mails were given up for want of it (D-157 item 4).

While outgoing mail is not set up, e-mails wait (D-116); after 7 days the waiting schedule gives
them up (`engine.expire_waiting`, never sent late). Each run that gives any up records one
`MailNotSentSummary` (how many, the oldest), and this source turns it into ONE in-app notice for
each person who may set mail up (`integrations.manage_email`, the tenant admins by default),
with a link to the mail settings: one notice per run, never one per e-mail.

Lane A's review: the run claims its summary once (`engine._claim_summary`, processed_events
keyed by tenant and cut-off minute), so a retried run never tells anyone twice; the payload is a
count and the oldest time, no addresses; recipients are active people only (identity's
`holders`), at most 200; the event is not required (people may switch it off).

In the app only by default: the summary cannot go by e-mail (there is no mail to send it with).
An admin who adds e-mail to the rule anyway gets a waiting e-mail like any other, and when it
is given up in turn it is not counted again (`SUMMARY_EVENT`), so a summary never feeds itself.
"""

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.identity_access import subject_for, worker_policy
from app.modules.notifications.events import MailNotSentSummary
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

RECORD_TYPE = "outgoing_mail"
SUMMARY_EVENT = "outgoing_mail.not_sent"
MAIL_ADMINS = "mail_admins"  # the recipient kind (labelled with the mailbox source's)
SETS_UP_MAIL = "integrations.manage_email"  # who can set mail up (the mail status card's fixers)
ADMINS_LIMIT = 200  # active holders only (holders() skips inactive and service identities)
LINK = "/admin/mail"

_VARIABLES = (
    Variable("mail.count", "notification_variable.mail.count"),
    Variable("mail.oldest_at", "notification_variable.mail.oldest_at"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


class MailSummaryNotifications:
    """The notification source of the "e-mails given up" summary (record type outgoing_mail)."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = RECORD_TYPE
    events: ClassVar[tuple[NotificationEvent, ...]] = (
        NotificationEvent(
            SUMMARY_EVENT,
            NotificationCategory.STATUS,
            EventDefault(
                enabled=True, recipients=(MAIL_ADMINS,), channels=(NotificationChannel.IN_APP,)
            ),
            required=False,  # people may switch it off (lane A)
        ),
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (MAIL_ADMINS,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (MailNotSentSummary.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """The one summary event."""
        del envelope
        return (SUMMARY_EVENT,)

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """How many, the oldest, and who may set mail up now."""
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        held = await worker_policy().holders(session, tenant, SETS_UP_MAIL, limit=ADMINS_LIMIT)
        if not held:
            return None
        payload = envelope.payload
        values: dict[str, VariableValue] = {
            "mail.count": int(payload["count"]),
            "mail.oldest_at": datetime.fromisoformat(str(payload["oldest_at"])),
            "record.link": LINK,
        }
        return RecordContext(
            record_id=uuid.UUID(str(payload["summary_id"])),
            display_id="",
            link=LINK,
            variables=values,
            public_variables=values,
            relatives={MAIL_ADMINS: frozenset(user_id for user_id, _ in held)},
            conditions={},
            event_code=event_code,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for people who may set mail up (checked at send time), NONE for anyone else."""
        del record_id
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        return RecordAccess.FULL if subject.holds(SETS_UP_MAIL) else RecordAccess.NONE


SOURCE = MailSummaryNotifications()


def register() -> None:
    """Make the summary notify (idempotent; when the notifications module is imported)."""
    register_record_source(SOURCE)
