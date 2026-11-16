"""The CMDB on realtime (WP-011 pattern; docs/architecture/realtime.md; architecture.md §8.1).

Channels this module decides about:
    t:{tenant}:queue:cmdb…     the CI list, one channel per audience (LiveList: all, each site,
                               each group, the owner's personal channel)
    t:{tenant}:ci:{id}         one CI, for whoever may see it (with presence)
    t:{tenant}:broadcast       (identity_access) "the CMDB's types, states or settings changed",
                               with no names: open screens refetch them

Payloads carry IDs, changed field names and the version only (rule c).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cmdb.infra.models import Ci
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
    record,
)

RECORD_KIND = "ci"
LIST = LiveList("cmdb", VIEW)
CHANGED = "cmdb.ci.changed"
CONFIG_CHANGED = "cmdb.config_changed"


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


CHANNELS = [LIST.spec(), ChannelSpec(kind=RECORD_KIND, authorize=_record_channel)]


def _actor(envelope: EventEnvelope) -> str | None:
    return envelope.actor.id if envelope.actor.type == "user" else None


async def _ci_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    tenant = envelope.tenant_id
    ci_id = uuid.UUID(str(envelope.payload["ci_id"]))
    row = await session.scalar(select(Ci).where(Ci.id == ci_id))
    if row is None:  # pragma: no cover - CIs are never hard-deleted by the API
        return RealtimeEffects()
    groups = sorted({g for g in (row.owner_group_id, row.managed_by_group_id) if g}, key=str)
    publications = [
        Publication(
            record(tenant, RECORD_KIND, ci_id),
            CHANGED,
            ids=(str(ci_id),),
            fields=tuple(envelope.payload.get("changed_fields", ())),
            version=envelope.aggregate_version,
            actor_id=_actor(envelope),
        ),
        *LIST.publications(
            tenant,
            CHANGED,
            ci_id,
            sites=[row.site_id] if row.site_id else [],
            groups=groups,
            owners=[row.owner_user_id] if row.owner_user_id else [],
            actor_id=_actor(envelope),
        ),
    ]
    return RealtimeEffects(publications=publications)


async def _config_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), CONFIG_CHANGED)]
    )


ROUTES = [
    RealtimeRoute(
        ("cmdb.ci.created", "cmdb.ci.updated", "cmdb.ci.deleted", "cmdb.ci.restored"),
        _ci_changed,
    ),
    RealtimeRoute(("cmdb.config.changed",), _config_changed),
]
