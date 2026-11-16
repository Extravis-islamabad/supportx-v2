"""The audit log on realtime (WP-011 pattern; REQ-AUD-007 AC3, REQ-AUD-010).

One list channel, joined only by holders of `audit.view`:

    t:{tenant}:queue:audit      "the audit log changed" (new entries, sealing, verification,
                                exports, archives, alerts); no IDs, no content. Open screens refetch
                                through the API, which applies the permission again.
    t:{tenant}:queue:personal_data_access   "the personal data access log changed" (REQ-AUD-017),
                                joined only with `audit.view_personal_data_access`.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import LiveList, Publication, RealtimeEffects, RealtimeRoute
from app.shared.realtime.channels import queue

LIST = LiveList("audit", "audit.view")
CHANGED = "audit.changed"
# REQ-AUD-017: its own list, joined only with audit.view_personal_data_access.
ACCESS_LIST = LiveList("personal_data_access", "audit.view_personal_data_access")
ACCESS_CHANGED = "personal_data_access.changed"


async def _changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(queue(envelope.tenant_id, LIST.name), CHANGED, coalesce=True)]
    )


async def _access_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    channel = queue(envelope.tenant_id, ACCESS_LIST.name)
    return RealtimeEffects(publications=[Publication(channel, ACCESS_CHANGED, coalesce=True)])


CHANNELS = [LIST.spec(), ACCESS_LIST.spec()]
ROUTES = [
    RealtimeRoute(
        (
            "audit.entry.recorded",
            "audit.entries.sealed",
            "audit.verification.completed",
            "audit.alert.raised",
            "audit.export.finished",
            "audit.settings.changed",
            "audit.archive.updated",
        ),
        _changed,
    ),
    RealtimeRoute(("audit.personal_data_access.recorded",), _access_changed),
]
