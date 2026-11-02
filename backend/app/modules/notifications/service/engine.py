"""The notification engine (WP-023; REQ-NTF-001, -003, -008, -009, -010, -014, -016, -020).

One consumer, `notifications__dispatch`, sees every committed domain event (a rolled-back change
never reaches it). For each notification event a record source raises:

1. the tenant's rule (or the shipped default) and its conditions;
2. recipients, resolved now and de-duplicated, without the person who made the change;
3. per person: may they still see the record (and how much of it), are they active, do their
   preferences hold the channel back;
4. per channel: an in-app entry (live on their personal channel), or an e-mail through the one
   mail sender, rendered in their language and zone with the tenant's brand.

Every message gets a delivery row with its state and reason, including those not sent: nothing
is dropped silently. With no outgoing mail set up, e-mails wait (rendered) and in-app entries go
out; the `notifications__mail_waiting` schedule hands the waiting ones over once mail works.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access import NotifiablePerson, notifiable_people
from app.modules.notifications.domain.rules import (
    Condition,
    ConditionOperator,
    DeliveryState,
    Preferences,
    Recipient,
    Rule,
    SuppressedReason,
    held_back,
    recipients,
)
from app.modules.notifications.domain.templates import Rendered, html_body, render
from app.modules.notifications.events import DeliveryRecorded, NotificationCreated
from app.modules.notifications.infra.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationRule,
)
from app.modules.organization import email_branding, site_defaults, users_in_groups
from app.shared.events import Actor, ConsumerSpec, EventEnvelope, Handler, record_event
from app.shared.labels import label
from app.shared.mail import (
    Language,
    MailRefused,
    OutgoingMail,
    mail_configured,
    queue_mail,
    with_token,
    wrap_html,
)
from app.shared.mail.events import MailStateChanged
from app.shared.notifications.ports import (
    DeliveryChange,
    LabelRef,
    Localised,
    NotificationChannel,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    RecordSource,
    VariableValue,
    find_event,
    record_source,
    record_sources,
)

log = get_logger(__name__)
LANGUAGES: tuple[Language, ...] = ("en", "ar", "ur")
WAITING_BATCH = 200
# An e-mail that waited this long for outgoing mail is never sent late (REQ-INC-060; D-116).
WAITING_DAYS = 7
NOT_SENT_IN_TIME = "not_sent_in_time"
REQUESTER = "requester"  # the recipient kind whose e-mail a reply's delivery state follows


# --- rules and preferences -------------------------------------------------------------------


def rule_of(row: NotificationRule) -> Rule:
    """A saved rule as the domain sees it."""
    return Rule(
        enabled=row.enabled,
        recipients=tuple(row.recipients),
        channels=tuple(NotificationChannel(c) for c in row.channels),
        user_ids=tuple(row.user_ids),
        group_ids=tuple(row.group_ids),
        conditions=tuple(
            Condition(
                str(c["field"]),
                ConditionOperator(str(c["operator"])),
                tuple(str(v) for v in c["values"]),  # type: ignore[attr-defined]  # JSON list
            )
            for c in row.conditions
        ),
        notify_actor=row.notify_actor,
    )


async def rule_for(session: AsyncSession, event: NotificationEvent) -> Rule:
    """The tenant's rule for the event, else its shipped default (no set-up step)."""
    row = await session.scalar(
        select(NotificationRule).where(
            NotificationRule.event_code == event.code, NotificationRule.deleted_at.is_(None)
        )
    )
    return Rule.from_default(event.default) if row is None else rule_of(row)


async def preferences_of(
    session: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Preferences]:
    """Each person's preferences; people with no row have the defaults."""
    rows = await session.scalars(
        select(NotificationPreference).where(NotificationPreference.user_id.in_(list(user_ids)))
    )
    return {
        row.user_id: Preferences(
            off=frozenset((str(c), NotificationChannel(str(ch))) for c, ch in row.off),
            do_not_disturb=row.do_not_disturb,
        )
        for row in rows
    }


async def _group_members(
    session: AsyncSession, group_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, frozenset[uuid.UUID]]:
    members: dict[uuid.UUID, frozenset[uuid.UUID]] = {}
    for group in group_ids:
        members[group] = frozenset(await session.scalars(users_in_groups(frozenset({group}))))
    return members


