"""A record's conversation as text, asked of the module that owns the record (WP-038, §6.1).

The ai module never reads another module's tables. The owner registers, at start-up, a function
that returns what one person may see of a record, from the sources the tenant's admin chose
(the description, replies, public notes, private notes). An unregistered record type has no
conversation (fail closed), as with `register_record_access`.
"""

import uuid
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject

# Summary sources an admin may choose (AI settings), in screen order.
SUMMARY_SOURCES = ("description", "replies", "public_notes", "private_notes")
DEFAULT_SUMMARY_SOURCES = ("description", "replies", "public_notes")


@dataclass(frozen=True, slots=True)
class ConversationEntry:
    """One reply or note, as plain text."""

    kind: str  # reply | note
    visibility: str  # public | private
    author: str
    at: datetime
    text: str


@dataclass(frozen=True, slots=True)
class ConversationText:
    """What one person may see of a record, from the chosen sources."""

    record_id: uuid.UUID
    display_id: str
    title: str
    description: str
    entries: tuple[ConversationEntry, ...]
    # The newest entry on the record (a summary of it is current until a newer one is added).
    last_entry_id: uuid.UUID | None
    # Everyone named in it, for masking.
    names: tuple[str, ...]
    private_included: bool


# (session, subject, record ID, sources) → the text; raises NotFound when the record is not visible.
ConversationSource = Callable[
    [AsyncSession, Subject, uuid.UUID, Collection[str]], Awaitable[ConversationText]
]

_SOURCES: dict[str, ConversationSource] = {}


def register_conversation_source(record_type: str, source: ConversationSource) -> None:
    """The owning module's conversation reader for one record type (at its start-up)."""
    _SOURCES[record_type] = source


def unregister_conversation_source(record_type: str) -> None:
    """At shutdown (tests start the app more than once)."""
    _SOURCES.pop(record_type, None)


def conversation_source(record_type: str) -> ConversationSource | None:
    """The registered reader, or None (the record type has no conversation for AI)."""
    return _SOURCES.get(record_type)
