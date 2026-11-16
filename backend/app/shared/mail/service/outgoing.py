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
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from html import escape as html_escape
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import ServiceUnavailable
from app.core.logging import get_logger
from app.shared import action_links
from app.shared.events import record_event
from app.shared.ids import new_id
from app.shared.mail.domain.message import (
    Attachment,
    OutgoingMail,
    build_mime,
    check,
    links_from_json,
    links_to_json,
)
from app.shared.mail.events import MailQueued, MailStateChanged
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
            links=links_to_json(mail.links),
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
        links=links_from_json(row.links),
    )


async def _with_links(session: AsyncSession, mail: OutgoingMail) -> OutgoingMail:
    """The outgoing copy with each one-time link made now (D-132), never stored or logged.

    A link from an earlier attempt that was never delivered is revoked first, so only the one
    in the e-mail that leaves works (lane B review: a fresh token invalidates the old one).
    """
    if not mail.links:
        return mail
    text, html = mail.text, mail.html
    for link in mail.links:
        request = link.request
        await action_links.revoke_for(session, request.object_type, request.object_id)
        token = await action_links.issue(
            session,
            recipient_id=request.recipient_id,
            action=request.action,
            object_type=request.object_type,
            object_id=request.object_id,
            object_version=request.object_version,
        )
        url = link.prefix + token
        spot = action_links.marker(link.name)
        text = text.replace(spot, url)
        html = None if html is None else html.replace(spot, html_escape(url))
    return replace(mail, text=text, html=html, links=())


# Never sent late (D-116, REQ-INC-060): a message that waited this long for outgoing mail to be
# set up fails instead. The same 7 days as the notification engine's WAITING_DAYS, which this
# shared module cannot import; the reason is the engine's too (its labels say "never sent: mail
# was not set up within 7 days").
WAITING_FOR_MAIL_DAYS = 7
NOT_SENT_IN_TIME = "not_sent_in_time"


