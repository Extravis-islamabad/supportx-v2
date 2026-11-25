"""The CMDB on realtime (WP-011 pattern; docs/architecture/realtime.md; architecture.md §8.1).

Channels this module decides about:
    t:{tenant}:queue:cmdb…     the CI list, one channel per audience (LiveList: all, each site,
                               each group, the owner's personal channel)
    t:{tenant}:ci:{id}         one CI, for whoever may see it (with presence); a relationship
                               added or removed names `relationships` on both ends (S2)
    t:{tenant}:cmdb_view:{id}  one business view, for whoever may see its base CI (S2)
    t:{tenant}:user:{id}       (identity_access) an import's progress, to its importer (S4b)
    t:{tenant}:broadcast       (identity_access) "the CMDB's types, states or settings changed",
                               with no names: open screens refetch them; also "the business
                               views changed" for open view lists (S2), and "the sync rules or
                               runs changed" (S4a, no IDs): the sync screens refetch, and the
                               server decides what each reader gets

Payloads carry IDs, changed field names and the version only (rule c).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.infra.models import BusinessView, Ci
from app.modules.cmdb.service.business_views import visible_views
from app.modules.cmdb.service.catalogue import VIEW
from app.modules.cmdb.service.cis import CIS
from app.modules.identity_access import authorize_stored
from app.shared.events import EventEnvelope
from app.shared.realtime import (
    ChannelAccess,
    ChannelRequest,
    ChannelSpec,
    LiveList,
    Publication,
    RealtimeEffects,
    RealtimeRoute,
    broadcast,
    personal,
    record,
)

RECORD_KIND = "ci"
LIST = LiveList("cmdb", VIEW)
CHANGED = "cmdb.ci.changed"
CONFIG_CHANGED = "cmdb.config_changed"
RELATIONSHIPS = "relationships"  # the field a relationship change names on both CIs
DOWNTIMES = "downtimes"  # the field a downtime change names on its CI (S5b)
VIEW_KIND = "cmdb_view"
VIEW_CHANGED = "cmdb.view.changed"
VIEWS_CHANGED = "cmdb.views_changed"
SYNC_CHANGED = "cmdb.sync_changed"
IMPORT_PROGRESS = "cmdb.import_progress"  # S4b: an import moved on, to its importer only


async def _record_channel(request: ChannelRequest) -> ChannelAccess | None:
    try:
        ci_id = uuid.UUID(request.channel.key or "")
    except ValueError:
        return None
    subject = request.subject
    if subject.holds(VIEW) and await authorize_stored(
        request.session, subject, VIEW, CIS, Ci.id, ci_id
    ):
        return ChannelAccess(presence=True)
    return None


def _actor(envelope: EventEnvelope) -> str | None:
    return envelope.actor.id if envelope.actor.type == "user" else None


def _ci_publications(
    tenant: uuid.UUID, row: Ci, fields: tuple[str, ...], version: int | None, actor: str | None
) -> list[Publication]:
    """One CI's record channel and every list audience that may see it."""
    groups = sorted({g for g in (row.owner_group_id, row.managed_by_group_id) if g}, key=str)
    return [
        Publication(
            record(tenant, RECORD_KIND, row.id),
            CHANGED,
            ids=(str(row.id),),
            fields=fields,
            version=version,
            actor_id=actor,
        ),
        *LIST.publications(
            tenant,
            CHANGED,
            row.id,
            sites=[row.site_id] if row.site_id else [],
            groups=groups,
            owners=[row.owner_user_id] if row.owner_user_id else [],
            actor_id=actor,
        ),
    ]


async def _ci_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    ci_id = uuid.UUID(str(envelope.payload["ci_id"]))
    row = await session.scalar(select(Ci).where(Ci.id == ci_id))
    if row is None:  # pragma: no cover - CIs are never hard-deleted by the API
        return RealtimeEffects()
    fields = tuple(envelope.payload.get("changed_fields", ()))
    return RealtimeEffects(
        publications=_ci_publications(
            envelope.tenant_id, row, fields, envelope.aggregate_version, _actor(envelope)
        )
    )


