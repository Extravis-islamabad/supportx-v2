"""Event contracts of the files service (registered by the `system` module, hence the prefix).

Payloads carry IDs, states and codes only: never file names or contents.
"""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class FileUploaded(DomainEvent):
    """A file was stored; the scan worker picks it up."""

    event_type: ClassVar[str] = "system.file.uploaded"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "file"

    file_id: uuid.UUID
    owner_type: str
    owner_id: uuid.UUID
    record_type: str | None = None
    record_id: uuid.UUID | None = None


class FileChanged(DomainEvent):
    """A file's state changed (scanned, blocked, deleted, moved from a draft): screens refresh."""

    event_type: ClassVar[str] = "system.file.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "file"

    file_id: uuid.UUID
    state: str
    owner_type: str
    owner_id: uuid.UUID
    record_type: str | None = None
    record_id: uuid.UUID | None = None


class FileSettingsUpdated(DomainEvent):
    """The tenant's file rules changed (admin screens refresh)."""

    event_type: ClassVar[str] = "system.file_settings.updated"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "file_settings"

    version: int


EVENTS: tuple[type[DomainEvent], ...] = (FileUploaded, FileChanged, FileSettingsUpdated)
