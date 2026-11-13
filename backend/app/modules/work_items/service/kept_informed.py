"""Mail to the people kept informed on a record (WP-046a S6; REQ-INC-066).

Each public reply on a record with addresses in `notify_emails` goes to each of them as its own
mail through the one mail sender. A durable consumer of `work_items.conversation.added` does it
(`KEPT_INFORMED`), after the reply is committed: never from the request, and an installation
without outgoing mail loses nothing but these mails. Private notes and automatic replies never go
(AC1).

Each mail carries its own stop link (lane B's conditions, see domain.kept_informed): a random
token whose SHA-256 alone is kept, bound to the tenant (RLS), the record and the address; single
use; it expires at the earliest limit. The link opens a page that asks first; only its button
stops the mails (POST /public/notify-links/stop), so a mail scanner that follows links changes
nothing. The address is masked wherever it is logged.
"""

import html
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import SESSION_TENANT_KEY
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.organization import email_branding, site_defaults
from app.modules.work_items.domain import kept_informed as rules
from app.modules.work_items.events import WorkItemUpdated
from app.modules.work_items.infra.models import WorkItem, WorkItemConversation, WorkItemNotifyLink
from app.shared.action_links.domain import digest_of, new_token, well_formed
from app.shared.events import ConsumerSpec, EventEnvelope, Handler, record_event
from app.shared.history import Change, record_changes
from app.shared.labels import LANGUAGES, plain_label
from app.shared.mail import Language, MailRefused, OutgoingMail, mail_configured, queue_mail
from app.shared.mail.domain.inbound import with_token

log = get_logger(__name__)
KIND = "kept_informed"  # the mail sender's kind for these mails
STOP_PATH = "stop-mails"  # the portal page that asks before stopping
EXCERPT_MAX = 4000  # characters of the reply in the mail


def _tenant(session: AsyncSession) -> uuid.UUID:
    context = session.info[SESSION_TENANT_KEY]
    if not isinstance(context, TenantContext):  # pragma: no cover - a tenant session always
        msg = "mail to people kept informed is sent in a tenant session"
        raise TypeError(msg)
    return context.tenant_id


def _plain(body: str) -> str:
    """The reply's sanitised HTML as plain text, cut to EXCERPT_MAX."""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", body)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()
    return text[:EXCERPT_MAX]


async def send_reply(
    session: AsyncSession, settings: Settings, record: WorkItem, entry: WorkItemConversation
) -> int:
    """Mail a public reply to each address kept informed; how many mails were queued."""
    if not record.notify_emails:
        return 0
    if not mail_configured(settings):
        log.info("kept_informed_no_mail", record_id=str(record.id))
        return 0
    tenant = _tenant(session)
    defaults = await site_defaults(session)
    language: Language = "en"
    for known in LANGUAGES:  # the tenant's default language, when it is one mail is sent in
        if defaults.language == known:
            language = known
    brand = await email_branding(session, settings, tenant, language)
    now = datetime.now(UTC)
    expires = rules.link_expiry(
        now,
        closed_at=record.closed_at,
        retention=timedelta(days=settings.mail_content_retention_days),
    )
    excerpt = _plain(entry.body)
    sent = 0
    for address in record.notify_emails:
        token = new_token()
        session.add(
            WorkItemNotifyLink(
                tenant_id=tenant,
                work_item_id=record.id,
                address=address,
                token_digest=token.digest,
                expires_at=expires,
            )
        )
        # The token in the fragment: browsers never send it, so no server log holds it.
        stop = f"{brand.portal_url.rstrip('/')}/{STOP_PATH}?t={brand.tenant_slug}#{token.secret}"
        subject = plain_label(
            "kept_informed.reply.subject", language, id=record.display_id, subject=record.subject
        )
        text = plain_label(
            "kept_informed.reply.body",
            language,
            id=record.display_id,
            subject=record.subject,
            reply=excerpt,
            stop=stop,
        )
        try:
            await queue_mail(
                session,
                settings,
                OutgoingMail(
                    kind=KIND,
                    to=(address,),
                    language=language,
                    subject=with_token(subject, record.display_id),
                    text=text,
                ),
            )
            sent += 1
        except MailRefused as refused:
            log.warning("kept_informed_refused", code=refused.code, to=rules.masked(address))
    await session.flush()
    return sent


