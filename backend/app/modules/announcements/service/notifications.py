"""Followers hear when an announcement is updated or withdrawn (WP-032 D7; REQ-PRT-009 AC3).

Through the one notification engine (lane B's WP-023, `app.shared.notifications.ports`), never a
second sender: the engine applies the tenant's rules, personal preferences and the delivery log.

- `announcement.updated`: a published announcement's text or window changed;
- `announcement.ended`: it was taken down (unpublished or archived).

Recipients are its followers only. An announcement whose window simply runs out raises no event
yet (there is no timer in the module); that case is recorded for lane C's WP-062b.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.modules.announcements.domain.announcement import AnnouncementStatus
from app.modules.announcements.events import AnnouncementStatusChanged, AnnouncementUpdated
from app.modules.announcements.infra.models import Announcement, AnnouncementFollow
from app.modules.announcements.service.announcements import addressed_to
from app.modules.announcements.service.personal import followers_of
from app.modules.announcements.service.realtime import RECORD_KIND
from app.modules.identity_access import subject_for
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

UPDATED = "announcement.updated"
ENDED = "announcement.ended"
FOLLOWERS = "followers"

EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent(
        UPDATED,
        NotificationCategory.FOLLOWING,
        EventDefault(enabled=True, recipients=(FOLLOWERS,)),
    ),
    NotificationEvent(
        ENDED,
        NotificationCategory.FOLLOWING,
        EventDefault(enabled=True, recipients=(FOLLOWERS,)),
    ),
)
VARIABLES = (
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)
_TAKEN_DOWN = {AnnouncementStatus.DRAFT.value, AnnouncementStatus.ARCHIVED.value}


class AnnouncementNotifications:
    """`RecordSource` for announcements: only their followers, only these two events."""

    record_type = "announcement"
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = (FOLLOWERS,)
    variables = VARIABLES
    conditions = ("severity",)
    event_types = (AnnouncementUpdated.event_type, AnnouncementStatusChanged.event_type)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """A published one changed, or a published one was taken down."""
        payload = envelope.payload
        if envelope.event_type == AnnouncementUpdated.event_type:
            return (UPDATED,) if payload.get("status") == AnnouncementStatus.PUBLISHED else ()
        if (
            payload.get("from_status") == AnnouncementStatus.PUBLISHED
            and payload.get("to_status") in _TAKEN_DOWN
        ):
            return (ENDED,)
        return ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The announcement now and its followers now."""
        record = await session.get(
            Announcement, uuid.UUID(str(envelope.payload["announcement_id"]))
        )
        if record is None or record.deleted_at is not None:
            return None
        followers = frozenset(await followers_of(session, record.id))
        if not followers:
            return None
        variables: dict[str, VariableValue] = {
            "record.display_id": record.display_id,
            "record.title": record.title,
            "record.link": f"/announcements/{record.id}",
        }
        return RecordContext(
            record_id=record.id,
            display_id=record.display_id,
            link=f"/announcements/{record.id}",
            variables=variables,
            public_variables=variables,
            relatives={FOLLOWERS: followers},
            conditions={"severity": record.severity},
            event_code=event_code,
            public_link="/",  # requesters read announcements on the portal home
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """A follower still in its audience now gets the public text (lane C's review).

        The audience is checked at send time: someone who followed and is no longer addressed
        (the audience was narrowed, or they moved site or group) is told nothing.
        """
        follows = await session.scalar(
            select(AnnouncementFollow.user_id).where(
                AnnouncementFollow.announcement_id == record_id,
                AnnouncementFollow.user_id == user_id,
            )
        )
        if follows is None:
            return RecordAccess.NONE
        subject = await subject_for(session, session.info[SESSION_TENANT_KEY].tenant_id, user_id)
        addressed = await session.scalar(
            select(Announcement.id).where(Announcement.id == record_id, addressed_to(subject))
        )
        return RecordAccess.PUBLIC if addressed is not None else RecordAccess.NONE


SOURCE = AnnouncementNotifications()


def register() -> None:
    """Make announcements notify their followers (idempotent; at import)."""
    register_record_source(SOURCE)


__all__ = ["ENDED", "UPDATED", "register"]
