"""SLA set-up on realtime (WP-025 session 1): calendars and holiday lists changed.

One ID-free-of-content message to the tenant: the calendar and holiday screens (and the site
and group forms that pick a calendar) refetch what they show. It carries the IDs of the
calendars and lists that changed, never names or dates (rule c).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

CHANGED = "sla.setup.changed"


def _ids(envelope: EventEnvelope) -> tuple[str, ...]:
    payload = envelope.payload
    found = [payload.get("calendar_id"), payload.get("list_id"), *payload.get("calendar_ids", [])]
    return tuple(dict.fromkeys(str(i) for i in found if i))


async def _changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), CHANGED, ids=_ids(envelope))]
    )


ROUTES = [
    RealtimeRoute(
        (
            "sla.calendar.saved",
            "sla.calendar.deleted",
            "sla.holiday_list.saved",
            "sla.holiday_list.deleted",
        ),
        _changed,
    )
]
