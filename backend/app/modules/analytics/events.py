"""Event contracts published by the analytics module (WP-035; docs/architecture/events.md).

Payloads carry IDs and changed field names only, never report names or definitions
(architecture.md §8.2).
"""

import uuid
from typing import ClassVar

from app.shared.events import DomainEvent


class ReportSaved(DomainEvent):
    """A saved report was created or changed (`changed_fields` empty on create)."""

    event_type: ClassVar[str] = "analytics.report.saved"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "report"

    report_id: uuid.UUID
    owner_id: uuid.UUID
    folder_id: uuid.UUID | None
    created: bool
    changed_fields: list[str]


class ReportDeleted(DomainEvent):
    """A saved report was deleted (soft)."""

    event_type: ClassVar[str] = "analytics.report.deleted"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "report"

    report_id: uuid.UUID
    owner_id: uuid.UUID
    folder_id: uuid.UUID | None


class ReportFolderSaved(DomainEvent):
    """A shared folder was created or renamed."""

    event_type: ClassVar[str] = "analytics.report_folder.saved"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "report_folder"

    folder_id: uuid.UUID
    created: bool


class ReportFolderDeleted(DomainEvent):
    """A shared folder was deleted; its reports moved to `moved_to` (None: their owners' own)."""

    event_type: ClassVar[str] = "analytics.report_folder.deleted"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "report_folder"

    folder_id: uuid.UUID
    moved_to: uuid.UUID | None


class ReportSettingsChanged(DomainEvent):
    """The tenant's report settings changed (week start, limits)."""

    event_type: ClassVar[str] = "analytics.report_settings.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "report_settings"

    changed_fields: list[str]


class ReportExportRequested(DomainEvent):
    """Someone asked for a report export; the worker builds it."""

    event_type: ClassVar[str] = "analytics.report_export.requested"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "report_export"

    export_id: uuid.UUID
    requested_by: uuid.UUID


class ReportExportFinished(DomainEvent):
    """An export is ready or failed (`problem` says why)."""

    event_type: ClassVar[str] = "analytics.report_export.finished"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "report_export"

    export_id: uuid.UUID
    requested_by: uuid.UUID
    status: str
    problem: str | None


EVENTS: tuple[type[DomainEvent], ...] = (
    ReportSaved,
    ReportDeleted,
    ReportFolderSaved,
    ReportFolderDeleted,
    ReportSettingsChanged,
    ReportExportRequested,
    ReportExportFinished,
)
