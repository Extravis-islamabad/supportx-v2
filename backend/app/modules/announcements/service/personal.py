"""A person's own state on announcements: dismissed banners and follows (WP-032 D7).

REQ-PRT-009 AC2: a dismissed banner stays dismissed for that person on every device, so the
dismissal is stored, not kept in one browser. AC3: following an announcement tells the person
when it is updated or ends. Only what is live for the person can be dismissed or followed (the
audience rules are unchanged: `live_for`). Each change goes through the outbox and reaches the
person's own channel only.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound
from app.modules.announcements.events import AnnouncementPersonalChanged
from app.modules.announcements.infra.models import (
    Announcement,
    AnnouncementDismissal,
    AnnouncementFollow,
)
from app.modules.announcements.service.announcements import live_for
from app.modules.identity_access import Subject
from app.shared.events import record_event


@dataclass(frozen=True)
class PersonalState:
    """Of some announcements, the ones the person dismissed and the ones they follow."""

    dismissed: frozenset[uuid.UUID]
    following: frozenset[uuid.UUID]


async def _live(session: AsyncSession, subject: Subject, announcement_id: uuid.UUID) -> None:
    found = await session.scalar(
        select(Announcement.id).where(
            Announcement.id == announcement_id, live_for(subject, datetime.now(UTC))
        )
    )
    if found is None:
        raise NotFound(code="announcement_not_found")


Change = Literal["dismissed", "followed", "unfollowed"]


async def _changed(
    session: AsyncSession, subject: Subject, announcement_id: uuid.UUID, change: Change
) -> None:
    await record_event(
        session,
        AnnouncementPersonalChanged(
            announcement_id=announcement_id, user_id=subject.user_id, change=change
        ),
        aggregate_id=announcement_id,
        aggregate_version=None,
    )


async def dismiss(session: AsyncSession, subject: Subject, announcement_id: uuid.UUID) -> None:
    """Hide the banner for this person everywhere; dismissing twice is not an error."""
    await _live(session, subject, announcement_id)
    made = await session.scalar(
        insert(AnnouncementDismissal)
        .values(
            tenant_id=session.info[SESSION_TENANT_KEY].tenant_id,
            announcement_id=announcement_id,
            user_id=subject.user_id,
        )
        .on_conflict_do_nothing()
        .returning(AnnouncementDismissal.user_id)
    )
    if made is not None:
        await _changed(session, subject, announcement_id, "dismissed")


async def follow(
    session: AsyncSession, subject: Subject, announcement_id: uuid.UUID, *, on: bool
) -> None:
    """Start or stop following; doing it twice is not an error."""
    if on:
        await _live(session, subject, announcement_id)
        made = await session.scalar(
            insert(AnnouncementFollow)
            .values(
                tenant_id=session.info[SESSION_TENANT_KEY].tenant_id,
                announcement_id=announcement_id,
                user_id=subject.user_id,
            )
            .on_conflict_do_nothing()
            .returning(AnnouncementFollow.user_id)
        )
        if made is not None:
            await _changed(session, subject, announcement_id, "followed")
        return
    gone = await session.execute(
        delete(AnnouncementFollow).where(
            AnnouncementFollow.announcement_id == announcement_id,
            AnnouncementFollow.user_id == subject.user_id,
        )
    )
    if gone.rowcount:  # type: ignore[attr-defined]  # a CursorResult from a DELETE
        await _changed(session, subject, announcement_id, "unfollowed")


async def state_of(
    session: AsyncSession, subject: Subject, announcement_ids: Sequence[uuid.UUID]
) -> PersonalState:
    """The person's dismissals and follows among these announcements."""
    if not announcement_ids:
        return PersonalState(frozenset(), frozenset())
    ids = list(announcement_ids)
    dismissed = await session.scalars(
        select(AnnouncementDismissal.announcement_id).where(
            AnnouncementDismissal.user_id == subject.user_id,
            AnnouncementDismissal.announcement_id.in_(ids),
        )
    )
    following = await session.scalars(
        select(AnnouncementFollow.announcement_id).where(
            AnnouncementFollow.user_id == subject.user_id,
            AnnouncementFollow.announcement_id.in_(ids),
        )
    )
    return PersonalState(frozenset(dismissed), frozenset(following))


async def followers_of(session: AsyncSession, announcement_id: uuid.UUID) -> list[uuid.UUID]:
    """Who follows an announcement (the notification recipients, REQ-PRT-009 AC3)."""
    rows = await session.scalars(
        select(AnnouncementFollow.user_id).where(
            AnnouncementFollow.announcement_id == announcement_id
        )
    )
    return list(rows)


__all__ = ["PersonalState", "dismiss", "follow", "followers_of", "state_of"]
