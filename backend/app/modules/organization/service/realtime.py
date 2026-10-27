"""Organization events on realtime (WP-011 pattern; docs/architecture/realtime.md).

A saved branding reaches every open console and portal of the tenant through the tenant-wide
broadcast channel, with no IDs or values: each screen refetches its brand (REQ-ADM-055 AC1,
REQ-PRT-016 AC1). Domain changes likewise refresh an open domains list. The brand is not
sensitive, but the payload rule (§8.2) holds anyway.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

BRANDING_CHANGED = "organization.branding_changed"
DOMAINS_CHANGED = "organization.domains_changed"


async def _branding_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), BRANDING_CHANGED)]
    )


async def _domains_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), DOMAINS_CHANGED)]
    )


ROUTES = [
    RealtimeRoute(("organization.branding.changed",), _branding_changed),
    RealtimeRoute(("organization.domain.changed",), _domains_changed),
]
