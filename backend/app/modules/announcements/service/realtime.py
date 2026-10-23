"""Announcements on realtime (WP-011 pattern; docs/architecture/realtime.md).

Channels this module decides about:

    t:{tenant}:queue:announcements…        staff list, one channel per audience (LiveList)
    t:{tenant}:announcement:{id}           one announcement: staff (with presence), or its
                                           audience while it is live for them
    t:{tenant}:broadcast                   (identity_access) "announcements changed", no IDs:
                                           banners and portal feeds refetch, the API filters

Only changes that touch something published reach the tenant-wide channel, so a draft's edits
are never even hinted at to requesters.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.announcements.domain.announcement import AnnouncementStatus
from app.modules.announcements.infra.models import (
    Announcement,
    AnnouncementGroup,
    AnnouncementSite,
)
from app.modules.announcements.service.announcements import (
    ANNOUNCEMENTS,
    VIEW,
    live_for,
)
from app.modules.identity_access import authorize_stored
from app.shared.events import EventEnvelope
from app.shared.realtime import (
    ChannelAccess,
    ChannelRequest,
    ChannelSpec,
    LiveList,
    Publication,
    RealtimeEffects,
    RealtimeRoute,
    broadcast,
    record,
)

RECORD_KIND = "announcement"
LIST = LiveList("announcements", VIEW)
FEED_CHANGED = "announcements.feed_changed"
CHANGED = "announcements.changed"


async def _record_channel(request: ChannelRequest) -> ChannelAccess | None:
    try:
        announcement_id = uuid.UUID(request.channel.key or "")
    except ValueError:
        return None
    subject = request.subject
    if subject.holds(VIEW) and await authorize_stored(
        request.session, subject, VIEW, ANNOUNCEMENTS, Announcement.id, announcement_id
    ):
        return ChannelAccess(presence=True)
    live = await request.session.scalar(
        select(Announcement.id).where(
            Announcement.id == announcement_id, live_for(subject, datetime.now(UTC))
        )
    )
    return ChannelAccess() if live is not None else None


CHANNELS = [LIST.spec(), ChannelSpec(kind=RECORD_KIND, authorize=_record_channel)]


def _actor(envelope: EventEnvelope) -> str | None:
    return envelope.actor.id if envelope.actor.type == "user" else None


def _touches_published(envelope: EventEnvelope) -> bool:
    payload = envelope.payload
    statuses = {payload.get("status"), payload.get("from_status"), payload.get("to_status")}
    return AnnouncementStatus.PUBLISHED in statuses


async def _announcement_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    tenant = envelope.tenant_id
    announcement_id = uuid.UUID(str(envelope.payload["announcement_id"]))
    row = await session.scalar(select(Announcement).where(Announcement.id == announcement_id))
    if row is None:  # pragma: no cover - rows are never hard-deleted by the API
        return RealtimeEffects()
    sites = list(
        await session.scalars(
            select(AnnouncementSite.site_id).where(
                AnnouncementSite.announcement_id == announcement_id
            )
        )
    )
    groups = list(
        await session.scalars(
            select(AnnouncementGroup.group_id).where(
                AnnouncementGroup.announcement_id == announcement_id
            )
        )
    )
    owners = sorted({u for u in (row.owner_id, row.created_by) if u is not None}, key=str)
    fields = tuple(envelope.payload.get("changed_fields", ()))
    if "to_status" in envelope.payload:
        fields = ("status",)
    publications = [
        Publication(
            record(tenant, RECORD_KIND, announcement_id),
            CHANGED,
            ids=(str(announcement_id),),
            fields=fields,
            version=envelope.aggregate_version,
            actor_id=_actor(envelope),
        ),
        *LIST.publications(
            tenant,
            CHANGED,
            announcement_id,
            sites=sites,
            groups=groups,
            owners=owners,
            actor_id=_actor(envelope),
        ),
    ]
    if _touches_published(envelope):
        publications.append(Publication(broadcast(tenant), FEED_CHANGED))
    return RealtimeEffects(publications=publications)


async def _settings_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Who may publish changed: open announcement pages refresh their action buttons."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), "announcements.settings_changed")]
    )


ROUTES = [
    RealtimeRoute(
        (
            "announcements.announcement.created",
            "announcements.announcement.updated",
            "announcements.announcement.status_changed",
            "announcements.announcement.deleted",
            "announcements.announcement.restored",
        ),
        _announcement_changed,
    ),
    RealtimeRoute(("announcements.settings.changed",), _settings_changed),
]
