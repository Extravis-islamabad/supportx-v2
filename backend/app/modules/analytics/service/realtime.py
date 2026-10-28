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


EXPORT_FINISHED = "reports.export_finished"


async def _export_finished(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Only the person who asked hears that their file is ready (or why it failed)."""
    del session
    payload = envelope.payload
    owner = uuid.UUID(str(payload["requested_by"]))
    return RealtimeEffects(
        publications=[
            Publication(
                personal(envelope.tenant_id, owner),
                EXPORT_FINISHED,
                ids=(str(payload["export_id"]),),
            )
        ]
    )


SCHEDULES_CHANGED = "reports.schedules_changed"


async def _schedule_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """The owner's schedule list refreshes: a change, or a run's result (REQ-RPT-052 AC2)."""
    del session
    payload = envelope.payload
    owner = uuid.UUID(str(payload["owner_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                personal(envelope.tenant_id, owner),
                SCHEDULES_CHANGED,
                ids=(str(payload["schedule_id"]),),
            )
        ]
    )


DASHBOARDS_CHANGED = "dashboards.changed"


async def _dashboard_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Who hears that a dashboard changed.

    A private dashboard: its owner. A shared one (or one just un-shared): everyone hears
    "dashboards changed" with its id, and screens refetch it through the API, which answers 404
    to anyone who may no longer see it (REQ-DSH-028 AC2). No names or widget definitions travel
    (rule c).
    """
    del session
    tenant = envelope.tenant_id
    payload = envelope.payload
    dashboard = str(payload["dashboard_id"])
    if payload.get("shared") or payload.get("was_shared"):
        return RealtimeEffects(
            publications=[Publication(broadcast(tenant), DASHBOARDS_CHANGED, ids=(dashboard,))]
        )
    owner = uuid.UUID(str(payload["owner_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                personal(tenant, owner),
                DASHBOARDS_CHANGED,
                ids=(dashboard,),
                actor_id=_actor(envelope),
            )
        ]
    )


async def _home_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A role's home dashboard changed: home pages refetch which dashboard they show."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), DASHBOARDS_CHANGED, coalesce=True)]
    )


ROUTES = [
    RealtimeRoute(
        (
            "analytics.report.saved",
            "analytics.report.deleted",
            "analytics.report_folder.saved",
            "analytics.report_folder.deleted",
        ),
        _report_changed,
    ),
    RealtimeRoute(("analytics.report_export.finished",), _export_finished),
    RealtimeRoute(
        ("analytics.report_schedule.saved", "analytics.report_schedule.ran"), _schedule_changed
    ),
    RealtimeRoute(("analytics.dashboard.saved", "analytics.dashboard.deleted"), _dashboard_changed),
    RealtimeRoute(("analytics.dashboard_home.changed",), _home_changed),
]
