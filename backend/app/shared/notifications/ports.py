"""The notifications port (WP-023, REQ-NTF-001).

A module whose records notify people registers a `RecordSource` here; the notifications module
does the rest: rules, recipients, access, preferences, templates, channels and the delivery log.
Modules never send mail or in-app messages themselves (an architecture test checks it).

The source answers three questions, always with the owning module's own rules:

- `events_for(envelope)`: which notification events a committed domain event raises (one change
  can raise several, e.g. a public reply that also mentions someone);
- `context(...)`: the record's variables for templates, in two cuts (everything, and public
  content only, for people who may see only the public side such as requesters), the people
  relative to the record (requester, assignee, followers…) and the values rules may test;
- `access(...)`: what one person may see of the record now, at send time (REQ-NTF-010).

Registered at import time of the owning module, so the API and the workers both have it.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.action_links.domain import LinkRequest
from app.shared.events import EventEnvelope


class NotificationChannel(StrEnum):
    """How a notification reaches a person."""

    IN_APP = "in_app"
    EMAIL = "email"


class RecordAccess(StrEnum):
    """What a person may see of a record when a notification about it is sent."""

    NONE = "none"  # gets nothing; the delivery log says why
    PUBLIC = "public"  # public content only (requesters): never private notes or internal fields
    FULL = "full"


class NotificationCategory(StrEnum):
    """Groups events for personal preferences (REQ-NTF-016)."""

    CREATED = "created"
    ASSIGNMENT = "assignment"
    CONVERSATION = "conversation"
    STATUS = "status"
    MENTION = "mention"
    FOLLOWING = "following"
    APPROVAL = "approval"  # WP-030 s3: an approval waits for you (required: never switched off)
    WORKFLOW = "workflow"  # WP-048b S2: a workflow's notify node (people may mute it)


@dataclass(frozen=True)
class LabelRef:
    """A variable value shown through the shared labels, in each recipient's language."""

    key: str  # e.g. "priority.p1"


@dataclass(frozen=True)
class Localised:
    """A variable value an admin wrote per language (status names…): {"en": "...", "ar": ...}."""

    texts: Mapping[str, str]
    fallback: str | None = None  # label key when the admin wrote nothing for the language


# What a variable may hold. Datetimes are shown in the recipient's zone and language.
VariableValue = str | int | LabelRef | Localised | datetime | None


@dataclass(frozen=True)
class Variable:
    """A template variable, offered in the editor's picker under its object (REQ-NTF-011)."""

    name: str  # dotted path in the template, e.g. "record.title"
    label: str  # label key shown in the picker


@dataclass(frozen=True)
class EventDefault:
    """The shipped rule of an event (Appendix A); tenants change it, never the code."""

    enabled: bool
    recipients: tuple[str, ...]  # relative recipient kinds, e.g. ("requester",)
    channels: tuple[NotificationChannel, ...] = (
        NotificationChannel.IN_APP,
        NotificationChannel.EMAIL,
    )
    # The person who did it is told too: an acknowledgement of one's own request (QA10).
    notify_actor: bool = False


@dataclass(frozen=True)
class NotificationEvent:
    """One kind of notification a record type can raise."""

    code: str  # "<record_type>.<event>", e.g. "incident.assigned"
    category: NotificationCategory
    default: EventDefault
    required: bool = False  # people cannot switch it off (approvals, assigned to me, mentions)
    # Admins cannot change or reset the rule either: the shipped default always applies (a
    # security notice the person must get even when an admin, maybe the attacker, would rather
    # they did not; WP-057 S2b, break-glass).
    locked: bool = False
    # False: only for people who see the record in full (a private note); anyone else gets
    # nothing, not even word that it happened (REQ-NTF-010).
    public: bool = True
    # Template variables beyond the record type's own (e.g. the conversation excerpt).
    variables: tuple[Variable, ...] = ()


@dataclass(frozen=True)
class RecordContext:
    """A record, as notifications see it at send time."""

    record_id: uuid.UUID
    display_id: str
    link: str  # path in the console, e.g. "/incidents/<id>"
    variables: Mapping[str, VariableValue]  # full content, for people with FULL access
    public_variables: Mapping[str, VariableValue]  # public content only, for PUBLIC access
    relatives: Mapping[str, frozenset[uuid.UUID]]  # recipient kind -> people, resolved now
    conditions: Mapping[str, str | None]  # values rules may test, e.g. {"priority": "p1"}
    urgent: bool = False  # never held for a digest or combined (Appendix A)
    # Changed field names (updates), so the message can say what changed.
    changed_fields: tuple[str, ...] = field(default_factory=tuple)
    # The event actually raised when only the record can tell (a public reply written by the
    # requester is "requester replied"); None keeps the code `events_for` gave.
    event_code: str | None = None
    # The part of the record the message carries (a reply's conversation entry): the source's
    # `delivery_changed` hears how the e-mail to the requester went (REQ-INC-059).
    entry_id: uuid.UUID | None = None
    # The record in the portal, a path from the portal's base starting with "/" (e.g.
    # "/requests/<id>"): people with PUBLIC access are sent there (REQ-PRT-024 AC2). None sends
    # them to the portal's home, as before.
    public_link: str | None = None

    def __post_init__(self) -> None:
        """A portal link is a path, never an address elsewhere."""
        if self.public_link is not None and not self.public_link.startswith("/"):
            msg = f"public_link must start with '/': {self.public_link!r}"
            raise ValueError(msg)


