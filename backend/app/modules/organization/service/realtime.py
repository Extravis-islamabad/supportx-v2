"""Organization events on realtime (WP-011 pattern; docs/architecture/realtime.md).

Everything goes to the tenant-wide broadcast channel with no IDs or values; each open screen
refetches. A saved branding reaches every console and portal (REQ-ADM-055 AC1, REQ-PRT-016 AC1);
domain changes refresh an open domains list (WP-017); a change to a site, group, department or
desk reloads the structure lists and pickers (WP-021). The payload rule (§8.2) holds anyway.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

BRANDING_CHANGED = "organization.branding_changed"
DOMAINS_CHANGED = "organization.domains_changed"
STRUCTURE_CHANGED = "organization.structure_changed"


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


async def _structure_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), STRUCTURE_CHANGED)]
    )


ROUTES = [
    RealtimeRoute(("organization.branding.changed",), _branding_changed),
    RealtimeRoute(("organization.domain.changed",), _domains_changed),
    RealtimeRoute(
        (
            "organization.site.changed",
            "organization.support_group.changed",
            "organization.department.changed",
            "organization.desk.changed",
        ),
        _structure_changed,
    ),
]
