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

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from markupsafe import Markup, escape
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Conflict
from app.core.logging import get_logger
from app.modules.identity_access import (
    create_requester_from_mail,
    mail_recipients,
    person_by_email,
)
from app.modules.integrations.domain.mailboxes import (
    WAITING,
    MailboxCreates,
    MailboxRules,
    Outcome,
    UnknownSenders,
    releasable,
    route,
)
from app.modules.integrations.events import MailboxMailHeld
from app.modules.integrations.infra.models import Mailbox, MailFetched
from app.modules.integrations.service import attachments
from app.modules.notifications import records_for_mail
from app.shared.events import record_event
from app.shared.files.ports import OwnerType
from app.shared.labels import label
from app.shared.mail import Language, MailRefused, OutgoingMail, mail_configured, queue_mail
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


def _first_line(text: str) -> str:
    """The first line with words, for a mail without a subject (the incident side fits it)."""
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


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


FLOOD = "sender_rate"


async def _flood_starts(session: AsyncSession, message: InboundMessage) -> bool:
    """Whether this is the sender's first message held for flooding within the hour."""
    since = datetime.now(UTC) - timedelta(hours=1)
    earlier = await session.scalar(
        select(func.count())
        .select_from(MailFetched)
        .where(
            MailFetched.sender == message.sender,
            MailFetched.reason == FLOOD,
            MailFetched.created_at >= since,
            MailFetched.message_id != message.message_id[:500],
        )
    )
    return not earlier


async def _recent(session: AsyncSession, sender: str) -> int:
    """Messages from `sender` in the last hour (REQ-NTF-023).

    Replies and automatic mail count too (product owner, 2026-10-29).
    """
    since = datetime.now(UTC) - timedelta(hours=1)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(MailFetched)
            .where(MailFetched.sender == sender, MailFetched.created_at >= since)
        )
        or 0
    )


