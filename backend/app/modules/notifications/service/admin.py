"""Notification rules per event, and the delivery log (REQ-NTF-008, -020; REQ-INC-134).

Rules: every event every module registered, with the shipped default until an admin saves a
rule (no set-up step, REQ-NTF-008 AC1). Saving uses the rule's version (0 for an event that
still has its default) so two admins never overwrite each other; "reset" goes back to the
default. Every change is audited by the route and recorded as `notifications.rule.changed`.

Delivery log: the rows of one record, for people who may see the record in full (staff); the
e-mail state is read live from the mail sender (sent, failed with the reason).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.identity_access import Subject, user_names
from app.modules.notifications.domain.rules import (
    ConditionOperator,
    DeliveryState,
    Rule,
)
from app.modules.notifications.events import RuleChanged
from app.modules.notifications.infra.models import NotificationDelivery, NotificationRule
from app.modules.notifications.service.engine import rule_of
from app.shared.events import record_event
from app.shared.mail import mail_states
from app.shared.notifications.ports import (
    NotificationChannel,
    NotificationEvent,
    RecordAccess,
    RecordSource,
    UnknownRecordTypeError,
    find_event,
    record_source,
    record_sources,
)

MANAGE = "notifications.manage"
NAMED_MAX = 50
CONDITIONS_MAX = 10
LOG_MAX = 200


@dataclass(frozen=True)
class RuleView:
    """One event with its rule as it applies now."""

    source: RecordSource
    event: NotificationEvent
    rule: Rule
    version: int  # 0: the shipped default applies
    updated_at: datetime | None
    updated_by: uuid.UUID | None


def _event(code: str) -> tuple[RecordSource, NotificationEvent]:
    try:
        return find_event(code)
    except (KeyError, UnknownRecordTypeError):
        raise NotFound(code="notification_event_not_found") from None


async def _row(session: AsyncSession, code: str, *, lock: bool = False) -> NotificationRule | None:
    query = select(NotificationRule).where(
        NotificationRule.event_code == code, NotificationRule.deleted_at.is_(None)
    )
    return await session.scalar(query.with_for_update() if lock else query)


def _view(source: RecordSource, event: NotificationEvent, row: NotificationRule | None) -> RuleView:
    if row is None:
        return RuleView(source, event, Rule.from_default(event.default), 0, None, None)
    return RuleView(source, event, rule_of(row), row.version, row.updated_at, row.updated_by)


async def rules(session: AsyncSession) -> list[RuleView]:
    """Every registered event, by record type, in each module's order."""
    saved = {
        row.event_code: row
        for row in await session.scalars(
            select(NotificationRule).where(NotificationRule.deleted_at.is_(None))
        )
    }
    return [
        _view(source, event, saved.get(event.code))
        for source in record_sources()
        for event in source.events
    ]


async def rule(session: AsyncSession, code: str) -> RuleView:
    """One event's rule."""
    source, event = _event(code)
    return _view(source, event, await _row(session, code))


def _check(source: RecordSource, wanted: Rule) -> list[FieldError]:
    """Field problems of a rule, every code written out (tests/test_error_labels.py)."""
    errors: list[FieldError] = []
    for i, kind in enumerate(wanted.recipients):
        if kind not in source.recipient_kinds:
            errors.append(
                FieldError(
                    field=f"body.recipients[{i}]",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            )
    if len(wanted.user_ids) > NAMED_MAX or len(wanted.group_ids) > NAMED_MAX:
        errors.append(
            FieldError(
                field="body.user_ids",
                code="too_many",
                message_key="errors.field.too_many",
                params={"max": NAMED_MAX},
            )
        )
    if len(wanted.conditions) > CONDITIONS_MAX:
        errors.append(
            FieldError(
                field="body.conditions",
                code="too_many_conditions",
                message_key="errors.field.too_many_conditions",
                params={"max": CONDITIONS_MAX},
            )
        )
    for i, condition in enumerate(wanted.conditions):
        if condition.field not in source.conditions or not condition.values:
            errors.append(
                FieldError(
                    field=f"body.conditions[{i}]",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            )
    if wanted.enabled and not wanted.channels:
        errors.append(
            FieldError(field="body.channels", code="required", message_key="errors.field.required")
        )
    if wanted.enabled and not (wanted.recipients or wanted.user_ids or wanted.group_ids):
        errors.append(
            FieldError(
                field="body.recipients", code="required", message_key="errors.field.required"
            )
        )
    return errors


def _changed(before: Rule, after: Rule) -> list[str]:
    names = (
        "enabled",
        "recipients",
        "channels",
        "user_ids",
        "group_ids",
        "conditions",
        "notify_actor",
    )
    return [name for name in names if getattr(before, name) != getattr(after, name)]


async def save_rule(
    session: AsyncSession,
    subject: Subject,
    code: str,
    wanted: Rule,
    *,
    expected_version: int,
) -> RuleView:
    """Replace an event's rule (If-Match: 0 while the default applies)."""
    source, event = _event(code)
    if errors := _check(source, wanted):
        raise ValidationFailed(errors=errors)
    row = await _row(session, code, lock=True)
    current = 0 if row is None else row.version
    if current != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current},
        )
    before = Rule.from_default(event.default) if row is None else rule_of(row)
    changed = _changed(before, wanted)
    if not changed and row is not None:
        return _view(source, event, row)
    if row is None:
        row = NotificationRule(
            tenant_id=subject.tenant_id, event_code=code, created_by=subject.user_id, version=1
        )
        session.add(row)
    else:
        row.version += 1
    row.enabled = wanted.enabled
    row.recipients = list(wanted.recipients)
    row.channels = [c.value for c in wanted.channels]
    row.user_ids = list(wanted.user_ids)
    row.group_ids = list(wanted.group_ids)
    row.conditions = [
        {"field": c.field, "operator": c.operator.value, "values": list(c.values)}
        for c in wanted.conditions
    ]
    row.notify_actor = wanted.notify_actor
    row.updated_by = subject.user_id
    row.updated_at = datetime.now(UTC)
    await session.flush()
    await record_event(
        session, RuleChanged(event_code=code, changed_fields=changed), aggregate_id=row.id
    )
    return _view(source, event, row)