async def deliver(
    session: AsyncSession, settings: Settings, mail_id: uuid.UUID, *, send: smtp.Sender = smtp.send
) -> str:
    """Send one queued message; its state afterwards (`sent`, `failed`, or `queued` to retry).

    With no mail server set up here (removed after the message was queued, or this process
    lacks the settings the queueing one had), nothing is attempted: the message waits, due as
    soon as mail works, and its callers hear `retrying` with failure `mail_not_configured` (QA
    2026-11-04 #2: never "sending" for ever). After `WAITING_FOR_MAIL_DAYS` it fails as
    `not_sent_in_time` instead, set up or not: never sent late (D-116). Before this, building
    the message (no sender address) or `smtp_settings` raised out of the attempt, the
    transaction rolled back and the message stayed queued with no next attempt, which the retry
    schedule never picks up.
    """
    row = await session.scalar(
        select(MailMessage).where(MailMessage.id == mail_id).with_for_update(skip_locked=True)
    )
    if row is None or row.state != "queued":
        return "gone" if row is None else row.state  # handled already, or being sent now
    now = datetime.now(UTC)
    configured = mail_configured(settings)
    waited = not configured or row.failure == MailNotConfigured.code
    if waited and row.created_at < now - timedelta(days=WAITING_FOR_MAIL_DAYS):
        # Mail was not set up in time: never sent late, even once it is set up now (D-116).
        row.state, row.failure, row.next_attempt_at = "failed", NOT_SENT_IN_TIME, None
        row.purge_after = now + timedelta(days=settings.mail_content_retention_days)
        row.version += 1
        log.warning("mail_not_sent_in_time", mail_id=str(mail_id))
        await _changed(session, row, "failed", now)
        return row.state
    if not configured:
        await _wait_for_mail(session, row, now)
        return row.state
    row.attempts += 1
    row.version += 1
    mime = build_mime(
        await _with_links(session, await _load(session, row)),
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
        await _changed(session, row, "failed", now)
        return row.state
    except smtp.TemporaryFailure as exc:
        if row.attempts >= settings.mail_max_attempts:
            row.state, row.failure = "failed", "gave_up"
            row.purge_after = now + timedelta(days=settings.mail_content_retention_days)
            log.warning("mail_gave_up", mail_id=str(mail_id), attempts=row.attempts)
            await _changed(session, row, "failed", now)
        else:
            row.failure = exc.code
            row.next_attempt_at = now + retry_delay(row.attempts)
            await _changed(session, row, "retrying", now)
        return row.state
    row.state, row.sent_at, row.message_id = "sent", now, str(mime["Message-ID"])
    row.failure = None
    row.next_attempt_at = None
    row.purge_after = now + timedelta(days=settings.mail_content_retention_days)
    await _changed(session, row, "sent", now)
    return row.state


async def _wait_for_mail(session: AsyncSession, row: MailMessage, now: datetime) -> None:
    """Keep `row` queued until outgoing mail is set up; say so once (a redelivery says nothing)."""
    if row.failure == MailNotConfigured.code and row.next_attempt_at is not None:
        return
    row.failure = MailNotConfigured.code
    row.next_attempt_at = now  # the retry schedule sends it on its first run with mail set up
    row.version += 1
    await _changed(session, row, "retrying", now)


async def _changed(
    session: AsyncSession,
    row: MailMessage,
    state: Literal["sent", "retrying", "failed"],
    at: datetime,
) -> None:
    """Tell the callers' modules (notifications) how the attempt ended, in this transaction."""
    await record_event(
        session,
        MailStateChanged(mail_id=row.id, kind=row.kind, state=state, failure=row.failure, at=at),
        aggregate_id=row.id,
    )


class MailContentGone(ServiceUnavailable):
    """The message's text was cleared (retention), so it cannot be sent again as it was."""

    code = "mail_content_gone"


async def requeue_mail(
    session: AsyncSession, settings: Settings, mail_id: uuid.UUID, *, to: str
) -> uuid.UUID:
    """Queue a copy of a sent or failed message to `to` (a resend); the new message's ID.

    The same subject and bodies, to the person's current address. MailNotConfigured without
    outgoing mail; MailContentGone when retention already cleared the text.
    """
    row = await session.scalar(select(MailMessage).where(MailMessage.id == mail_id))
    if row is None or row.text_body is None:
        raise MailContentGone
    original = await _load(session, row)
    return await queue_mail(
        session,
        settings,
        OutgoingMail(
            kind=original.kind,
            to=(to,),
            subject=original.subject,
            text=original.text,
            language=original.language,
            html=original.html,
            reply_to=original.reply_to,
            sender_name=original.sender_name,
            attachments=original.attachments,
            links=original.links,  # a resend makes fresh links at send (D-132)
        ),
    )


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


ERASED_RECIPIENT = "erased@invalid"  # RFC 2606: never deliverable, names nobody
RECIPIENT_ERASED = "recipient_erased"  # the failure code of a queued mail nobody else gets


async def forget_recipient(session: AsyncSession, address: str) -> int:
    """A person's GDPR erasure: mail to `address` keeps no trace of them; how many messages.

    Called by the erasure job in the tenant's session, **before** the person's address is
    anonymised (afterwards nothing can find their mail). For every message the address was sent
    or queued to:
    - its place in the recipients becomes `ERASED_RECIPIENT`, so the row no longer says to whom;
    - a message still queued for others only loses this recipient, and goes to the others as
      planned; one queued for them alone is failed (`recipient_erased`) and never sent;
    - otherwise (sent, failed, or queued for them alone) the subject, bodies, one-time links and
      attachments are cleared now rather than at `mail_content_retention_days`;
    - a message sent on their behalf (`reply_to` is them) loses its reply-to and sender name.
    The rows are locked (no skip): an erasure waits for a delivery in flight instead of racing
    it. Idempotent: a second call finds nothing.
    """
    wanted = address.strip().lower()
    if not wanted:
        return 0
    rows = list(
        await session.scalars(
            select(MailMessage)
            .where(
                func.lower(func.array_to_string(MailMessage.recipients, "\n")).contains(
                    wanted, autoescape=True
                )
                | (func.lower(MailMessage.reply_to) == wanted)
            )
            .with_for_update()
        )
    )
    changed = 0
    now = datetime.now(UTC)
    for row in rows:
        replied = (row.reply_to or "").strip().lower() == wanted
        if replied:  # sent on their behalf: their address and name leave it
            row.reply_to = row.sender_name = None
        hits = [r for r in row.recipients if r.strip().lower() == wanted]
        if not hits:
            if replied:
                row.updated_at = now
                changed += 1
            continue  # otherwise a substring of another address
        others = [r for r in row.recipients if r.strip().lower() != wanted]
        if row.state == "queued" and others:
            row.recipients = others
        else:
            row.recipients = [
                ERASED_RECIPIENT if r.strip().lower() == wanted else r for r in row.recipients
            ]
            if row.state == "queued":
                row.state, row.failure = "failed", RECIPIENT_ERASED
            row.subject = ""
            row.text_body = row.html_body = None
            row.links = None
            await session.execute(
                update(MailAttachment)
                .where(MailAttachment.message_id == row.id)
                .values(content=None)
            )
        row.updated_at = now
        changed += 1
    await session.flush()
    return changed


def sender_domain(settings: Settings) -> str:
    """The console's host, for messages that need a domain (Message-ID fallback)."""
    return urlsplit(settings.console_url).hostname or "supportx"


async def mails_with_message_ids(
    session: AsyncSession, message_ids: Sequence[str]
) -> list[uuid.UUID]:
    """The sent messages with these Message-IDs (a reply's In-Reply-To/References), this tenant."""
    if not message_ids:
        return []
    # Stored as sent ("<id@host>"); a parsed reply names them without the brackets.
    wanted = [f"<{i.strip('<>')}>" for i in list(message_ids)[:50]]
    rows = await session.scalars(select(MailMessage.id).where(MailMessage.message_id.in_(wanted)))
    return list(rows)
