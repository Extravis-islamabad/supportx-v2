"""Assets on realtime (WP-011 pattern; docs/architecture/realtime.md).

- The catalogue (product types, products, states, life cycles, settings) is tenant set-up that
  every asset screen reads: a change goes to the tenant-wide channel with no IDs, and open
  screens refetch through the API, which checks permissions (as knowledge does, D-120).
- An asset change goes to the asset list (the whole list, and its site's) and to the asset's own
  channel, with the ID, the changed field names and the version only (§8.2).

Channels this module decides about:
    t:{tenant}:queue:assets…    the staff list (LiveList), per site
    t:{tenant}:asset:{id}       one asset, for whoever may see it
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets.infra.models import Asset
from app.modules.assets.service.assets import ASSETS, VIEW
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

CATALOGUE_CHANGED = "assets.catalogue_changed"
ASSET_CHANGED = "assets.asset_changed"
RECORD_KIND = "asset"
LIST = LiveList("assets", VIEW)


async def _record_channel(request: ChannelRequest) -> ChannelAccess | None:
    try:
        asset_id = uuid.UUID(request.channel.key or "")
    except ValueError:
        return None
    subject = request.subject
    if subject.holds(VIEW) and await authorize_stored(
        request.session, subject, VIEW, ASSETS, Asset.id, asset_id
    ):
        return ChannelAccess(presence=True)
    return None


CHANNELS = [LIST.spec(), ChannelSpec(kind=RECORD_KIND, authorize=_record_channel)]


async def _catalogue_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), CATALOGUE_CHANGED)]
    )


def _actor(envelope: EventEnvelope) -> str | None:
    return envelope.actor.id if envelope.actor.type == "user" else None


async def _asset_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    payload = envelope.payload
    asset_id = uuid.UUID(str(payload["asset_id"]))
    site = payload.get("site_id")
    actor = _actor(envelope)
    return RealtimeEffects(
        publications=[
            Publication(
                record(envelope.tenant_id, RECORD_KIND, asset_id),
                ASSET_CHANGED,
                ids=(str(asset_id),),
                fields=tuple(payload.get("changed_fields", ())),
                version=envelope.aggregate_version,
                actor_id=actor,
            ),
            *LIST.publications(
                envelope.tenant_id,
                ASSET_CHANGED,
                asset_id,
                sites=() if site is None else (uuid.UUID(str(site)),),
                actor_id=actor,
            ),
        ]
    )


ROUTES = [
    RealtimeRoute(("assets.catalogue.changed", "assets.product.changed"), _catalogue_changed),
    RealtimeRoute(("assets.asset.changed",), _asset_changed),
]