async def reset_rule(
    session: AsyncSession, subject: Subject, code: str, *, expected_version: int
) -> RuleView:
    """Back to the shipped default (the saved rule is soft-deleted, kept for history)."""
    source, event = _event(code)
    row = await _row(session, code, lock=True)
    if row is None:
        return _view(source, event, None)
    if row.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": row.version},
        )
    changed = _changed(rule_of(row), Rule.from_default(event.default))
    now = datetime.now(UTC)
    row.deleted_at, row.updated_at, row.updated_by = now, now, subject.user_id
    # The unique key is per event: a reset rule gives its key back for the next save.
    row.event_code = f"{code}#{row.id}"[:80]
    await session.flush()
    await record_event(
        session,
        RuleChanged(event_code=code, changed_fields=changed or ["enabled"]),
        aggregate_id=row.id,
    )
    return _view(source, event, None)


def parse_rule(  # noqa: PLR0913 - the rule's fields, explicit
    *,
    enabled: bool,
    recipients: Sequence[str],
    channels: Sequence[str],
    user_ids: Sequence[uuid.UUID],
    group_ids: Sequence[uuid.UUID],
    conditions: Sequence[Mapping[str, object]],
    notify_actor: bool,
) -> Rule:
    """A rule from request fields (codes already checked by the request schema)."""
    from app.modules.notifications.domain.rules import Condition  # noqa: PLC0415 - one use

    return Rule(
        enabled=enabled,
        recipients=tuple(dict.fromkeys(recipients)),
        channels=tuple(dict.fromkeys(NotificationChannel(c) for c in channels)),
        user_ids=tuple(dict.fromkeys(user_ids)),
        group_ids=tuple(dict.fromkeys(group_ids)),
        conditions=tuple(
            Condition(
                str(c["field"]),
                ConditionOperator(str(c["operator"])),
                tuple(str(v) for v in c["values"]),  # type: ignore[attr-defined]  # a list
            )
            for c in conditions
        ),
        notify_actor=notify_actor,
    )


# --- delivery log ----------------------------------------------------------------------------


@dataclass(frozen=True)
class LogEntry:
    """One delivery as the record's log shows it."""

    row: NotificationDelivery
    state: str  # the mail sender's state for e-mails, else the delivery's
    reason: str | None
    recipient_name: str | None


async def delivery_log(
    session: AsyncSession, subject: Subject, record_type: str, record_id: uuid.UUID
) -> list[LogEntry]:
    """The record's notifications, newest first, for people who may see the record in full."""
    try:
        source = record_source(record_type)
    except UnknownRecordTypeError:
        raise NotFound(code="notification_record_not_found") from None
    if await source.access(session, subject.user_id, record_id) is not RecordAccess.FULL:
        raise NotFound(code="notification_record_not_found")
    rows = list(
        await session.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.record_type == record_type,
                NotificationDelivery.record_id == record_id,
            )
            .order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc())
            .limit(LOG_MAX)
        )
    )
    mails = await mail_states(session, [r.mail_id for r in rows if r.mail_id is not None])
    names = await user_names(session, [str(r.user_id) for r in rows if r.user_id])
    entries: list[LogEntry] = []
    for row in rows:
        state, reason = row.state, row.reason
        mail = mails.get(row.mail_id) if row.mail_id else None
        if mail is not None and row.state == DeliveryState.QUEUED.value:
            state, reason = mail.state, mail.failure
        entries.append(
            LogEntry(row, state, reason, names.get(str(row.user_id)) if row.user_id else None)
        )
    return entries
