"""The audit log on realtime (WP-011 pattern; REQ-AUD-007 AC3, REQ-AUD-010).

One list channel, joined only by holders of `audit.view`:

    t:{tenant}:queue:audit      "the audit log changed" (new entries, sealing, verification,
                                exports, alerts); no IDs, no content. Open screens refetch
                                through the API, which applies the permission again.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import LiveList, Publication, RealtimeEffects, RealtimeRoute
from app.shared.realtime.channels import queue

LIST = LiveList("audit", "audit.view")
CHANGED = "audit.changed"


async def _changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(queue(envelope.tenant_id, LIST.name), CHANGED, coalesce=True)]
    )


CHANNELS = [LIST.spec()]
ROUTES = [
    RealtimeRoute(
        (
            "audit.entry.recorded",
            "audit.entries.sealed",
            "audit.verification.completed",
            "audit.alert.raised",
            "audit.export.finished",
            "audit.settings.changed",
        ),
        _changed,
    )
]
