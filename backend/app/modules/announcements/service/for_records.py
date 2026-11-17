"""Announcements made from another module's record (WP-046b S4, REQ-INC-129; lane C's design).

The announcements module stays unaware of records: the caller keeps its own link to the
announcement IDs returned here. Everything goes through this module's own service, with the
actor's own rights, scope and audience rules:

- `announce_for_record`: a draft from the actor's text and chosen audience (`create`, which needs
  announcements.manage and checks the sites and groups against the actor's scope through
  `holders`), published at once only when the actor may publish (`transition`), otherwise left
  for someone who may. Never automatic: the caller acts on a person's request.
- `end_for_record`: archive one announcement the actor may manage (`transition`); an archived
  one is left as it is.
- `states`: the status of announcements by ID, for the caller's list of its links (only those
  the actor may see; the others are left out).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.modules.announcements.domain.announcement import AnnouncementAction, AnnouncementStatus
from app.modules.announcements.service import announcements as service
from app.modules.identity_access import Subject
from app.shared.history import Source

STATES_MAX = 50  # a record's announcements are a handful; never an unbounded loop


@dataclass(frozen=True)
class Announced:
    """An announcement made or ended for a record: IDs and its status only."""

    id: uuid.UUID
    display_id: str
    status: str
    title: str


def _of(view: service.AnnouncementView | service.PublicView) -> Announced:
    record = view.record
    return Announced(record.id, record.display_id, record.status, record.title)


async def announce_for_record(  # noqa: PLR0913 - the actor, the text, its audience and source
    session: AsyncSession,
    subject: Subject,
    *,
    values: Mapping[str, Any],
    publish: bool,
    source: Source,
    holders: service.PermissionHolders,
) -> Announced:
    """A draft with the actor's text and audience; published now when asked and allowed."""
    made = await service.create(session, subject, values, source, holders)
    if publish and subject.holds(service.PUBLISH):
        made = await service.transition(
            session,
            subject,
            made.record.id,
            AnnouncementAction.PUBLISH,
            expected_version=made.record.version,
            reason=None,
            source=source,
        )
    return _of(made)


async def end_for_record(
    session: AsyncSession,
    subject: Subject,
    announcement_id: uuid.UUID,
    *,
    reason: str | None,
    source: Source,
) -> Announced:
    """Archive it (the actor must be able to manage it); an archived one is left as it is.

    The version is read here, not taken from the caller: archiving is idempotent and the
    announcement keeps its own history, so a stale screen never needs a conflict (lane C).
    """
    view = await service.get_announcement(session, subject, announcement_id)
    if view.record.status == AnnouncementStatus.ARCHIVED:
        return _of(view)
    ended = await service.transition(
        session,
        subject,
        announcement_id,
        AnnouncementAction.ARCHIVE,
        expected_version=view.record.version,
        reason=reason,
        source=source,
    )
    return _of(ended)


async def states(
    session: AsyncSession, subject: Subject, announcement_ids: Sequence[uuid.UUID]
) -> list[Announced]:
    """The ones the actor may see, in the order asked (at most STATES_MAX); others left out."""
    found: list[Announced] = []
    for announcement_id in announcement_ids[:STATES_MAX]:
        try:
            found.append(_of(await service.get_announcement(session, subject, announcement_id)))
        except (NotFound, PermissionDenied):
            continue
    return found