class StopRefused(Exception):
    """Unknown, used, expired or another tenant's token: one answer for all (lane B)."""


async def _live_link(session: AsyncSession, secret: str) -> WorkItemNotifyLink:
    if not well_formed(secret):
        raise StopRefused
    link = await session.scalar(
        select(WorkItemNotifyLink).where(WorkItemNotifyLink.token_digest == digest_of(secret))
    )
    if link is None or link.used_at is not None or link.expires_at <= datetime.now(UTC):
        raise StopRefused
    return link


async def peek(session: AsyncSession, secret: str) -> tuple[str, str]:
    """What the stop page shows before asking: the record's ID and the masked address."""
    link = await _live_link(session, secret)
    record = await session.get(WorkItem, link.work_item_id)
    display = record.display_id if record is not None else ""
    return display, rules.masked(link.address)


async def stop(session: AsyncSession, secret: str) -> WorkItemNotifyLink:
    """The address is taken off the record's list and the link used, once.

    A change to the record like any other (CLAUDE.md rules b, g): a new version, a history line
    (source portal, by nobody signed in) and `work_item.updated` in the same transaction, so the
    record's screen follows live.
    """
    from app.modules.work_items.service import work_items as items  # noqa: PLC0415 - cycle

    link = await _live_link(session, secret)
    record = await session.get(WorkItem, link.work_item_id, with_for_update=True)
    link.used_at = datetime.now(UTC)
    if record is not None and link.address in record.notify_emails:
        before = list(record.notify_emails)
        audience = items.audience_of(record)
        record.notify_emails = [a for a in before if a != link.address]
        record.version += 1
        record.updated_at = link.used_at
        await session.flush()
        await record_changes(
            session,
            record_type=items.RECORD_TYPE,
            record_id=record.id,
            version=record.version,
            kind="updated",
            changes=[Change("notify_emails", before, list(record.notify_emails))],
            source="portal",
        )
        await record_event(
            session,
            WorkItemUpdated(
                work_item_id=record.id,
                type=record.type,
                display_id=record.display_id,
                status=record.status,
                status_category=record.status_category,
                changed_fields=["notify_emails"],
                audience_before=audience,
            ),
            aggregate_id=record.id,
            aggregate_version=record.version,
        )
    await session.flush()
    return link


# --- the consumer -------------------------------------------------------------------------------


async def on_conversation_added(
    envelope: EventEnvelope, session: AsyncSession, settings: Settings
) -> int:
    """A committed public reply (not an automatic one) goes to the people kept informed."""
    payload = envelope.payload
    if payload.get("kind") != "reply" or payload.get("visibility") != "public":
        return 0
    if payload.get("automatic"):
        return 0  # an out-of-office is no update for anyone
    entry = await session.get(WorkItemConversation, uuid.UUID(str(payload["entry_id"])))
    record = await session.get(WorkItem, uuid.UUID(str(payload["work_item_id"])))
    if entry is None or record is None or entry.deleted_at is not None:
        return 0
    return await send_reply(session, settings, record, entry)


def handler(settings: Callable[[], Settings] = get_settings) -> Handler:
    """The consumer's handler, reading settings when it runs (tests pass their own)."""

    async def handle(envelope: EventEnvelope, session: AsyncSession | None) -> None:
        assert session is not None  # noqa: S101 - transactional consumer
        await on_conversation_added(envelope, session, settings())

    return handle


KEPT_INFORMED = ConsumerSpec(
    name="work_items__kept_informed",
    event_types=("work_items.conversation.added",),
    handler=handler(),
)