class DeliveryChange(Protocol):
    """Optional on a RecordSource: how the e-mail carrying an entry to the requester is going.

    `state` is waiting, queued, retrying, sent or failed; `reason` a code (labels
    `delivery_reason.<code>`). `at` orders the changes: an older one never overwrites a newer
    one, and a sent entry never moves back (WP-024 session 3, agreed with lane A).
    """

    async def delivery_changed(  # noqa: PLR0913 - the change, explicit
        self,
        session: AsyncSession,
        *,
        record_id: uuid.UUID,
        entry_id: uuid.UUID,
        state: str,
        reason: str | None,
        at: datetime,
    ) -> None:
        """Move the entry's delivery state (the source's own rules)."""
        ...


# Variables that hold a secret (a signed action link, WP-030 s3; lane B's review): never in a log
# line, delivery metadata or an error message; previews and admin test-sends show a placeholder
# and never mint one.
SECRET_VARIABLES = frozenset({"approval_link"})
SECRET_PLACEHOLDER = "[link]"  # noqa: S105 - shown instead of a secret, not one itself


@runtime_checkable
class RecipientLinks(Protocol):
    """Optional on a RecordSource: links made for one recipient while their e-mail renders.

    Called by the engine only for the e-mail channel, once per recipient and only when that
    e-mail has not been delivered before. Returns `{variable: LinkRequest}`: who, which action,
    on which object at which version. No token exists yet: the body holds a marker and the mail
    sender makes the link at send (D-132), so no stored body or log ever holds one. Every name
    must be in SECRET_VARIABLES.
    """

    async def recipient_links(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        recipient_id: uuid.UUID,
        channel: NotificationChannel,
    ) -> Mapping[str, LinkRequest]:
        """The recipient's own links for this event's e-mail."""
        ...


class RecordSource(Protocol):
    """Registered by the module that owns a record type."""

    @property
    def record_type(self) -> str:
        """Record type code, e.g. "incident"."""
        ...

    @property
    def channel_kind(self) -> str:
        """Kind of the record's realtime channel (`t:{tenant}:{kind}:{id}`), e.g. "wi"."""
        ...

    @property
    def events(self) -> tuple[NotificationEvent, ...]:
        """Every notification event of the type, in the order the rules screen lists them."""
        ...

    @property
    def recipient_kinds(self) -> tuple[str, ...]:
        """Relative recipients the type offers, e.g. ("requester", "assignee", "followers")."""
        ...

    @property
    def variables(self) -> tuple[Variable, ...]:
        """The record type's template variables."""
        ...

    @property
    def conditions(self) -> tuple[str, ...]:
        """Fields a rule's conditions may test, e.g. ("priority",)."""
        ...

    @property
    def event_types(self) -> tuple[str, ...]:
        """Domain event types `events_for` reads."""
        ...

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """Notification event codes raised by this committed domain event (may be none)."""
        ...

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The record's context for `event_code`; None when the record no longer exists."""
        ...

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """What `user_id` may see of the record now (the module's own visibility rules)."""
        ...


@runtime_checkable
class DeliveryListener(Protocol):
    """Optional for a `RecordSource`: told when a notification really reached someone.

    The engine calls it once a delivery is `sent` (the mail server accepted it for that address;
    never for queued, refused, suppressed or no address). The owning module decides what that
    delivery means for its record, e.g. "the requester was told of the resolution" (WP-020f
    BUG-02, agreed by lanes A and B 2026-10-29). `event_at` is when the domain event the
    notification was about happened; `at` is when the delivery was accepted.
    """

    async def delivered(  # noqa: PLR0913 - the delivery's facts, explicit
        self,
        session: AsyncSession,
        *,
        event_code: str,
        record_id: uuid.UUID,
        user_id: uuid.UUID,
        reasons: tuple[str, ...],
        event_at: datetime,
        at: datetime,
    ) -> None:
        """React to one sent delivery (in the record's tenant session)."""
        ...


class UnknownRecordTypeError(LookupError):
    """No module has registered this record type."""


_SOURCES: dict[str, RecordSource] = {}


def register_record_source(source: RecordSource) -> None:
    """Make a record type notify (call when the owning module is imported)."""
    _SOURCES[source.record_type] = source


def unregister_record_source(record_type: str) -> None:
    """Undo `register_record_source` (tests)."""
    _SOURCES.pop(record_type, None)


def record_source(record_type: str) -> RecordSource:
    """The source of `record_type`; UnknownRecordTypeError when none is registered."""
    try:
        return _SOURCES[record_type]
    except KeyError:
        raise UnknownRecordTypeError(record_type) from None


def record_sources() -> tuple[RecordSource, ...]:
    """Every registered source, by record type."""
    return tuple(_SOURCES[name] for name in sorted(_SOURCES))


def find_event(code: str) -> tuple[RecordSource, NotificationEvent]:
    """The source and event of an event code; UnknownRecordTypeError / KeyError otherwise."""
    source = record_source(code.split(".", 1)[0])
    for event in source.events:
        if event.code == code:
            return source, event
    raise KeyError(code)