# --- rendering -------------------------------------------------------------------------------


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def localise(value: VariableValue, language: Language, zone: ZoneInfo) -> str | None:  # noqa: PLR0911 - one return per kind of value
    """A variable's value as the recipient reads it."""
    if value is None:
        return None
    if isinstance(value, LabelRef):
        return label(value.key, language)
    if isinstance(value, Localised):
        own = value.texts.get(language)
        if own:
            return own
        if value.fallback is not None:
            return label(value.fallback, language)
        return value.texts.get("en")
    if isinstance(value, datetime):
        return value.astimezone(zone).strftime("%Y-%m-%d %H:%M")
    return str(value)


def _template(code: str, part: str, language: Language) -> str:
    # The shipped defaults are labels (en, ar, ur); their {{ variables }} are Jinja2's.
    return label(f"notification_template.{code}.{part}", language)


@dataclass(frozen=True)
class Message:
    """One rendered notification for one person."""

    language: Language
    in_app: str
    email: Rendered
    link: str  # absolute, for e-mail
    path: str  # console path, for the centre


def compose(  # noqa: PLR0913 - the event, the record, the person and their reading of it
    code: str,
    *,
    context: RecordContext,
    access: RecordAccess,
    person: NotifiablePerson,
    language: Language,
    zone: ZoneInfo,
    origin: Callable[[RecordAccess], str],
    offered: frozenset[str] = frozenset(),
) -> Message:
    """The message in the person's language, from the content they may see (REQ-NTF-010)."""
    chosen = context.variables if access is RecordAccess.FULL else context.public_variables
    # Every offered variable exists, empty when this reader may not see it or it has no value.
    values: dict[str, str | None] = dict.fromkeys(offered)
    values.update({name: localise(value, language, zone) for name, value in chosen.items()})
    base = origin(access)
    link = base + context.link.lstrip("/") if access is RecordAccess.FULL else base
    values["record.link"] = link
    values["recipient.name"] = person.name
    in_app = render(_template(code, "in_app", language), "", values).subject
    email = render(_template(code, "subject", language), _template(code, "body", language), values)
    return Message(language, in_app, email, link, context.link)


# --- delivery --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One notification event for one person: what every delivery row of it shares."""

    envelope: EventEnvelope
    code: str
    source: RecordSource
    context: RecordContext
    recipient: Recipient


async def _record(  # noqa: PLR0913 - one delivery row, explicit
    session: AsyncSession,
    target: Target,
    channel: NotificationChannel,
    state: DeliveryState,
    *,
    reason: str | None = None,
    language: str | None = None,
    notification_id: uuid.UUID | None = None,
    mail_id: uuid.UUID | None = None,
    waiting: Rendered | None = None,
    html: str | None = None,
) -> NotificationDelivery:
    envelope, code, source, context, recipient = (
        target.envelope,
        target.code,
        target.source,
        target.context,
        target.recipient,
    )
    delivery = NotificationDelivery(
        tenant_id=envelope.tenant_id,
        event_id=envelope.event_id,
        event_code=code,
        record_type=source.record_type,
        record_id=context.record_id,
        display_id=context.display_id,
        user_id=recipient.user_id,
        reasons=list(recipient.reasons),
        channel=channel.value,
        state=state.value,
        reason=reason,
        language=language,
        notification_id=notification_id,
        mail_id=mail_id,
        entry_id=context.entry_id if channel is NotificationChannel.EMAIL else None,
        subject=waiting.subject if waiting else None,
        text_body=waiting.body if waiting else None,
        html_body=html if waiting else None,
    )
    session.add(delivery)
    await session.flush()
    if delivery.entry_id is not None and REQUESTER in recipient.reasons:
        moved = _entry_state(state, reason)
        if moved is not None:
            await entry_changed(
                session, source, delivery, state=moved[0], reason=moved[1], at=datetime.now(UTC)
            )
    await record_event(
        session,
        DeliveryRecorded(
            delivery_id=delivery.id,
            record_type=source.record_type,
            record_id=context.record_id,
            channel=channel.value,
            state=state.value,
        ),
        aggregate_id=delivery.id,
        actor=Actor.system("notifications"),
        causation_id=envelope.event_id,
    )
    return delivery


def _text_with_link(message: Message, open_text: str) -> str:
    return f"{message.email.body}\n\n{open_text}: {message.link}"


