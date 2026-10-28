"""One fetched message → a record, a reply, or nothing, with the ledger (WP-024).

`process(session, settings, mailbox, raw)` runs in the tenant's transaction:

1. claim the message in the ledger (`mail_fetched`, one row per mailbox and Message-ID): a
   message seen before is skipped, so a restart between storing and marking never duplicates;
2. parse it and decide (`domain.mailboxes.route`);
3. act through the owning module's port (`app.shared.mail.ports`): a new incident, a reply on
   the record it answers (an automatic reply is recorded with no reaction and no notification),
   or a polite answer for refused mail (never to automatic senders: no loops);
4. write the outcome on the ledger row; a refusal by the owning module is kept as "held" with
   its code and parameters for an admin.

The caller marks the message on the mail server only after this transaction commits.
"""

import html
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from markupsafe import Markup, escape
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.modules.identity_access import create_requester_from_mail, person_by_email
from app.modules.integrations.domain.mailboxes import (
    MailboxCreates,
    MailboxRules,
    Outcome,
    UnknownSenders,
    route,
)
from app.modules.integrations.infra.models import Mailbox, MailFetched
from app.modules.notifications import records_for_mail
from app.shared.labels import label
from app.shared.mail import MailRefused, OutgoingMail, mail_configured, queue_mail
from app.shared.mail.domain.inbound import InboundMessage, parse, reply_text
from app.shared.mail.ports import FoundRecord, InboundRefused, InboundTarget, inbound_target

log = get_logger(__name__)
RECORD_TYPE = "incident"  # what mailboxes create at MVP (service requests join with WP-030)


def body_html(text: str) -> str:
    """Plain text as safe HTML paragraphs (the record's rich-text field takes HTML)."""
    paragraphs = [p for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    return str(
        Markup("").join(
            Markup("<p>{}</p>").format(Markup("<br>").join(escape(line) for line in p.split("\n")))
            for p in paragraphs
        )
    )


def _rules(mailbox: Mailbox) -> MailboxRules:
    return MailboxRules(
        address=mailbox.address,
        creates=MailboxCreates(mailbox.creates),
        unknown_senders=UnknownSenders(mailbox.unknown_senders),
        allowed_domains=tuple(mailbox.allowed_domains),
    )


async def _claim(session: AsyncSession, mailbox: Mailbox, message: InboundMessage) -> bool:
    """Record the message once; False when it was handled before."""
    result = await session.execute(
        insert(MailFetched)
        .values(
            tenant_id=mailbox.tenant_id,
            mailbox_id=mailbox.id,
            message_id=message.message_id[:500],
            sender=message.sender[:320],
            subject=message.subject[:500],
            outcome=Outcome.HELD.value,  # until decided below, in this transaction
        )
        .on_conflict_do_nothing()
    )
    return bool(getattr(result, "rowcount", 0))


async def _recent(session: AsyncSession, sender: str) -> int:
    since = datetime.now(UTC) - timedelta(hours=1)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(MailFetched)
            .where(MailFetched.sender == sender, MailFetched.created_at >= since)
        )
        or 0
    )


async def _answer(
    session: AsyncSession, settings: Settings, mailbox: Mailbox, message: InboundMessage, key: str
) -> None:
    """A polite answer to a person whose mail created nothing (never to automatic mail)."""
    if message.automatic is not None or not mail_configured(settings) or not message.sender:
        return
    subject = label(f"{key}.subject", "en", subject=message.subject)
    text = label(f"{key}.body", "en", address=mailbox.address)
    try:
        await queue_mail(
            session,
            settings,
            OutgoingMail(kind="mailbox_answer", to=(message.sender,), subject=subject, text=text),
        )
    except MailRefused as refused:
        log.warning("mailbox_answer_refused", code=refused.code)


async def _finish(  # noqa: PLR0913 - the ledger row's result, explicit
    session: AsyncSession,
    mailbox: Mailbox,
    message: InboundMessage,
    outcome: Outcome,
    *,
    reason: str | None = None,
    params: dict[str, str] | None = None,
    record: tuple[str, uuid.UUID] | None = None,
) -> Outcome:
    row = await session.get(MailFetched, (mailbox.tenant_id, mailbox.id, message.message_id[:500]))
    if row is not None:
        row.outcome = outcome.value
        row.reason = reason
        row.reason_params = dict(params or {})
        row.record_type, row.record_id = record or (None, None)
        row.updated_at = datetime.now(UTC)
    return outcome


@dataclass(frozen=True)
class _Context:
    session: AsyncSession
    mailbox: Mailbox
    message: InboundMessage
    target: InboundTarget
    sender_id: uuid.UUID | None


