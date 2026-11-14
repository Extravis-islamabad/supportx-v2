"""Analytics' slices of a person's erasure (ADR-052 §4; lane C's S2 ports).

Two ports, in two bands:
- `analytics.recipients` (references, band 100): the person leaves other people's scheduled
  report recipient lists.
- `analytics` (owned, band 500):
  - their favourites and dashboard preferences are deleted; their report exports are deleted
    with their files;
  - their private dashboards (not shared, no group) are deleted; shared or group dashboards,
    reports and folders (shared at MVP) move to the successor (D4);
  - their scheduled reports move to the successor and are PAUSED (`owner_changed`, ADR-052 §4):
    a schedule mails with its owner's access (ADR-047 §5), so the successor looks before it runs.

Batched (ERASE_BATCH rows a call), resumable by phase, idempotent, counts only. Each moved or
removed object raises the module's ordinary event, so open screens follow live (rule c); none
names the person.
"""

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.analytics.events import (
    DashboardDeleted,
    DashboardSaved,
    ReportFolderSaved,
    ReportSaved,
    ReportScheduleSaved,
)
from app.modules.analytics.infra.models import (
    Dashboard,
    DashboardPreference,
    Report,
    ReportExport,
    ReportFavourite,
    ReportFolder,
    ReportSchedule,
)
from app.modules.analytics.service.jobs import storage_or_none
from app.modules.identity_access import (
    ERASE_BATCH,
    ErasureBatch,
    ErasureStepFailed,
    register_person_data,
)
from app.shared.events import record_event
from app.shared.storage import ObjectStorage

OWNER_CHANGED = "owner_changed"  # the schedule's paused reason (labelled)
STORAGE_UNAVAILABLE = "erasure_storage_unavailable"
# Where export files live; replaced in tests.
storage_factory: Callable[[], ObjectStorage | None] = lambda: storage_or_none(get_settings())  # noqa: E731


