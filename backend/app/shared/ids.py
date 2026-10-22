"""Primary-key IDs: UUIDv7 (architecture.md §7.1; WP-004).

UUIDv7 starts with a millisecond Unix timestamp, so new rows land at the end of B-tree indexes
(no random page splits like UUIDv4) and IDs sort by creation time. The value is a standard
`uuid.UUID`, so SQLAlchemy, Pydantic and asyncpg handle it without adapters.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import uuid_utils.compat

IdFactory = Callable[[], uuid.UUID]
UUID_VERSION_7 = 7


def new_id() -> uuid.UUID:
    """A new UUIDv7. Monotonic within a process, even for IDs created in the same millisecond."""
    return uuid_utils.compat.uuid7()


def id_created_at(value: uuid.UUID) -> datetime:
    """The creation time embedded in a UUIDv7 (millisecond precision, UTC)."""
    if value.version != UUID_VERSION_7:
        msg = f"not a UUIDv7: version {value.version}"
        raise ValueError(msg)
    milliseconds = value.int >> 80
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
