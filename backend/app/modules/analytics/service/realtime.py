"""Reports on realtime (WP-035; architecture.md §8, CLAUDE.md rule c).

The reports home updates live without a new channel kind:
    t:{tenant}:user:{owner}   a private report changed: only its owner hears of it (with its id)
    t:{tenant}:broadcast      a shared report or a folder changed: "reports changed", no ids;
                              screens refetch the library, where the API applies who sees what
Report *results* follow the lists they count (the entity's own list channels, joined by the
viewer), so a number on screen changes when a record changes (REQ-RPT-008 AC2).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast, personal

CHANGED = "reports.changed"


def _actor(envelope: EventEnvelope) -> str | None:
    return envelope.actor.id if envelope.actor.type == "user" else None


async def _report_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session  # the payload says where the report lives; nothing to read
    tenant = envelope.tenant_id
    payload = envelope.payload
    shared = Publication(broadcast(tenant), CHANGED, coalesce=True)
    if payload.get("folder_id") is not None or "owner_id" not in payload:
        return RealtimeEffects(publications=[shared])
    owner = uuid.UUID(str(payload["owner_id"]))
    own = Publication(
        personal(tenant, owner),
        CHANGED,
        ids=(str(payload["report_id"]),),
        actor_id=_actor(envelope),
    )
    # A report taken out of a shared folder: its former viewers must see it go.
    moved = "folder_id" in payload.get("changed_fields", ())
    return RealtimeEffects(publications=[own, shared] if moved else [own])


ROUTES = [
    RealtimeRoute(
        (
            "analytics.report.saved",
            "analytics.report.deleted",
            "analytics.report_folder.saved",
            "analytics.report_folder.deleted",
        ),
        _report_changed,
    )
]