async def _email(
    session: AsyncSession,
    settings: Settings,
    target: Target,
    person: NotifiablePerson,
    message: Message,
) -> None:
    tenant, context, code = target.envelope.tenant_id, target.context, target.code
    # The record's token in the subject: a reply finds its record (REQ-NTF-002, WP-024).
    subject = with_token(message.email.subject, context.display_id)
    brand = await email_branding(session, settings, tenant, message.language)
    open_text = label("notification.open_record", message.language, id=context.display_id)
    content = html_body(
        message.email.body, link=message.link, link_text=open_text, colour=brand.primary_colour
    )
    html = wrap_html(content, brand=brand, language=message.language, title=subject)
    plain = _text_with_link(message, open_text)
    common = (session, target, NotificationChannel.EMAIL)
    if not mail_configured(settings):
        waiting = Rendered(subject, plain)
        await _record(
            *common, DeliveryState.WAITING, language=message.language, waiting=waiting, html=html
        )
        return
    if person.email is None:  # checked by the caller; kept for the type checker
        return
    try:
        mail_id = await queue_mail(
            session,
            settings,
            OutgoingMail(
                kind="notification",
                to=(person.email,),
                language=message.language,
                subject=subject,
                text=plain,
                html=html,
                sender_name=brand.product_name,
            ),
        )
    except MailRefused as refused:
        log.warning("notification_mail_refused", code=refused.code, event_code=code)
        await _record(*common, DeliveryState.SUPPRESSED, reason=SuppressedReason.MAIL_REFUSED)
        return
    await _record(*common, DeliveryState.QUEUED, language=message.language, mail_id=mail_id)


def _entry_state(state: DeliveryState, reason: str | None) -> tuple[str, str | None] | None:
    """The reply's delivery state for a requester e-mail's first state (None: no change)."""
    if state is DeliveryState.WAITING:
        return "waiting", "mail_not_configured"
    if state is DeliveryState.QUEUED:
        return "queued", None
    if state is DeliveryState.SUPPRESSED:
        known = {SuppressedReason.NO_ADDRESS.value, SuppressedReason.MAIL_REFUSED.value}
        return "failed", reason if reason in known else "not_notified"
    return None


async def entry_changed(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    source: RecordSource,
    delivery: NotificationDelivery,
    *,
    state: str,
    reason: str | None,
    at: datetime,
) -> None:
    """Tell the record's module how the e-mail carrying one of its entries went (REQ-INC-059)."""
    hook = getattr(source, "delivery_changed", None)
    if hook is None or delivery.entry_id is None:
        return
    await cast("DeliveryChange", source).delivery_changed(
        session,
        record_id=delivery.record_id,
        entry_id=delivery.entry_id,
        state=state,
        reason=reason,
        at=at,
    )


async def mail_changed(session: AsyncSession, envelope: EventEnvelope) -> int:
    """A send attempt ended: the delivery log and the carried entry follow; how many rows."""
    payload = envelope.payload
    mail_id = uuid.UUID(str(payload["mail_id"]))
    state, failure = str(payload["state"]), payload.get("failure")
    at = datetime.fromisoformat(str(payload["at"]))
    rows = list(
        await session.scalars(
            select(NotificationDelivery).where(NotificationDelivery.mail_id == mail_id)
        )
    )
    for row in rows:
        if state == "sent":
            row.state, row.reason = DeliveryState.SENT.value, None
        elif state == "failed":
            row.state, row.reason = DeliveryState.FAILED.value, str(failure or "gave_up")
        row.updated_at = datetime.now(UTC)
        if row.entry_id is not None and REQUESTER in row.reasons:
            await entry_changed(
                session,
                record_source(row.record_type),
                row,
                state=state,
                reason=None if state == "sent" else str(failure or "gave_up"),
                at=at,
            )
    return len(rows)


async def _in_app(session: AsyncSession, target: Target, message: Message) -> None:
    envelope, code, context, recipient = (
        target.envelope,
        target.code,
        target.context,
        target.recipient,
    )
    entry = Notification(
        tenant_id=envelope.tenant_id,
        user_id=recipient.user_id,
        event_code=code,
        record_type=target.source.record_type,
        record_id=context.record_id,
        display_id=context.display_id,
        title=message.in_app[:300],
        link=message.path,
        urgent=context.urgent,
    )
    session.add(entry)
    await session.flush()
    await record_event(
        session,
        NotificationCreated(
            notification_id=entry.id, user_id=recipient.user_id, urgent=context.urgent
        ),
        aggregate_id=entry.id,
        actor=Actor.system("notifications"),
        causation_id=envelope.event_id,
    )
    await _record(
        session,
        target,
        NotificationChannel.IN_APP,
        DeliveryState.SENT,
        language=message.language,
        notification_id=entry.id,
    )


