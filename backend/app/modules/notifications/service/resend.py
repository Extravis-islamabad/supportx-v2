"""Resending a reply's e-mail that failed (WP-024 session 3; REQ-INC-059 AC3, REQ-NTF-020 AC2).

The record's module owns the route and its checks (who may reply, the entry's version, the
Idempotency-Key, the audit entry); this port does the sending: the failed e-mail to the
requester goes again, as it was written, to the person's current address. A new delivery row
names the one it resends and who asked, and the entry moves to "queued". A second request
finds nothing failed and is refused (`delivery_not_failed`), so a double click sends once.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict
from app.modules.identity_access import notifiable_people
from app.modules.notifications.domain.rules import DeliveryState
from app.modules.notifications.events import DeliveryRecorded
from app.modules.notifications.infra.models import NotificationDelivery
from app.modules.notifications.service.engine import REQUESTER, entry_changed
from app.shared.events import Actor, record_event
from app.shared.files.ports import Actor as Person
from app.shared.mail import (
    Language,
    MailContentGone,
    OutgoingMail,
    mail_configured,
    queue_mail,
    requeue_mail,
)
from app.shared.notifications.ports import NotificationChannel, record_source


class DeliveryNotFailed(Conflict):
    """Nothing failed to resend (already sent, queued, waiting, or resent a moment ago)."""

    code = "delivery_not_failed"


class MailStillNotConfigured(Conflict):
    """Outgoing mail is still not set up: a resend would only wait again."""

    code = "mail_not_configured"


class ResendContentGone(Conflict):
    """The e-mail's text was cleared after the retention period; write the reply again."""

    code = "mail_content_gone"


async def _failed_rows(session: AsyncSession, entry_id: uuid.UUID) -> list[NotificationDelivery]:
    """The newest requester e-mail per person for the entry, when it failed (locked)."""
    rows = list(
        await session.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.entry_id == entry_id,
                NotificationDelivery.channel == NotificationChannel.EMAIL.value,
            )
            .order_by(NotificationDelivery.created_at.desc())
            .with_for_update()
        )
    )
    newest: dict[uuid.UUID | None, NotificationDelivery] = {}
    for row in rows:
        if REQUESTER in row.reasons:
            newest.setdefault(row.user_id, row)
    return [r for r in newest.values() if r.state == DeliveryState.FAILED.value]


async def _queue_again(session: AsyncSession, row: NotificationDelivery, to: str) -> uuid.UUID:
    settings = get_settings()
    try:
        if row.mail_id is not None:
            return await requeue_mail(session, settings, row.mail_id, to=to)
    except MailContentGone as exc:
        raise ResendContentGone from exc
    if row.text_body is None:  # waited and gave up: its rendered text is kept on the row
        raise ResendContentGone
    language: Language = row.language if row.language in ("en", "ar", "ur") else "en"  # type: ignore[assignment]  # narrowed by the check
    return await queue_mail(
        session,
        settings,
        OutgoingMail(
            kind="notification",
            to=(to,),
            language=language,
            subject=row.subject or row.display_id,
            text=row.text_body,
            html=row.html_body,
        ),
    )


async def resend_entry(session: AsyncSession, entry_id: uuid.UUID, actor: Person) -> None:
    """Send a reply's failed e-mail again (see the module docstring for the checks)."""
    failed = await _failed_rows(session, entry_id)
    if not failed:
        raise DeliveryNotFailed
    if not mail_configured(get_settings()):
        raise MailStillNotConfigured
    people = await notifiable_people(session, [r.user_id for r in failed if r.user_id])
    now = datetime.now(UTC)
    for row in failed:
        person = people.get(row.user_id) if row.user_id else None
        if person is None or not person.email:
            continue  # still no address: it stays failed with its reason
        mail_id = await _queue_again(session, row, person.email)
        row.subject = row.text_body = row.html_body = None  # the copy carries it now
        again = NotificationDelivery(
            tenant_id=row.tenant_id,
            event_id=row.event_id,
            event_code=row.event_code,
            record_type=row.record_type,
            record_id=row.record_id,
            display_id=row.display_id,
            user_id=row.user_id,
            reasons=list(row.reasons),
            channel=row.channel,
            state=DeliveryState.QUEUED.value,
            language=row.language,
            mail_id=mail_id,
            entry_id=row.entry_id,
            resent_from=row.id,
            resent_by=actor.user_id,
        )
        session.add(again)
        await session.flush()
        await record_event(
            session,
            DeliveryRecorded(
                delivery_id=again.id,
                record_type=row.record_type,
                record_id=row.record_id,
                channel=row.channel,
                state=again.state,
            ),
            aggregate_id=again.id,
            actor=Actor.user(actor.user_id),
        )
        await entry_changed(
            session, record_source(row.record_type), again, state="queued", reason=None, at=now
        )