async def _relationships_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Both ends of every link added or removed (REQ-CMDB-007 AC3).

    Each CI's record channel with `relationships` and its new version, and the list audiences
    that may see it. A map listens on its CIs' list audience and patches or refetches (§8.3),
    never one channel per node (lane C's condition 9).
    """
    ids = [
        uuid.UUID(str(i))
        for i in (envelope.payload["ci_id"], *envelope.payload.get("other_ci_ids", ()))
    ]
    rows = await session.scalars(select(Ci).where(Ci.id.in_(ids)).order_by(Ci.id))
    publications = [
        p
        for row in rows
        for p in _ci_publications(
            envelope.tenant_id, row, (RELATIONSHIPS,), row.version, _actor(envelope)
        )
    ]
    return RealtimeEffects(publications=publications)


async def _downtimes_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A CI's downtimes changed or moved state: its record channel refetches them (§8.3)."""
    row = await session.scalar(select(Ci).where(Ci.id == uuid.UUID(str(envelope.payload["ci_id"]))))
    if row is None:
        return RealtimeEffects(publications=[])
    return RealtimeEffects(
        publications=list(
            _ci_publications(envelope.tenant_id, row, (DOWNTIMES,), row.version, _actor(envelope))
        )
    )


async def _view_channel(request: ChannelRequest) -> ChannelAccess | None:
    try:
        view_id = uuid.UUID(request.channel.key or "")
    except ValueError:
        return None
    subject = request.subject
    if not subject.holds(VIEW):
        return None
    seen = await request.session.scalar(
        visible_views(subject).with_only_columns(BusinessView.id).where(BusinessView.id == view_id)
    )
    return ChannelAccess() if seen is not None else None


async def _view_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """The view's own channel, and "views changed" (no names) for open view lists."""
    del session
    view_id = uuid.UUID(str(envelope.payload["view_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                record(envelope.tenant_id, VIEW_KIND, view_id),
                VIEW_CHANGED,
                ids=(str(view_id),),
                fields=tuple(envelope.payload.get("changed_fields", ())),
                version=envelope.aggregate_version,
                actor_id=_actor(envelope),
            ),
            Publication(broadcast(envelope.tenant_id), VIEWS_CHANGED),
        ]
    )


async def _config_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), CONFIG_CHANGED)]
    )


async def _sync_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A rule or a run changed: open sync screens refetch (no IDs on the tenant channel)."""
    del session
    return RealtimeEffects(publications=[Publication(broadcast(envelope.tenant_id), SYNC_CHANGED)])


async def _import_progressed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """An import moved on: its importer's screens refresh (IDs only, S4b)."""
    del session
    payload = envelope.payload
    person = uuid.UUID(str(payload["requested_by"]))
    return RealtimeEffects(
        publications=[
            Publication(
                personal(envelope.tenant_id, person),
                IMPORT_PROGRESS,
                ids=(str(payload["import_id"]),),
            )
        ]
    )


CHANNELS = [
    LIST.spec(),
    ChannelSpec(kind=RECORD_KIND, authorize=_record_channel),
    ChannelSpec(kind=VIEW_KIND, authorize=_view_channel),
]

ROUTES = [
    RealtimeRoute(
        ("cmdb.ci.created", "cmdb.ci.updated", "cmdb.ci.deleted", "cmdb.ci.restored"),
        _ci_changed,
    ),
    RealtimeRoute(("cmdb.config.changed",), _config_changed),
    RealtimeRoute(("cmdb.relationship.changed",), _relationships_changed),
    RealtimeRoute(("cmdb.business_view.changed",), _view_changed),
    RealtimeRoute(("cmdb.sync_rule.changed", "cmdb.sync_run.changed"), _sync_changed),
    RealtimeRoute(("cmdb.import.progressed",), _import_progressed),
    RealtimeRoute(("cmdb.downtime.changed",), _downtimes_changed),
]
