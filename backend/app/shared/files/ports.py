"""What the files service asks of others (ADR-028 item 5).

The files service never reads another module's tables. Whoever owns the thing a file is attached
to (`work_items` for incidents, replies and notes) registers a `FileOwnerAccess` that answers,
for one person: may they see it, may they attach to it, may they remove a file from it. Private
notes are answered there too (staff only), so visibility is never copied onto a file.

The storage quota comes from the entitlement interface through a `QuotaSource` registered by the
module that mounts the files service (`system`), because shared code cannot import modules.
"""

import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


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


class OwnerType(StrEnum):
    """What a file can be attached to."""

    WORK_ITEM = "work_item"
    CONVERSATION_ENTRY = "conversation_entry"
    DRAFT = "draft"  # pasted into an editor before the entry exists (its uploader's only)
    BRANDING = "branding"  # a tenant's logo and icon uploads (WP-017); the record is the tenant
    KB_ARTICLE = "kb_article"  # a knowledge article's images and attachments (WP-033 s2, lane B)


class Action(StrEnum):
    """What someone wants to do with an owner's files."""

    VIEW = "view"
    ATTACH = "attach"
    REMOVE = "remove"


@dataclass(frozen=True)
class Owner:
    """One owner, and the record it belongs to (the incident of a reply)."""

    type: OwnerType
    id: uuid.UUID
    record_type: str
    record_id: uuid.UUID
    private: bool = False  # staff only (a private note): its files' downloads are audited


class FileOwnerAccess(Protocol):
    """Answers about owners of some types, for one person. Implemented by owner modules."""

    owner_types: frozenset[OwnerType]

    async def check(
        self,
        session: AsyncSession,
        actor: Actor,
        owner_type: OwnerType,
        owner_id: uuid.UUID,
        action: Action,
    ) -> Owner:
        """The owner if `actor` may do `action`; NotFound (cannot see it) or PermissionDenied."""
        ...

    async def visible_owners(
        self, session: AsyncSession, actor: Actor, record_type: str, record_id: uuid.UUID
    ) -> set[tuple[OwnerType, uuid.UUID]]:
        """Which owners of one record `actor` may see (NotFound when the record itself is hidden).

        Private entries are left out for people who may not see them.
        """
        ...


_OWNERS: dict[OwnerType, FileOwnerAccess] = {}


class UnknownOwnerError(LookupError):
    """No module answers for this owner type (a wiring error, never a user error)."""


def register_owner_access(access: FileOwnerAccess) -> None:
    """Called by an owner module at startup."""
    for owner_type in access.owner_types:
        _OWNERS[owner_type] = access


def unregister_owner_access(owner_types: Iterable[OwnerType]) -> None:
    """Called at shutdown (and by tests)."""
    for owner_type in owner_types:
        _OWNERS.pop(owner_type, None)


def owner_access(owner_type: OwnerType) -> FileOwnerAccess:
    """Who answers for `owner_type`."""
    access = _OWNERS.get(owner_type)
    if access is None:
        raise UnknownOwnerError(owner_type)
    return access


def record_access(record_type: str) -> FileOwnerAccess:
    """Who answers for a record's owners (the module owning WORK_ITEM answers for work items)."""
    del record_type  # one record family today: work items
    return owner_access(OwnerType.WORK_ITEM)


# The tenant's storage limit in bytes (None = unlimited), from the entitlement interface.
QuotaSource = Callable[[AsyncSession], Awaitable[int | None]]
_QUOTA: list[QuotaSource] = []


def register_quota(source: QuotaSource) -> None:
    """Set where the storage limit comes from (the mounting module, at startup)."""
    _QUOTA[:] = [source]


async def storage_limit(session: AsyncSession) -> int | None:
    """The tenant's storage limit in bytes; unlimited when nothing is registered (tests, tools)."""
    return await _QUOTA[0](session) if _QUOTA else None
