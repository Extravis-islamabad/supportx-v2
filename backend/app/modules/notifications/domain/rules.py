"""Notification rules, recipients and preferences: pure decisions, no I/O (REQ-NTF-008/009/016).

The engine asks, in this order, for every committed event:

1. is the event on for the tenant, and do the rule's conditions match the record?
2. who are the recipients (relative kinds resolved now, plus named people), once each?
3. for each person and channel: does their preference or do-not-disturb hold it back?

Each "no" has a reason code, written to the delivery log, so nothing is ever silently dropped.
"""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from app.shared.notifications.ports import EventDefault, NotificationChannel


class DeliveryState(StrEnum):
    """The state of one message to one person on one channel (REQ-NTF-020)."""

    QUEUED = "queued"  # handed to the channel, not yet confirmed
    WAITING = "waiting"  # the channel is not set up yet (no outgoing mail); sent once it is
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"  # deliberately not sent; the reason says why


class SuppressedReason(StrEnum):
    """Why a message was not sent; every one is shown in the delivery log."""

    NO_ACCESS = "no_access"  # the person may not see the record now (REQ-NTF-010)
    PREFERENCE = "preference"  # the person switched this event off for the channel
    DO_NOT_DISTURB = "do_not_disturb"
    NO_ADDRESS = "no_address"  # inactive person, or no e-mail address
    MAIL_REFUSED = "mail_refused"  # the mail foundation refused the message (bad address…)


class ConditionOperator(StrEnum):
    """How a rule condition tests a record value."""

    IN = "in"
    NOT_IN = "not_in"


@dataclass(frozen=True)
class Condition:
    """`field` (one the record type offers) is / is not one of `values`."""

    field: str
    operator: ConditionOperator
    values: tuple[str, ...]

    def matches(self, values: Mapping[str, str | None]) -> bool:
        """Whether the record's value of the field passes."""
        found = values.get(self.field) in self.values
        return found if self.operator is ConditionOperator.IN else not found


@dataclass(frozen=True)
class Rule:
    """A tenant's rule for one event (the shipped default until an admin saves one)."""

    enabled: bool
    recipients: tuple[str, ...]  # relative kinds
    channels: tuple[NotificationChannel, ...]
    user_ids: tuple[uuid.UUID, ...] = ()
    group_ids: tuple[uuid.UUID, ...] = ()
    conditions: tuple[Condition, ...] = ()
    notify_actor: bool = False  # people are not told about their own changes unless set

    @classmethod
    def from_default(cls, default: EventDefault) -> "Rule":
        """The rule an event ships with (no set-up step, REQ-NTF-008 AC1)."""
        return cls(default.enabled, default.recipients, default.channels)

    def applies(self, values: Mapping[str, str | None]) -> bool:
        """On, and every condition passes (REQ-NTF-008 AC2)."""
        return self.enabled and all(c.matches(values) for c in self.conditions)


@dataclass(frozen=True)
class Recipient:
    """One person to notify, and every path that reached them (for the log)."""

    user_id: uuid.UUID
    reasons: tuple[str, ...]  # recipient kinds or "user" / "group", in rule order


def recipients(
    rule: Rule,
    relatives: Mapping[str, frozenset[uuid.UUID]],
    group_members: Mapping[uuid.UUID, frozenset[uuid.UUID]],
    actor_id: uuid.UUID | None,
) -> list[Recipient]:
    """Everyone the rule reaches, once each (REQ-NTF-009 AC1), without the actor (AC3).

    Relative kinds and groups are resolved by the caller at send time, so a group's members are
    those of now, not of when the rule was saved (AC2).
    """
    reached: dict[uuid.UUID, list[str]] = {}

    def add(people: Iterable[uuid.UUID], reason: str) -> None:
        for person in sorted(people):
            paths = reached.setdefault(person, [])
            if reason not in paths:
                paths.append(reason)

    for kind in rule.recipients:
        add(relatives.get(kind, frozenset()), kind)
    add(rule.user_ids, "user")
    for group in rule.group_ids:
        add(group_members.get(group, frozenset()), "group")
    if actor_id is not None and not rule.notify_actor:
        reached.pop(actor_id, None)
    return [Recipient(user, tuple(paths)) for user, paths in reached.items()]


@dataclass(frozen=True)
class Preferences:
    """One person's choices (REQ-NTF-016, REQ-INC-131's do-not-disturb)."""

    # (category, channel) pairs switched off; everything else is on.
    off: frozenset[tuple[str, NotificationChannel]] = field(default_factory=frozenset)
    do_not_disturb: bool = False


def held_back(
    preferences: Preferences,
    *,
    category: str,
    channel: NotificationChannel,
    required: bool,
    urgent: bool,
) -> SuppressedReason | None:
    """Why the person's own settings hold this message back, or None to send it.

    Required events (approvals, assigned to me, mentions) cannot be switched off (AC2).
    Do-not-disturb holds back e-mail for events that are neither required nor urgent; in-app
    entries still land in the centre (the browser shows no pop-up while it is on).
    """
    if required:
        return None
    if (category, channel) in preferences.off:
        return SuppressedReason.PREFERENCE
    if preferences.do_not_disturb and channel is NotificationChannel.EMAIL and not urgent:
        return SuppressedReason.DO_NOT_DISTURB
    return None
