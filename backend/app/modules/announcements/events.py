"""Event contracts published by the announcements module (WP-012; docs/architecture/events.md).

Payloads carry IDs, status codes and changed field *names* only, never titles or bodies
(architecture.md §8.2). Consumers that need more read it through the module's service.
"""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class AnnouncementCreated(DomainEvent):
    """A new announcement was saved (always as a draft)."""

    event_type: ClassVar[str] = "announcements.announcement.created"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "announcement"

    announcement_id: uuid.UUID
    status: str


class AnnouncementUpdated(DomainEvent):
    """Fields changed (names only); `status` is the (unchanged) status at the time."""

    event_type: ClassVar[str] = "announcements.announcement.updated"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "announcement"

    announcement_id: uuid.UUID
    status: str
    changed_fields: list[str]


class AnnouncementStatusChanged(DomainEvent):
    """Published, unpublished, archived or reopened."""

    event_type: ClassVar[str] = "announcements.announcement.status_changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "announcement"

    announcement_id: uuid.UUID
    action: str
    from_status: str
    to_status: str


class AnnouncementDeleted(DomainEvent):
    """Moved to the trash (soft delete)."""

    event_type: ClassVar[str] = "announcements.announcement.deleted"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "announcement"

    announcement_id: uuid.UUID
    status: str


class AnnouncementRestored(DomainEvent):
    """Taken back out of the trash."""

    event_type: ClassVar[str] = "announcements.announcement.restored"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "announcement"

    announcement_id: uuid.UUID
    status: str


class AnnouncementSettingsChanged(DomainEvent):
    """The module's tenant settings changed (e.g. the four-eyes rule)."""

    event_type: ClassVar[str] = "announcements.settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "announcement_settings"

    changed_fields: list[str]


EVENTS: tuple[type[DomainEvent], ...] = (
    AnnouncementCreated,
    AnnouncementUpdated,
    AnnouncementStatusChanged,
    AnnouncementDeleted,
    AnnouncementRestored,
    AnnouncementSettingsChanged,
)
