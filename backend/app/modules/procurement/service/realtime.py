"""Vendors on realtime (WP-011 pattern; docs/architecture/realtime.md).

Vendors are shared reference data every purchasing and asset screen reads: a change goes to the
tenant-wide channel with the vendor's ID and changed field names, and open screens refetch
through the API, which checks permissions.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

VENDORS_CHANGED = "procurement.vendors_changed"


async def _vendor_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    vendor = str(envelope.payload["vendor_id"])
    return RealtimeEffects(
        publications=[
            Publication(
                broadcast(envelope.tenant_id),
                VENDORS_CHANGED,
                ids=(vendor,),
                fields=tuple(envelope.payload.get("changed_fields", ())),
                version=envelope.aggregate_version,
            )
        ]
    )


ROUTES = [RealtimeRoute(("procurement.vendor.changed",), _vendor_changed)]
