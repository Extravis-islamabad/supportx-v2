"""Announcements' slice of a person's erasure (ADR-052 §4; lane C's S2 port).

Their follows and dismissals are deleted (their own). Announcements they own move to the
successor (D4); what they wrote stays (D1a). Batched, resumable by phase, idempotent, counts only;
a moved announcement raises its ordinary `updated` event so open screens follow (rule c).
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.announcements.events import AnnouncementUpdated
from app.modules.announcements.infra.models import (
    Announcement,
    AnnouncementDismissal,
    AnnouncementFollow,
)
from app.modules.identity_access import ERASE_BATCH, ErasureBatch, register_person_data
from app.shared.events import record_event

PHASES = ("follows", "dismissals", "owned")


async def _owned(
    session: AsyncSession, person: uuid.UUID, successor: uuid.UUID, now: datetime
) -> int:
    rows = list(
        await session.scalars(
            select(Announcement)
            .where(Announcement.owner_id == person)
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
            AnnouncementUpdated(
                announcement_id=row.id, status=row.status, changed_fields=["owner_id"]
            ),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
    return len(rows)


class AnnouncementsData:
    """announcements: follows and dismissals deleted, owned ones moved (band 500)."""

    module: ClassVar[str] = "announcements"
    order: ClassVar[int] = 560
    kinds: ClassVar[frozenset[str]] = frozenset(
        {"announcement_follows_deleted", "announcement_dismissals_deleted", "announcements_moved"}
    )

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
        """One phase (or one batch of owned announcements) per call."""
        del keep_files
        phase = cursor if cursor in PHASES else PHASES[0]
        if phase == "follows":
            result = await session.execute(
                delete(AnnouncementFollow).where(AnnouncementFollow.user_id == person_id)
            )
            return ErasureBatch(
                {"announcement_follows_deleted": int(getattr(result, "rowcount", 0) or 0)},
                cursor="dismissals",
            )
        if phase == "dismissals":
            result = await session.execute(
                delete(AnnouncementDismissal).where(AnnouncementDismissal.user_id == person_id)
            )
            return ErasureBatch(
                {"announcement_dismissals_deleted": int(getattr(result, "rowcount", 0) or 0)},
                cursor="owned",
            )
        moved = await _owned(session, person_id, successor_id, now)
        return ErasureBatch(
            {"announcements_moved": moved}, cursor="owned" if moved >= ERASE_BATCH else None
        )


PORT = AnnouncementsData()


def register() -> None:
    """Make the erasure job erase announcements' slice (at module import)."""
    register_person_data(PORT)
