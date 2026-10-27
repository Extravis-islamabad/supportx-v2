"""Saved reports, shared folders and favourites (REQ-RPT-019, REQ-RPT-045, REQ-RPT-048).

Who sees what (MVP; sharing by role, group or user is V1, REQ-RPT-046):
- a report without a folder is in its owner's "My reports", visible to the owner only;
- a report in a folder is visible to everyone holding `reports.view`;
- the owner edits and deletes their reports; `reports.manage_folders` also edits and deletes
  reports in shared folders, and creates, renames and deletes folders.
Saving needs `reports.create`. Every write is versioned (If-Match), recorded in field history
and emitted through the outbox in the same transaction.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules.analytics.domain.builtin import BUILTIN, BUILTIN_PREFIX
from app.modules.analytics.domain.definition import ReportDefinition
from app.modules.analytics.events import (
    ReportDeleted,
    ReportFolderDeleted,
    ReportFolderSaved,
    ReportSaved,
)
from app.modules.analytics.infra.models import Report, ReportFavourite, ReportFolder
from app.modules.identity_access import Subject
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

VIEW = "reports.view"
CREATE = "reports.create"
MANAGE_FOLDERS = "reports.manage_folders"
RECORD_TYPE = "report"
FOLDER_RECORD_TYPE = "report_folder"
MAX_FAVOURITES = 200

# Checks a definition against the entity as the saver sees it (compiles it; 422 on any problem).
Validator = Callable[[ReportDefinition], Awaitable[None]]


class ReportRepository(Repository[Report]):
    """Saved reports of the session's tenant."""

    model = Report


class FolderRepository(Repository[ReportFolder]):
    """Shared report folders of the session's tenant."""

    model = ReportFolder


@dataclass(frozen=True)
class SavedReport:
    """A saved report as one viewer sees it."""

    record: Report
    can_edit: bool


def _visible(subject: Subject) -> Any:  # noqa: ANN401 - SQLAlchemy condition
    return or_(Report.folder_id.is_not(None), Report.owner_id == subject.user_id)


def _can_edit(subject: Subject, record: Report) -> bool:
    if record.folder_id is None:
        return record.owner_id == subject.user_id and subject.holds(CREATE)
    return (record.owner_id == subject.user_id and subject.holds(CREATE)) or subject.holds(
        MANAGE_FOLDERS
    )


def _require(subject: Subject, permission: str) -> None:
    if not subject.holds(permission):
        raise PermissionDenied(params={"permission": permission})


async def list_folders(session: AsyncSession) -> Sequence[ReportFolder]:
    """Every shared folder, by name."""
    return (
        await session.scalars(
            select(ReportFolder)
            .where(ReportFolder.deleted_at.is_(None))
            .order_by(ReportFolder.name, ReportFolder.id)
        )
    ).all()


async def list_reports(session: AsyncSession, subject: Subject) -> list[SavedReport]:
    """Saved reports the subject may see: their own, and every report in a shared folder."""
    rows = (
        await session.scalars(
            select(Report)
            .where(Report.deleted_at.is_(None), _visible(subject))
            .order_by(Report.name, Report.id)
        )
    ).all()
    return [SavedReport(r, _can_edit(subject, r)) for r in rows]


async def get_report(session: AsyncSession, subject: Subject, report_id: uuid.UUID) -> SavedReport:
    """One saved report; 404 when it does not exist or is someone else's private report."""
    record = await session.scalar(
        select(Report).where(Report.id == report_id, Report.deleted_at.is_(None), _visible(subject))
    )
    if record is None:
        raise NotFound(code="report_not_found")
    return SavedReport(record, _can_edit(subject, record))


async def _folder_exists(session: AsyncSession, folder_id: uuid.UUID | None) -> None:
    if folder_id is None:
        return
    found = await session.scalar(
        select(ReportFolder.id).where(
            ReportFolder.id == folder_id, ReportFolder.deleted_at.is_(None)
        )
    )
    if found is None:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.folder_id",
                    code="unknown_folder",
                    message_key="errors.field.unknown_folder",
                )
            ]
        )


def _snapshot(record: Report) -> dict[str, Any]:
    return {
        "name": record.name,
        "description": record.description,
        "folder_id": str(record.folder_id) if record.folder_id else None,
        "definition": record.definition,
    }