def _actor_id(envelope: EventEnvelope) -> uuid.UUID | None:
    if envelope.actor.type != "user":
        return None
    try:
        return uuid.UUID(envelope.actor.id)
    except ValueError:
        return None


def _language(person: NotifiablePerson, site: str | None) -> Language:
    if person.language is not None:
        return person.language
    return site if site in LANGUAGES else "en"


async def notify(  # noqa: C901 - the pipeline of one event, in order
    session: AsyncSession,
    settings: Settings,
    source: RecordSource,
    code: str,
    envelope: EventEnvelope,
) -> int:
    """Send one notification event to everyone its rule reaches; how many deliveries."""
    context = await source.context(session, code, envelope)
    if context is None:
        return 0
    code = context.event_code or code
    _, event = find_event(code)
    rule = await rule_for(session, event)
    if not rule.applies(context.conditions):
        return 0
    people = recipients(
        rule, context.relatives, await _group_members(session, rule.group_ids), _actor_id(envelope)
    )
    if not people:
        return 0
    ids = [p.user_id for p in people]
    details = await notifiable_people(session, ids)
    preferences = await preferences_of(session, ids)
    defaults = await site_defaults(session)
    brand_urls: dict[str, tuple[str, str]] = {}

    async def origin_for(language: Language) -> Callable[[RecordAccess], str]:
        if language not in brand_urls:
            brand = await email_branding(session, settings, envelope.tenant_id, language)
            brand_urls[language] = (brand.console_url, brand.portal_url)
        console, portal = brand_urls[language]
        return lambda access: console if access is RecordAccess.FULL else portal

    count = 0
    for recipient in people:
        person = details.get(recipient.user_id)
        access = (
            RecordAccess.NONE
            if person is None
            else await source.access(session, recipient.user_id, context.record_id)
        )
        message: Message | None = None
        target = Target(envelope, code, source, context, recipient)
        for channel in rule.channels:
            count += 1
            common = (session, target, channel)
            if person is None:
                await _record(*common, DeliveryState.SUPPRESSED, reason=SuppressedReason.NO_ADDRESS)
                continue
            if access is RecordAccess.NONE or (access is RecordAccess.PUBLIC and not event.public):
                await _record(*common, DeliveryState.SUPPRESSED, reason=SuppressedReason.NO_ACCESS)
                continue
            held = held_back(
                preferences.get(recipient.user_id, Preferences()),
                category=event.category.value,
                channel=channel,
                required=event.required,
                urgent=context.urgent,
            )
            if held is not None:
                await _record(*common, DeliveryState.SUPPRESSED, reason=held)
                continue
            if channel is NotificationChannel.EMAIL and not person.email:
                await _record(*common, DeliveryState.SUPPRESSED, reason=SuppressedReason.NO_ADDRESS)
                continue
            if message is None:
                language = _language(person, defaults.language)
                zone = _zone(person.time_zone or defaults.time_zone)
                message = compose(
                    code,
                    context=context,
                    access=access,
                    person=person,
                    language=language,
                    zone=zone,
                    origin=await origin_for(language),
                    offered=frozenset(v.name for v in (*source.variables, *event.variables)),
                )
            if channel is NotificationChannel.IN_APP:
                await _in_app(session, target, message)
            else:
                await _email(session, settings, target, person, message)
    return count


async def dispatch(session: AsyncSession, settings: Settings, envelope: EventEnvelope) -> int:
    """Every notification a committed domain event raises; how many deliveries."""
    if envelope.event_type == MailStateChanged.event_type:
        await mail_changed(session, envelope)
        return 0
    total = 0
    for source in record_sources():
        if envelope.event_type in source.event_types:
            for code in source.events_for(envelope):
                total += await notify(session, settings, source, code, envelope)
    return total


def accepts(envelope: EventEnvelope) -> bool:
    """Whether any record source reads this event type, or it is a send attempt's end."""
    if envelope.event_type == MailStateChanged.event_type:
        return True
    return any(envelope.event_type in source.event_types for source in record_sources())


def handler(settings: Callable[[], Settings] = get_settings) -> Handler:
    """The consumer's handler, reading settings when it runs (tests pass their own)."""

    async def handle(envelope: EventEnvelope, session: AsyncSession | None) -> None:
        assert session is not None  # noqa: S101 - transactional consumer
        await dispatch(session, settings(), envelope)

    return handle