async def _recipients(session: AsyncSession, person: uuid.UUID, now: datetime) -> int:
    rows = list(
        await session.scalars(
            select(ReportSchedule)
            .where(ReportSchedule.recipient_users.contains([str(person)]))
            .limit(ERASE_BATCH)
            .with_for_update()
        )
    )
    for row in rows:
        row.recipient_users = [u for u in row.recipient_users if u != str(person)]
        row.version += 1
        row.updated_at = now
    await session.flush()
    for row in rows:
        await record_event(
            session,
            ReportScheduleSaved(
                schedule_id=row.id,
                owner_id=row.owner_id,
                status=row.status,
                changed_fields=["recipient_users"],
            ),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
    return len(rows)


class AnalyticsRecipients:
    """analytics.recipients: out of other people's schedule recipient lists (band 100)."""

    module: ClassVar[str] = "analytics.recipients"
    order: ClassVar[int] = 140
    kinds: ClassVar[frozenset[str]] = frozenset({"report_recipients_removed"})

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """One batch of schedules that name them as a recipient."""
        del successor_id, keep_files, cursor
        done = await _recipients(session, person_id, now)
        more = "recipients" if done >= ERASE_BATCH else None
        return ErasureBatch({"report_recipients_removed": done}, cursor=more)


# --- owned ----------------------------------------------------------------------------------------


async def _favourites(session: AsyncSession, person: uuid.UUID) -> int:
    result = await session.execute(delete(ReportFavourite).where(ReportFavourite.user_id == person))
    return int(getattr(result, "rowcount", 0) or 0)


async def _preferences(session: AsyncSession, person: uuid.UUID) -> int:
    result = await session.execute(
        delete(DashboardPreference).where(DashboardPreference.user_id == person)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _exports(session: AsyncSession, person: uuid.UUID) -> int:
    """Their exports go with their files (a file first, then its row)."""
    rows = list(
        await session.scalars(
            select(ReportExport).where(ReportExport.requested_by == person).limit(ERASE_BATCH)
        )
    )
    with_files = [row for row in rows if row.object_key]
    storage = storage_factory() if with_files else None
    if with_files and storage is None:
        raise ErasureStepFailed(STORAGE_UNAVAILABLE)  # retried: a file is never left behind
    for row in with_files:
        await storage.delete(row.object_key)  # type: ignore[union-attr,arg-type]  # checked above
    if rows:
        await session.execute(
            delete(ReportExport).where(ReportExport.id.in_([row.id for row in rows]))
        )
    return len(rows)


async def _dashboards(
    session: AsyncSession, person: uuid.UUID, successor: uuid.UUID, now: datetime
) -> tuple[int, int]:
    """Private ones deleted; shared or group ones to the successor. (deleted, moved)."""
    rows = list(
        await session.scalars(
            select(Dashboard)
            .where(Dashboard.owner_id == person)
            .limit(ERASE_BATCH)
            .with_for_update()
        )
    )
    private = [row for row in rows if not row.shared and row.group_id is None]
    shared = [row for row in rows if row not in private]
    for row in shared:
        row.owner_id = successor
        row.version += 1
        row.updated_at = now
    await session.flush()
    for row in private:
        await record_event(
            session,
            DashboardDeleted(dashboard_id=row.id, owner_id=person, shared=False),
            aggregate_id=row.id,
            aggregate_version=row.version + 1,
        )
    if private:
        await session.execute(delete(Dashboard).where(Dashboard.id.in_([r.id for r in private])))
    for row in shared:
        await record_event(
            session,
            DashboardSaved(
                dashboard_id=row.id,
                owner_id=successor,
                shared=row.shared,
                was_shared=row.shared,
                group_id=row.group_id,
                was_group=row.group_id is not None,
                created=False,
                changed_fields=["owner_id"],
            ),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
    return len(private), len(shared)


async def _reports(
    session: AsyncSession, person: uuid.UUID, successor: uuid.UUID, now: datetime
) -> int:
    rows = list(
        await session.scalars(
            select(Report).where(Report.owner_id == person).limit(ERASE_BATCH).with_for_update()
        )
    )
    for row in rows:
        row.owner_id, row.version, row.updated_at = successor, row.version + 1, now
    await session.flush()
    for row in rows:
        await record_event(
            session,
            ReportSaved(
                report_id=row.id,
                owner_id=successor,
                folder_id=row.folder_id,
                created=False,
                changed_fields=["owner_id"],
            ),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
    return len(rows)


async def _folders(
    session: AsyncSession, person: uuid.UUID, successor: uuid.UUID, now: datetime
) -> int:
    rows = list(
        await session.scalars(
            select(ReportFolder)
            .where(ReportFolder.owner_id == person)
            .limit(ERASE_BATCH)
            .with_for_update()
        )
    )
    for row in rows:
        row.owner_id, row.version, row.updated_at = successor, row.version + 1, now
    await session.flush()
    for row in rows:
        await record_event(
            session,
            ReportFolderSaved(folder_id=row.id, created=False),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
    return len(rows)


async def _schedules(
    session: AsyncSession, person: uuid.UUID, successor: uuid.UUID, now: datetime
) -> int:
    """To the successor, paused: it mails with its owner's access, so they look first."""
    rows = list(
        await session.scalars(
            select(ReportSchedule)
            .where(ReportSchedule.owner_id == person)
            .limit(ERASE_BATCH)
            .with_for_update()
        )
    )
    for row in rows:
        row.owner_id = successor
        if row.status == "active":
            row.status, row.paused_reason = "paused", OWNER_CHANGED
        row.version += 1
        row.updated_at = now
    await session.flush()
    for row in rows:
        await record_event(
            session,
            ReportScheduleSaved(
                schedule_id=row.id,
                owner_id=successor,
                status=row.status,
                changed_fields=["owner_id", "status"],
            ),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
    return len(rows)


PHASES = ("favourites", "preferences", "exports", "dashboards", "reports", "folders", "schedules")
KINDS = frozenset(
    {
        "report_favourites_deleted",
        "dashboard_preferences_deleted",
        "report_exports_deleted",
        "dashboards_deleted",
        "dashboards_moved",
        "reports_moved",
        "report_folders_moved",
        "report_schedules_moved",
    }
)


class AnalyticsData:
    """analytics: favourites, preferences and exports deleted; objects moved (band 500)."""

    module: ClassVar[str] = "analytics"
    order: ClassVar[int] = 550
    kinds: ClassVar[frozenset[str]] = KINDS

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """One batch of the phase the cursor names (the first when None)."""
        del keep_files  # exports are analytics' own generated files, not the person's uploads
        phase = cursor if cursor in PHASES else PHASES[0]
        counts: dict[str, int]
        if phase == "favourites":
            counts = {"report_favourites_deleted": await _favourites(session, person_id)}
            size = 0  # one statement: all of them
        elif phase == "preferences":
            counts = {"dashboard_preferences_deleted": await _preferences(session, person_id)}
            size = 0
        elif phase == "exports":
            size = await _exports(session, person_id)
            counts = {"report_exports_deleted": size}
        elif phase == "dashboards":
            deleted, moved = await _dashboards(session, person_id, successor_id, now)
            counts = {"dashboards_deleted": deleted, "dashboards_moved": moved}
            size = deleted + moved
        elif phase == "reports":
            size = await _reports(session, person_id, successor_id, now)
            counts = {"reports_moved": size}
        elif phase == "folders":
            size = await _folders(session, person_id, successor_id, now)
            counts = {"report_folders_moved": size}
        else:
            size = await _schedules(session, person_id, successor_id, now)
            counts = {"report_schedules_moved": size}
        if size >= ERASE_BATCH:
            return ErasureBatch(counts, cursor=phase)  # more of this phase
        following = PHASES.index(phase) + 1
        return ErasureBatch(counts, cursor=PHASES[following] if following < len(PHASES) else None)


RECIPIENTS = AnalyticsRecipients()
PORT = AnalyticsData()


def register() -> None:
    """Make the erasure job erase analytics' slices (at module import)."""
    register_person_data(RECIPIENTS)
    register_person_data(PORT)