async def _answer(  # noqa: PLR0913 - the message, who, what to say and its values
    session: AsyncSession,
    settings: Settings,
    mailbox: Mailbox,
    message: InboundMessage,
    key: str,
    *,
    person: uuid.UUID | None = None,
    **values: str,
) -> None:
    """A short answer to the sender (mail that created nothing, or a follow-up's new ID).

    In the person's mail language when the sender is someone the tenant knows, else English.
    Never to automatic mail: two systems answering each other would loop.
    """
    if message.automatic is not None or not mail_configured(settings) or not message.sender:
        return
    known = await mail_recipients(session, [person]) if person is not None else {}
    language: Language = known[person].language if person in known else "en"
    subject = label(f"{key}.subject", language, subject=message.subject, **values)
    text = label(f"{key}.body", language, address=mailbox.address, **values)
    try:
        await queue_mail(
            session,
            settings,
            OutgoingMail(
                kind="mailbox_answer",
                to=(message.sender,),
                language=language,
                subject=subject,
                text=text,
            ),
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
    settings: Settings
    mailbox: Mailbox
    message: InboundMessage
    target: InboundTarget
    sender_id: uuid.UUID | None
    # Attachments refused only when stored (quota, permission): kept on the ledger row.
    not_kept: list[attachments.NotKept] = field(default_factory=list)

    def ledger_params(self) -> dict[str, str]:
        """The ledger row's params: which attachments could not be kept, if any."""
        if not self.not_kept:
            return {}
        return {"not_kept": ", ".join(item.name for item in self.not_kept)[:500]}


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


async def _reply(ctx: _Context, settings: Settings, found: FoundRecord) -> Outcome:
    """The requester's reply; staff and others reply in the app (no entry, lane A)."""
    if ctx.sender_id is None or ctx.sender_id not in found.requester_ids:
        return await _finish(
            ctx.session, ctx.mailbox, ctx.message, Outcome.HELD, reason="not_requester"
        )
    screened = await attachments.screen(ctx.session, ctx.message.attachments)
    language = await attachments.language_of(ctx.session, ctx.sender_id)
    replied = await ctx.target.reply_from_mail(
        ctx.session,
        found,
        author_id=ctx.sender_id,
        body_html=body_html(reply_text(ctx.message.text))
        + attachments.not_kept_html(screened.not_kept, language),
        automatic=False,
        message_id=ctx.message.message_id,
    )
    follow_up = replied.follow_up
    await _keep_files(
        ctx,
        screened,
        owner=(
            (OwnerType.CONVERSATION_ENTRY, replied.entry_id)
            if replied.entry_id is not None
            else (OwnerType.WORK_ITEM, (follow_up or found).record_id)
        ),
    )
    if follow_up is not None:
        # Too late to reopen: a new incident follows the closed one; the sender learns its ID,
        # and the token in the subject makes their next reply land on it (WP-020f, lane A).
        await _answer(
            ctx.session, settings, ctx.mailbox, ctx.message, "mailbox_answer.follow_up",
            person=ctx.sender_id, id=follow_up.display_id, previous=found.display_id,
        )  # fmt: skip
    record = follow_up or found
    return await _finish(
        ctx.session, ctx.mailbox, ctx.message, Outcome.REPLIED,
        record=(record.record_type, record.record_id), params=ctx.ledger_params(),
    )  # fmt: skip


async def _keep_files(
    ctx: _Context,
    screened: attachments.Screened,
    *,
    owner: tuple[OwnerType, uuid.UUID],
    person: uuid.UUID | None = None,
) -> None:
    """Store the screened attachments as the sender; a late refusal is noted on the ledger row."""
    sender = person or ctx.sender_id
    if sender is None or not screened.keep:
        return
    refused = await attachments.keep(
        ctx.session,
        ctx.settings,
        screened.keep,
        sender_id=sender,
        owner_type=owner[0],
        owner_id=owner[1],
    )
    if refused:
        ctx.not_kept.extend(refused)


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
    screened = await attachments.screen(ctx.session, ctx.message.attachments)
    language = await attachments.language_of(ctx.session, requester)
    created = await ctx.target.create_from_mail(
        ctx.session,
        requester_id=requester,
        subject=ctx.message.subject or _first_line(ctx.message.text),
        body_html=body_html(ctx.message.text)
        + attachments.not_kept_html(screened.not_kept, language),
        group_id=ctx.mailbox.group_id,
        message_id=ctx.message.message_id,
    )
    await _keep_files(
        ctx, screened, owner=(OwnerType.WORK_ITEM, created.record_id), person=requester
    )
    return await _finish(
        ctx.session, ctx.mailbox, ctx.message, Outcome.CREATED,
        record=(created.record_type, created.record_id), params=ctx.ledger_params(),
    )  # fmt: skip


async def _handle(  # noqa: PLR0913 - one return per outcome of the module docstring
    session: AsyncSession,
    settings: Settings,
    mailbox: Mailbox,
    message: InboundMessage,
    size: int,
    *,
    own_addresses: tuple[str, ...],
    vouched: bool = False,
) -> Outcome:
    """Decide and act on a claimed message; `vouched`: an admin released it (no flood check)."""
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
    recent = 0 if vouched else await _recent(session, message.sender) - 1  # minus this one
    decision = route(
        mailbox=_rules(mailbox),
        automatic=message.automatic,
        sender=message.sender,
        own_addresses=own_addresses,
        recent_from_sender=recent,
        answers_record=found is not None,
        sender_known=sender_id is not None,
        size=size,
    )
    if target is None:
        return await _finish(session, mailbox, message, Outcome.HELD, reason="no_target")
    ctx = _Context(session, settings, mailbox, message, target, sender_id)
    if decision.outcome is Outcome.AUTOMATIC and found is not None:
        return await _automatic(ctx, found, decision.reason)
    if decision.outcome not in (Outcome.CREATED, Outcome.REPLIED):
        if decision.reason == FLOOD and await _flood_starts(session, message):
            # Never silent (product owner, 2026-10-29): admins are told once per flood.
            await record_event(
                session,
                MailboxMailHeld(mailbox_id=mailbox.id, reason=FLOOD),
                aggregate_id=mailbox.id,
                aggregate_version=mailbox.version,
            )
        if decision.outcome is Outcome.REJECTED:
            await _answer(session, settings, mailbox, message, f"mailbox_answer.{decision.reason}")
        return await _finish(session, mailbox, message, decision.outcome, reason=decision.reason)
    try:
        if found is not None:
            return await _reply(ctx, settings, found)
        return await _create(ctx, create_requester=decision.create_requester)
    except InboundRefused as refused:
        return await _finish(
            session, mailbox, message, Outcome.HELD, reason=refused.code, params=refused.params
        )


async def _keep_while_held(
    session: AsyncSession, mailbox: Mailbox, message: InboundMessage, raw: bytes | None
) -> None:
    row = await session.get(MailFetched, (mailbox.tenant_id, mailbox.id, message.message_id[:500]))
    if row is not None:
        row.raw = raw if row.outcome == Outcome.HELD.value else None


async def process(
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
    outcome = await _handle(
        session, settings, mailbox, message, len(raw), own_addresses=own_addresses
    )
    await _keep_while_held(session, mailbox, message, raw)  # for the review queue
    return outcome


class NotWaiting(Conflict):
    """The message was released or discarded meanwhile, or cannot be released."""

    code = "mail_not_waiting"


async def release(  # noqa: PLR0913 - the message and who vouches for it, explicit
    session: AsyncSession,
    settings: Settings,
    mailbox: Mailbox,
    row: MailFetched,
    *,
    own_addresses: tuple[str, ...],
    admin_id: uuid.UUID,
) -> Outcome:
    """An admin hands a held message in again; held again (with the new reason) if it fails."""
    if not releasable(Outcome(row.outcome), row.reason):
        raise NotWaiting
    await session.refresh(row, ["raw"])  # deferred: only the message being released
    raw = row.raw
    if raw is None:
        raise NotWaiting
    message = parse(raw)
    outcome = await _handle(
        session, settings, mailbox, message, len(raw), own_addresses=own_addresses, vouched=True
    )
    row.handled_by = admin_id
    await _keep_while_held(session, mailbox, message, raw)
    return outcome


async def discard(row: MailFetched, *, admin_id: uuid.UUID) -> None:
    """An admin discards a waiting message: kept in the ledger as discarded, without its copy."""
    if Outcome(row.outcome) not in WAITING:
        raise NotWaiting
    row.outcome, row.raw, row.handled_by = Outcome.DISCARDED.value, None, admin_id
    row.updated_at = datetime.now(UTC)