async def _automatic(ctx: _Context, found: FoundRecord, reason: str | None) -> Outcome:
    """An out-of-office on a record: on its timeline as a system entry, nothing else."""
    if ctx.sender_id is not None and ctx.sender_id in found.requester_ids:
        await ctx.target.reply_from_mail(
            ctx.session,
            found,
            author_id=ctx.sender_id,
            body_html=body_html(reply_text(ctx.message.text)),
            automatic=True,
            message_id=ctx.message.message_id,
        )
    return await _finish(
        ctx.session, ctx.mailbox, ctx.message, Outcome.AUTOMATIC, reason=reason,
        record=(found.record_type, found.record_id),
    )  # fmt: skip


async def _reply(ctx: _Context, found: FoundRecord) -> Outcome:
    """The requester's reply; staff and others reply in the app (no entry, lane A)."""
    if ctx.sender_id is None or ctx.sender_id not in found.requester_ids:
        return await _finish(
            ctx.session, ctx.mailbox, ctx.message, Outcome.HELD, reason="not_requester"
        )
    follow_up = await ctx.target.reply_from_mail(
        ctx.session,
        found,
        author_id=ctx.sender_id,
        body_html=body_html(reply_text(ctx.message.text)),
        automatic=False,
        message_id=ctx.message.message_id,
    )
    record = follow_up or found
    return await _finish(
        ctx.session, ctx.mailbox, ctx.message, Outcome.REPLIED,
        record=(record.record_type, record.record_id),
    )  # fmt: skip


async def _create(ctx: _Context, *, create_requester: bool) -> Outcome:
    """A new incident from the mail (the sender made a requester first when allowed)."""
    requester = ctx.sender_id
    if requester is None and create_requester:
        requester = await create_requester_from_mail(
            ctx.session, email=ctx.message.sender, name=ctx.message.sender_name
        )
    if requester is None:  # pragma: no cover - route() only creates for known or made senders
        return await _finish(
            ctx.session, ctx.mailbox, ctx.message, Outcome.REJECTED, reason="unknown_sender"
        )
    created = await ctx.target.create_from_mail(
        ctx.session,
        requester_id=requester,
        subject=ctx.message.subject or html.unescape(ctx.message.text[:80]),
        body_html=body_html(ctx.message.text),
        group_id=ctx.mailbox.group_id,
        message_id=ctx.message.message_id,
    )
    return await _finish(
        ctx.session, ctx.mailbox, ctx.message, Outcome.CREATED,
        record=(created.record_type, created.record_id),
    )  # fmt: skip


async def process(  # noqa: PLR0911 - one return per outcome of the module docstring
    session: AsyncSession,
    settings: Settings,
    mailbox: Mailbox,
    raw: bytes,
    *,
    own_addresses: tuple[str, ...],
) -> Outcome | None:
    """Handle one fetched message; None when it was handled before (skip, but mark it)."""
    message = parse(raw)
    if not await _claim(session, mailbox, message):
        return None
    target = inbound_target(RECORD_TYPE)
    found: FoundRecord | None = None
    if target is not None:
        answered = await records_for_mail(session, message.thread_ids)
        found = await target.find_record(
            session,
            tokens=message.tokens,
            record_ids=[record_id for kind, record_id in answered if kind == RECORD_TYPE],
        )
    sender_id = await person_by_email(session, message.sender) if message.sender else None
    decision = route(
        mailbox=_rules(mailbox),
        automatic=message.automatic,
        sender=message.sender,
        own_addresses=own_addresses,
        recent_from_sender=await _recent(session, message.sender) - 1,  # minus this one
        answers_record=found is not None,
        sender_known=sender_id is not None,
        size=len(raw),
    )
    if target is None:
        return await _finish(session, mailbox, message, Outcome.HELD, reason="no_target")
    ctx = _Context(session, mailbox, message, target, sender_id)
    if decision.outcome is Outcome.AUTOMATIC and found is not None:
        return await _automatic(ctx, found, decision.reason)
    if decision.outcome not in (Outcome.CREATED, Outcome.REPLIED):
        if decision.outcome is Outcome.REJECTED:
            await _answer(session, settings, mailbox, message, f"mailbox_answer.{decision.reason}")
        return await _finish(session, mailbox, message, decision.outcome, reason=decision.reason)
    try:
        if found is not None:
            return await _reply(ctx, found)
        return await _create(ctx, create_requester=decision.create_requester)
    except InboundRefused as refused:
        return await _finish(
            session, mailbox, message, Outcome.HELD, reason=refused.code, params=refused.params
        )
