"""Records other modules may ask about (D-121; architecture.md §6.1 rule e).

A module that owns records (work_items for incidents) registers a `RecordFacts` at import. Other
modules (knowledge) ask through it and never read the owner's tables. Every answer applies the
owner's own read rule for the person asking: what they could open themselves, nothing more.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

BATCH_MAX = 500  # ids per `visible` call (lane A's condition)


class Actor(Protocol):
    """The person asking (the identity module's Subject satisfies this)."""

    @property
    def tenant_id(self) -> uuid.UUID:
        """Their tenant."""
        ...

    @property
    def user_id(self) -> uuid.UUID:
        """Who they are."""
        ...


@dataclass(frozen=True)
class RecordPeople:
    """Whom a record is for: its requester, and the person it was raised on behalf of."""

    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None

    @property
    def ids(self) -> frozenset[uuid.UUID]:
        """Both, without the empty one."""
        return frozenset(i for i in (self.requester_id, self.on_behalf_of_id) if i is not None)


@dataclass(frozen=True)
class RecordSummary:
    """A record as a list line shows it: its ID, subject and status category (a fixed code)."""

    id: uuid.UUID
    display_id: str
    subject: str
    status_category: str


@dataclass(frozen=True)
class RecordResolution:
    """What "save as knowledge" starts from (REQ-KB-016)."""

    subject: str
    resolution_html: str  # already sanitised by the owner
    language: str  # "en" or "ar"


class RecordFacts(Protocol):
    """Answers about one record type, for one person, with the owner's read rule."""

    record_type: str  # the work-item type code: "incident"

    async def visible(
        self, session: AsyncSession, subject: Actor, ids: Iterable[uuid.UUID]
    ) -> set[uuid.UUID]:
        """The ids `subject` may open (live records only). At most BATCH_MAX ids."""
        ...

    async def summaries(
        self, session: AsyncSession, subject: Actor, ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, RecordSummary]:
        """The records of these ids `subject` may open, as list lines. At most BATCH_MAX ids."""
        ...

    async def requester_of(
        self, session: AsyncSession, subject: Actor, record_id: uuid.UUID
    ) -> RecordPeople | None:
        """Whom the record is for, when `subject` may open it; else None."""
        ...

    async def resolution_of(
        self, session: AsyncSession, subject: Actor, record_id: uuid.UUID
    ) -> RecordResolution | None:
        """Subject and resolution, when `subject` may open it and it has one; else None."""
        ...


_FACTS: dict[str, RecordFacts] = {}


class UnknownRecordTypeError(LookupError):
    """No module answers for this record type (a wiring error, or a type not built yet)."""


def register_record_facts(facts: RecordFacts) -> None:
    """Called by the owner module at import."""
    _FACTS[facts.record_type] = facts


def unregister_record_facts(record_type: str) -> None:
    """For tests."""
    _FACTS.pop(record_type, None)


def record_facts(record_type: str) -> RecordFacts:
    """Who answers for `record_type`."""
    found = _FACTS.get(record_type)
    if found is None:
        raise UnknownRecordTypeError(record_type)
    return found
