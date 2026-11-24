"""Event contracts published by the CMDB module (WP-053 S1, S2; docs/architecture/events.md).

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


class RelationshipsChanged(DomainEvent):
    """Relationships of one type were added to or removed from a CI (WP-053 S2).

    One event per add or remove call: the source CI and every other CI it touched, all of which
    got a new version. IDs only (rule c); open maps patch both ends or refetch (§8.3).
    """

    event_type: ClassVar[str] = "cmdb.relationship.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "ci"

    ci_id: uuid.UUID
    action: str  # added or removed
    type_id: uuid.UUID
    relationship_ids: list[uuid.UUID]
    other_ci_ids: list[uuid.UUID]


class BusinessViewChanged(DomainEvent):
    """A business view was created, changed or removed (WP-053 S2; field names only)."""

    event_type: ClassVar[str] = "cmdb.business_view.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "ci_business_view"

    view_id: uuid.UUID
    base_ci_id: uuid.UUID
    action: str  # created, updated or deleted
    changed_fields: list[str]


class SyncRuleChanged(DomainEvent):
    """A sync rule was created, changed or removed (WP-053 S4a; field names only)."""

    event_type: ClassVar[str] = "cmdb.sync_rule.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "cmdb_sync_rule"

    rule_id: uuid.UUID
    action: str  # created, updated or deleted
    changed_fields: list[str]


class SyncRunChanged(DomainEvent):
    """A sync run was queued, started or finished (WP-053 S4a; IDs and its status code only)."""

    event_type: ClassVar[str] = "cmdb.sync_run.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "cmdb_sync_run"

    run_id: uuid.UUID
    rule_id: uuid.UUID
    status: str


class CiImportProgressed(DomainEvent):
    """An import of CIs or relationships moved on (WP-053 S4b): its importer's screen refreshes.

    IDs, a status code and counts only (rule c).
    """

    event_type: ClassVar[str] = "cmdb.import.progressed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "cmdb_import"

    import_id: uuid.UUID
    requested_by: uuid.UUID
    status: str
    processed: int
    total: int


class DowntimeChanged(DomainEvent):
    """A CI's downtime was added, changed, removed, or moved state as time passed (REQ-CMDB-020).

    `change` is added, updated, removed or state (the sweep moved it: `state` is the new one).
    IDs and codes only; the CI's screens refetch its downtimes (§8.3), and automation reads the
    started ones (S5d's `downtime_started`).
    """

    event_type: ClassVar[str] = "cmdb.downtime.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "ci"

    ci_id: uuid.UUID
    downtime_id: uuid.UUID
    change: str
    state: str
    source: str
    version: int


EVENTS: tuple[type[DomainEvent], ...] = (
    CiCreated,
    CiUpdated,
    CiDeleted,
    CiRestored,
    CmdbConfigChanged,
    RelationshipsChanged,
    BusinessViewChanged,
    SyncRuleChanged,
    SyncRunChanged,
    CiImportProgressed,
    DowntimeChanged,
)
