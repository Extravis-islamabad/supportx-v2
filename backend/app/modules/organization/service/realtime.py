"""Organization on realtime (WP-021): open screens reload sites, groups, departments, desks.

Any change tells every screen of the tenant; the message names nothing (IDs only in events).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

CHANGED = "organization.structure_changed"


async def _changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(publications=[Publication(broadcast(envelope.tenant_id), CHANGED)])


ROUTES = [
    RealtimeRoute(
        (
            "organization.site.changed",
            "organization.support_group.changed",
            "organization.department.changed",
            "organization.desk.changed",
        ),
        _changed,
    )
]
