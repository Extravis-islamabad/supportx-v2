"""Event contracts published by the CMDB module (WP-053 S1; docs/architecture/events.md).

Payloads carry IDs, codes and changed field *names* only, never names or descriptions
(architecture.md §8.2). Consumers read more through the module's public interface.
"""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class CiCreated(DomainEvent):
    """A CI was saved for the first time (by hand, copied, or from an asset)."""

    event_type: ClassVar[str] = "cmdb.ci.created"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "ci"

    ci_id: uuid.UUID
    type_id: uuid.UUID
    source: str
    asset_id: uuid.UUID | None = None


class CiUpdated(DomainEvent):
    """Fields of a CI changed (names only; a type change lists `type_id`)."""

    event_type: ClassVar[str] = "cmdb.ci.updated"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "ci"

    ci_id: uuid.UUID
    type_id: uuid.UUID
    changed_fields: list[str]


class CiDeleted(DomainEvent):
    """A CI moved to the trash (soft delete)."""

    event_type: ClassVar[str] = "cmdb.ci.deleted"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "ci"

    ci_id: uuid.UUID
    type_id: uuid.UUID


class CiRestored(DomainEvent):
    """A CI came back from the trash."""

    event_type: ClassVar[str] = "cmdb.ci.restored"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "ci"

    ci_id: uuid.UUID
    type_id: uuid.UUID


class CmdbConfigChanged(DomainEvent):
    """A CI type, a CI state or the CMDB settings changed (`what`: type, state or settings)."""

    event_type: ClassVar[str] = "cmdb.config.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "cmdb_config"

    what: str
    action: str
    item_id: uuid.UUID | None = None


EVENTS: tuple[type[DomainEvent], ...] = (
    CiCreated,
    CiUpdated,
    CiDeleted,
    CiRestored,
    CmdbConfigChanged,
)
