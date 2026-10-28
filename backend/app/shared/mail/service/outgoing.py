"""Queue and send e-mails: the one mail sender of SupportX (WP-039 session 2, D-089 D3).

Interface for every module (docs/architecture/mail.md):

    if mail_configured(settings):
        mail_id = await queue_mail(session, OutgoingMail(kind="report", to=(...,), ...))

`queue_mail` stores the message in the caller's transaction and records `system.mail.queued`
through the outbox (CLAUDE.md rule b), so a message is sent exactly when the caller's change
commits. The `system__mail_send` worker sends it (`deliver`). A temporary failure (server down,
4xx) is tried again later with backoff, up to `mail_max_attempts` times, by the
`system__mail_retry` schedule (`due_messages`); a permanent refusal (5xx) is recorded at once.
Bodies and attachments are cleared `mail_content_retention_days` after the message is done
(`purge_content`).
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import ServiceUnavailable
from app.core.logging import get_logger
from app.shared.events import record_event
from app.shared.ids import new_id
from app.shared.mail.domain.message import Attachment, OutgoingMail, build_mime, check
from app.shared.mail.events import MailQueued
from app.shared.mail.infra import smtp
from app.shared.mail.infra.models import MailAttachment, MailMessage

log = get_logger(__name__)


class MailNotConfigured(ServiceUnavailable):
    """No outgoing mail server is set up on this installation."""

    code = "mail_not_configured"


def mail_configured(settings: Settings) -> bool:
    """Whether outgoing mail is set up (cheap: settings only, no connection)."""
    return bool(settings.mail_smtp_host and settings.mail_from_address)


def smtp_settings(settings: Settings) -> smtp.SmtpSettings:
    """The SMTP server from the installation settings."""
    if not mail_configured(settings):
        raise MailNotConfigured
    password = settings.mail_smtp_password
    return smtp.SmtpSettings(
        host=settings.mail_smtp_host or "",
        port=settings.mail_smtp_port,
        security=settings.mail_smtp_security,
        username=settings.mail_smtp_username,
        password=password.get_secret_value() if password else None,
        timeout=settings.mail_timeout_seconds,
    )


async def queue_mail(session: AsyncSession, settings: Settings, mail: OutgoingMail) -> uuid.UUID:
    """Store `mail` for sending in the caller's transaction; its ID (see module docstring).

    Raises MailNotConfigured when there is no mail server, MailRefused when the message breaks
    a rule (domain/message.py).
    """
    if not mail_configured(settings):
        raise MailNotConfigured
    check(mail)
    context = session.info[SESSION_TENANT_KEY]
    mail_id = new_id()
    session.add(
        MailMessage(
            id=mail_id,
            tenant_id=context.tenant_id,
            kind=mail.kind,
            language=mail.language,
            recipients=list(mail.to),
            reply_to=mail.reply_to,
            sender_name=mail.sender_name,
            subject=mail.subject,
            text_body=mail.text,
            html_body=mail.html,
            state="queued",
            version=1,
        )
    )
    await session.flush()  # the message row first: attachments reference it
    for attachment in mail.attachments:
        session.add(
            MailAttachment(
                id=new_id(),
                tenant_id=context.tenant_id,
                message_id=mail_id,
                name=attachment.name,
                content_type=attachment.content_type,
                size=len(attachment.content),
                content=attachment.content,
                version=1,
            )
        )
    await session.flush()
    await record_event(session, MailQueued(mail_id=mail_id, kind=mail.kind), aggregate_id=mail_id)
    return mail_id


async def _load(session: AsyncSession, row: MailMessage) -> OutgoingMail:
    attachments = await session.scalars(
        select(MailAttachment)
        .where(MailAttachment.message_id == row.id)
        .order_by(MailAttachment.created_at)
    )
    return OutgoingMail(
        kind=row.kind,
        to=tuple(row.recipients),
        subject=row.subject,
        text=row.text_body or "",
        language=row.language,  # type: ignore[arg-type]  # the column holds only en, ar, ur
        html=row.html_body,
        reply_to=row.reply_to,
        sender_name=row.sender_name,
        attachments=tuple(
            Attachment(a.name, a.content_type, a.content or b"") for a in attachments
        ),
    )


async def deliver(
    session: AsyncSession, settings: Settings, mail_id: uuid.UUID, *, send: smtp.Sender = smtp.send
) -> str:
    """Send one queued message; its state afterwards (`sent`, `failed`, or `queued` to retry)."""
    row = await session.scalar(
        select(MailMessage).where(MailMessage.id == mail_id).with_for_update(skip_locked=True)
    )
    if row is None or row.state != "queued":
        return "gone" if row is None else row.state  # handled already, or being sent now
    now = datetime.now(UTC)
    row.attempts += 1
    row.version += 1
    mime = build_mime(
        await _load(session, row),
        from_address=settings.mail_from_address or "",
        from_name=settings.mail_from_name,
        message_id_domain=(settings.mail_from_address or "@supportx").rsplit("@", 1)[1],
        sent_at=now,
    )
    try:
        await send(smtp_settings(settings), mime)
    except smtp.PermanentFailure as exc:
        row.state, row.failure = "failed", exc.code
        row.purge_after = now + timedelta(days=settings.mail_content_retention_days)
        log.warning("mail_refused", mail_id=str(mail_id), reason=exc.code)
        return row.state
    except smtp.TemporaryFailure:
        if row.attempts >= settings.mail_max_attempts:
            row.state, row.failure = "failed", "gave_up"
            row.purge_after = now + timedelta(days=settings.mail_content_retention_days)
            log.warning("mail_gave_up", mail_id=str(mail_id), attempts=row.attempts)
        else:
            row.next_attempt_at = now + retry_delay(row.attempts)
        return row.state
    row.state, row.sent_at, row.message_id = "sent", now, str(mime["Message-ID"])
    row.next_attempt_at = None
    row.purge_after = now + timedelta(days=settings.mail_content_retention_days)
    return row.state


@dataclass(frozen=True)
class MailState:
    """Where one queued message stands (for logs such as the notification log, REQ-NTF-020)."""

    state: str  # queued | sent | failed
    attempts: int
    failure: str | None  # reason code of the last failure
    sent_at: datetime | None


async def mail_states(
    session: AsyncSession, mail_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, MailState]:
    """The state of each message (of the session's tenant); unknown IDs are left out."""
    if not mail_ids:
        return {}
    rows = await session.execute(
        select(
            MailMessage.id,
            MailMessage.state,
            MailMessage.attempts,
            MailMessage.failure,
            MailMessage.sent_at,
        ).where(MailMessage.id.in_(list(mail_ids)))
    )
    return {row.id: MailState(row.state, row.attempts, row.failure, row.sent_at) for row in rows}


def retry_delay(attempts: int) -> timedelta:
    """1, 2, 4, 8 … minutes after the first, second, third … attempt (at most an hour)."""
    return timedelta(minutes=min(2 ** (attempts - 1), 60))


async def due_messages(
    session: AsyncSession, now: datetime | None = None, limit: int = 50
) -> list[uuid.UUID]:
    """Queued messages whose next attempt is due (the retry schedule sends them)."""
    moment = now or datetime.now(UTC)
    found = await session.scalars(
        select(MailMessage.id)
        .where(
            MailMessage.state == "queued",
            MailMessage.next_attempt_at.is_not(None),
            MailMessage.next_attempt_at <= moment,
        )
        .order_by(MailMessage.next_attempt_at)
        .limit(limit)
    )
    return list(found)


async def purge_content(session: AsyncSession, now: datetime | None = None) -> int:
    """Clear bodies and attachments of messages done long enough ago; how many messages."""
    moment = now or datetime.now(UTC)
    due = list(
        await session.scalars(
            select(MailMessage.id).where(
                MailMessage.purge_after.is_not(None),
                MailMessage.purge_after <= moment,
                MailMessage.text_body.is_not(None),
            )
        )
    )
    if not due:
        return 0
    await session.execute(
        update(MailMessage).where(MailMessage.id.in_(due)).values(text_body=None, html_body=None)
    )
    await session.execute(
        update(MailAttachment).where(MailAttachment.message_id.in_(due)).values(content=None)
    )
    return len(due)


def sender_domain(settings: Settings) -> str:
    """The console's host, for messages that need a domain (Message-ID fallback)."""
    return urlsplit(settings.console_url).hostname or "supportx"
