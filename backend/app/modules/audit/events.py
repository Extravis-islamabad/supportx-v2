"""Event contracts of the audit module (WP-018; docs/architecture/events.md).

Payloads carry IDs, positions and codes only: never actions' details or personal data.
"""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class AuditEntryRecorded(DomainEvent):
    """An entry was written; wakes the sealer (it seals everything queued for the tenant)."""

    event_type: ClassVar[str] = "audit.entry.recorded"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "audit_entry"

    entry_id: uuid.UUID


class AuditEntriesSealed(DomainEvent):
    """Entries from `from_seq` to `to_seq` joined the chain; open audit screens refresh."""

    event_type: ClassVar[str] = "audit.entries.sealed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "audit_chain"

    from_seq: int
    to_seq: int


class AuditVerificationRequested(DomainEvent):
    """Someone asked for a verification now; the worker runs it (it can take minutes)."""

    event_type: ClassVar[str] = "audit.verification.requested"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "audit_verification_run"

    run_id: uuid.UUID


class AuditVerificationCompleted(DomainEvent):
    """A verification run finished (`status`: passed, failed or error)."""

    event_type: ClassVar[str] = "audit.verification.completed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "audit_verification_run"

    run_id: uuid.UUID
    status: str
    problem: str | None = None


class AuditAlertRaised(DomainEvent):
    """Something security admins must see: a broken chain, overdue sealing, probing.

    REQ-AUD-005, REQ-AUD-010. The notification engine (WP-023) will deliver it; until then the
    console shows a banner and operations get a metric alert (D-075).
    """

    event_type: ClassVar[str] = "audit.alert.raised"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "audit_alert"

    alert: str
    entry_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None


class AuditExportRequested(DomainEvent):
    """An auditor asked for an export; the worker builds it."""

    event_type: ClassVar[str] = "audit.export.requested"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "audit_export"

    export_id: uuid.UUID


class AuditExportFinished(DomainEvent):
    """An export is ready or failed (`problem` names why)."""

    event_type: ClassVar[str] = "audit.export.finished"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "audit_export"

    export_id: uuid.UUID
    status: str
    problem: str | None = None


class AuditSettingsChanged(DomainEvent):
    """The tenant's audit settings changed (field names only)."""

    event_type: ClassVar[str] = "audit.settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "audit_settings"

    changed_fields: list[str]


class AuditArchiveUpdated(DomainEvent):
    """A month was archived (`status` ready or failed) or a restore finished (`restore_status`)."""

    event_type: ClassVar[str] = "audit.archive.updated"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "audit_archive"

    archive_id: uuid.UUID
    status: str
    restore_status: str | None = None
    problem: str | None = None


class AuditArchiveRestoreRequested(DomainEvent):
    """An auditor asked to restore an archive for an investigation; the worker does it."""

    event_type: ClassVar[str] = "audit.archive.restore_requested"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "audit_archive"

    archive_id: uuid.UUID


EVENTS: tuple[type[DomainEvent], ...] = (
    AuditEntryRecorded,
    AuditEntriesSealed,
    AuditVerificationRequested,
    AuditVerificationCompleted,
    AuditAlertRaised,
    AuditExportRequested,
    AuditExportFinished,
    AuditSettingsChanged,
    AuditArchiveUpdated,
    AuditArchiveRestoreRequested,
)