async def create_report(  # noqa: PLR0913 - the new report's parts, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    name: str,
    description: str | None,
    folder_id: uuid.UUID | None,
    definition: ReportDefinition,
    copied_from: str | None,
    validate: Validator,
    source: Source,
) -> SavedReport:
    """Save a new report (a copy of a built-in one, or the user's own)."""
    _require(subject, CREATE)
    if copied_from is not None and copied_from not in BUILTIN:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.copied_from",
                    code="unknown_builtin_report",
                    message_key="errors.field.unknown_builtin_report",
                )
            ]
        )
    await validate(definition)
    await _folder_exists(session, folder_id)
    record = Report(
        name=name.strip(),
        description=(description or "").strip() or None,
        owner_id=subject.user_id,
        folder_id=folder_id,
        definition=definition.model_dump(mode="json", by_alias=True),
        copied_from=copied_from,
    )
    await ReportRepository(session).add(record)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="created",
        changes=[Change(k, None, v) for k, v in _snapshot(record).items()],
        source=source,
    )
    await record_event(
        session,
        ReportSaved(
            report_id=record.id,
            owner_id=record.owner_id,
            folder_id=record.folder_id,
            created=True,
            changed_fields=[],
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return SavedReport(record, can_edit=True)


async def _editable(session: AsyncSession, subject: Subject, report_id: uuid.UUID) -> Report:
    found = await get_report(session, subject, report_id)
    if not found.can_edit:
        raise PermissionDenied(code="report_not_editable")
    return found.record


async def update_report(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    report_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    validate: Validator,
    source: Source,
) -> SavedReport:
    """Rename, describe, move or change the definition (only the fields given)."""
    record = await _editable(session, subject, report_id)
    before = _snapshot(record)
    columns: dict[str, Any] = {}
    if "name" in values:
        columns["name"] = values["name"].strip()
    if "description" in values:
        columns["description"] = (values["description"] or "").strip() or None
    if "folder_id" in values:
        await _folder_exists(session, values["folder_id"])
        columns["folder_id"] = values["folder_id"]
    if "definition" in values:
        definition: ReportDefinition = values["definition"]
        await validate(definition)
        columns["definition"] = definition.model_dump(mode="json", by_alias=True)
    columns = {k: v for k, v in columns.items() if getattr(record, k) != v}
    if not columns:
        if record.version != expected_version:
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": record.version},
            )
        return SavedReport(record, can_edit=True)
    updated = await ReportRepository(session).update(
        record.id, expected_version=expected_version, changes=columns
    )
    after = _snapshot(updated)
    changes = [Change(k, before[k], v) for k, v in after.items() if before[k] != v]
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        ReportSaved(
            report_id=updated.id,
            owner_id=updated.owner_id,
            folder_id=updated.folder_id,
            created=False,
            changed_fields=[c.field for c in changes],
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return SavedReport(updated, can_edit=True)


async def delete_report(
    session: AsyncSession,
    subject: Subject,
    report_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Delete a saved report (soft); its favourites go with it."""
    record = await _editable(session, subject, report_id)
    deleted = await ReportRepository(session).soft_delete(
        record.id, expected_version=expected_version
    )
    await session.execute(
        delete(ReportFavourite).where(ReportFavourite.report_ref == str(record.id))
    )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        ReportDeleted(report_id=record.id, owner_id=record.owner_id, folder_id=record.folder_id),
        aggregate_id=record.id,
        aggregate_version=deleted.version,
    )


# --- folders --------------------------------------------------------------------------------------


async def create_folder(
    session: AsyncSession, subject: Subject, *, name: str, source: Source
) -> ReportFolder:
    """A new shared folder."""
    _require(subject, MANAGE_FOLDERS)
    folder = ReportFolder(name=name.strip(), owner_id=subject.user_id)
    await _unique_name(session, folder.name, None)
    await FolderRepository(session).add(folder)
    await record_changes(
        session,
        record_type=FOLDER_RECORD_TYPE,
        record_id=folder.id,
        version=folder.version,
        kind="created",
        changes=[Change("name", None, folder.name)],
        source=source,
    )
    await record_event(
        session,
        ReportFolderSaved(folder_id=folder.id, created=True),
        aggregate_id=folder.id,
        aggregate_version=folder.version,
    )
    return folder


async def _unique_name(session: AsyncSession, name: str, except_id: uuid.UUID | None) -> None:
    query = select(ReportFolder.id).where(
        ReportFolder.deleted_at.is_(None),
        ReportFolder.name.ilike(name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")),
    )
    if except_id is not None:
        query = query.where(ReportFolder.id != except_id)
    if await session.scalar(query) is not None:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.name",
                    code="duplicate_name",
                    message_key="errors.field.duplicate_name",
                )
            ]
        )


async def rename_folder(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    folder_id: uuid.UUID,
    *,
    name: str,
    expected_version: int,
    source: Source,
) -> ReportFolder:
    """Rename a shared folder."""
    _require(subject, MANAGE_FOLDERS)
    folder = await FolderRepository(session).get(folder_id)
    name = name.strip()
    if folder.name == name:
        return folder
    await _unique_name(session, name, folder.id)
    before = folder.name
    updated = await FolderRepository(session).update(
        folder.id, expected_version=expected_version, changes={"name": name}
    )
    await record_changes(
        session,
        record_type=FOLDER_RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=[Change("name", before, name)],
        source=source,
    )
    await record_event(
        session,
        ReportFolderSaved(folder_id=updated.id, created=False),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return updated


async def delete_folder(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    folder_id: uuid.UUID,
    *,
    move_to: uuid.UUID | None,
    expected_version: int,
    source: Source,
) -> None:
    """Delete a shared folder; its reports move to `move_to`, or back to their owners' own.

    The caller must say where they go (REQ-RPT-045 AC3); the API requires the choice.
    """
    _require(subject, MANAGE_FOLDERS)
    if move_to == folder_id:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.move_to", code="same_folder", message_key="errors.field.same_folder"
                )
            ]
        )
    await _folder_exists(session, move_to)
    folder = await FolderRepository(session).get(folder_id)
    deleted = await FolderRepository(session).soft_delete(
        folder.id, expected_version=expected_version
    )
    await session.execute(
        update(Report)
        .where(Report.folder_id == folder.id, Report.deleted_at.is_(None))
        .values(folder_id=move_to, version=Report.version + 1)
    )
    await record_changes(
        session,
        record_type=FOLDER_RECORD_TYPE,
        record_id=folder.id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        ReportFolderDeleted(folder_id=folder.id, moved_to=move_to),
        aggregate_id=folder.id,
        aggregate_version=deleted.version,
    )


# --- favourites -----------------------------------------------------------------------------------


async def favourites(session: AsyncSession, subject: Subject) -> list[str]:
    """The subject's starred report references, newest first."""
    return list(
        (
            await session.scalars(
                select(ReportFavourite.report_ref)
                .where(ReportFavourite.user_id == subject.user_id)
                .order_by(ReportFavourite.created_at.desc())
            )
        ).all()
    )


async def set_favourite(
    session: AsyncSession, subject: Subject, report_ref: str, *, starred: bool
) -> None:
    """Star or unstar a built-in (`builtin:<code>`) or saved (id) report the subject can see."""
    _require(subject, VIEW)
    if report_ref.startswith(BUILTIN_PREFIX):
        if report_ref.removeprefix(BUILTIN_PREFIX) not in BUILTIN:
            raise NotFound(code="report_not_found")
    else:
        try:
            await get_report(session, subject, uuid.UUID(report_ref))
        except ValueError:
            raise NotFound(code="report_not_found") from None
    if not starred:
        await session.execute(
            delete(ReportFavourite).where(
                ReportFavourite.user_id == subject.user_id,
                ReportFavourite.report_ref == report_ref,
            )
        )
        return
    if len(await favourites(session, subject)) >= MAX_FAVOURITES:
        raise ValidationFailed(code="too_many_favourites", params={"max": MAX_FAVOURITES})
    await session.execute(
        insert(ReportFavourite)
        .values(tenant_id=subject.tenant_id, user_id=subject.user_id, report_ref=report_ref)
        .on_conflict_do_nothing()
    )
