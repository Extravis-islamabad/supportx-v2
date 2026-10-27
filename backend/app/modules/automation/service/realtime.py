"""Automation on realtime (WP-029): changed rules, settings, availability or a stopped loop.

The message names nothing: the admin tabs and availability switches refetch what they show.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

CHANGED = "automation.changed"


async def _changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(publications=[Publication(broadcast(envelope.tenant_id), CHANGED)])


ROUTES = [
    RealtimeRoute(
        (
            "automation.definition.changed",
            "automation.availability.changed",
            # A stopped loop: the admins' banner and the record's automation panel (REQ-RUL-028).
            "automation.loop.stopped",
        ),
        _changed,
    )
]
