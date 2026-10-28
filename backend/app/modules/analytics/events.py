"""Event contracts published by the analytics module (WP-035; docs/architecture/events.md).

Payloads carry IDs and changed field names only, never report names or definitions
(architecture.md §8.2).
"""

import uuid
from datetime import datetime
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


class ReportScheduleSaved(DomainEvent):
    """A schedule was created, changed, paused, resumed or deleted."""

    event_type: ClassVar[str] = "analytics.report_schedule.saved"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "report_schedule"

    schedule_id: uuid.UUID
    owner_id: uuid.UUID
    status: str
    changed_fields: list[str]


class ReportScheduleDue(DomainEvent):
    """A schedule's time came; the worker sends it."""

    event_type: ClassVar[str] = "analytics.report_schedule.due"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "report_schedule"

    schedule_id: uuid.UUID
    run_at: datetime


class ReportScheduleRan(DomainEvent):
    """A run finished: how many recipients got it, and why a failed run failed."""

    event_type: ClassVar[str] = "analytics.report_schedule.ran"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "report_schedule"

    schedule_id: uuid.UUID
    owner_id: uuid.UUID
    result: str
    sent: int
    failed: int
    paused: bool


class DashboardSaved(DomainEvent):
    """A dashboard was created or changed (`changed_fields` empty on create).

    `was_shared`: it was shared before this change, so its former viewers must hear of it
    (un-sharing closes it on their screens, REQ-DSH-028 AC2).
    """

    event_type: ClassVar[str] = "analytics.dashboard.saved"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "dashboard"

    dashboard_id: uuid.UUID
    owner_id: uuid.UUID
    shared: bool
    was_shared: bool
    created: bool
    changed_fields: list[str]


class DashboardDeleted(DomainEvent):
    """A dashboard was deleted (soft)."""

    event_type: ClassVar[str] = "analytics.dashboard.deleted"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "dashboard"

    dashboard_id: uuid.UUID
    owner_id: uuid.UUID
    shared: bool


class DashboardHomeChanged(DomainEvent):
    """A role's default home dashboard changed (its holders' home pages follow)."""

    event_type: ClassVar[str] = "analytics.dashboard_home.changed"
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str] = "role"

    role_key: str


EVENTS: tuple[type[DomainEvent], ...] = (
    ReportSaved,
    ReportDeleted,
    ReportFolderSaved,
    ReportFolderDeleted,
    ReportSettingsChanged,
    ReportExportRequested,
    ReportExportFinished,
    ReportScheduleSaved,
    ReportScheduleDue,
    ReportScheduleRan,
    DashboardSaved,
    DashboardDeleted,
    DashboardHomeChanged,
)