DISPATCH = ConsumerSpec(
    name="notifications__dispatch",
    # Every module's events: record sources say at run time which they read (REQ-NTF-001 AC1).
    event_types=(">",),
    handler=handler(),
    deliver_from="new",
    accepts=accepts,
)


# --- e-mails waiting for outgoing mail ------------------------------------------------------


async def send_waiting(session: AsyncSession, settings: Settings) -> int:
    """Hand waiting e-mails to the mail sender, checking access and address again; how many."""
    if not mail_configured(settings):
        return 0
    rows = list(
        await session.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.state == DeliveryState.WAITING.value)
            .order_by(NotificationDelivery.created_at)
            .limit(WAITING_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    if not rows:
        return 0
    details = await notifiable_people(session, [r.user_id for r in rows if r.user_id])
    sent = 0
    for row in rows:
        person = details.get(row.user_id) if row.user_id else None
        access = RecordAccess.NONE
        if person is not None and row.user_id is not None:
            access = await record_source(row.record_type).access(
                session, row.user_id, row.record_id
            )
        if person is None or not person.email:
            row.state, row.reason = DeliveryState.SUPPRESSED.value, SuppressedReason.NO_ADDRESS
        elif access is RecordAccess.NONE:
            row.state, row.reason = DeliveryState.SUPPRESSED.value, SuppressedReason.NO_ACCESS
        else:
            language: Language = row.language if row.language in LANGUAGES else "en"
            try:
                row.mail_id = await queue_mail(
                    session,
                    settings,
                    OutgoingMail(
                        kind="notification",
                        to=(person.email,),
                        language=language,
                        subject=row.subject or row.display_id,
                        text=row.text_body or "",
                        html=row.html_body,
                    ),
                )
                row.state = DeliveryState.QUEUED.value
                sent += 1
            except MailRefused:
                row.state = DeliveryState.SUPPRESSED.value
                row.reason = SuppressedReason.MAIL_REFUSED
        row.subject = row.text_body = row.html_body = None
        row.updated_at = datetime.now(UTC)
    return sent


async def expire_waiting(
    session: AsyncSession, now: datetime | None = None, *, retention_days: int = 30
) -> int:
    """E-mails that waited `WAITING_DAYS` for outgoing mail fail, visibly; never sent late.

    Their rendered text stays for a resend (REQ-INC-059 AC3) until the mail retention period
    (`mail_content_retention_days`) has passed, like any other sent or failed e-mail.
    """
    moment = now or datetime.now(UTC)
    await session.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.state == DeliveryState.FAILED.value,
            NotificationDelivery.reason == NOT_SENT_IN_TIME,
            NotificationDelivery.text_body.is_not(None),
            NotificationDelivery.updated_at < moment - timedelta(days=retention_days),
        )
        .values(subject=None, text_body=None, html_body=None)
    )
    rows = list(
        await session.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.state == DeliveryState.WAITING.value,
                NotificationDelivery.created_at < moment - timedelta(days=WAITING_DAYS),
            )
            .limit(WAITING_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        row.state, row.reason = DeliveryState.FAILED.value, NOT_SENT_IN_TIME
        row.updated_at = moment
        if row.entry_id is not None and REQUESTER in row.reasons:
            await entry_changed(
                session,
                record_source(row.record_type),
                row,
                state="failed",
                reason=NOT_SENT_IN_TIME,
                at=moment,
            )
    return len(rows)


async def waiting_schedule(database: Database, settings: Settings) -> None:
    """Every minute: give up on what waited too long, then (mail set up) send what waited."""
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    configured = mail_configured(settings)
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            expired = await expire_waiting(
                session, retention_days=settings.mail_content_retention_days
            )
            sent = await send_waiting(session, settings) if configured else 0
        if sent or expired:
            log.info("notifications_waiting", tenant_id=str(tenant), sent=sent, expired=expired)


async def waiting_count(session: AsyncSession) -> int:
    """E-mails waiting for outgoing mail (the admins' banner, REQ-NTF-020 AC3)."""
    from sqlalchemy import func  # noqa: PLC0415 - one query, kept beside its use

    return int(
        await session.scalar(
            select(func.count())
            .select_from(NotificationDelivery)
            .where(NotificationDelivery.state == DeliveryState.WAITING.value)
        )
        or 0
    )


__all__ = [
    "DISPATCH",
    "Message",
    "accepts",
    "compose",
    "dispatch",
    "expire_waiting",
    "localise",
    "mail_changed",
    "notify",
    "rule_for",
    "send_waiting",
    "waiting_count",
    "waiting_schedule",
]
