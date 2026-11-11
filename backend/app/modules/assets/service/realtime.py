"""Assets on realtime (WP-011 pattern; docs/architecture/realtime.md).

- The catalogue (product types, products, states, life cycles, settings) is tenant set-up that
  every asset screen reads: a change goes to the tenant-wide channel with no IDs, and open
  screens refetch through the API, which checks permissions (as knowledge does, D-120).
- An asset change goes to the asset list (the whole list, and its site's) and to the asset's own
  channel, with the ID, the changed field names and the version only (§8.2).

WP-049b s1: consumables and stock go to the tenant channel with the consumable's ID
(`assets.consumables_changed`), bookings to the tenant channel, the asset's own channel and the
booker's personal channel (`assets.bookings_changed`), minimum-stock rules as set-up.

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
    personal,
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


# "My assets" (REQ-AST-024 AC3): the people concerned hear of it on their own channel.
MINE_CHANGED = "assets.mine_changed"


async def _holder_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """An asset changed hands: the people before and after refresh their own list. IDs only."""
    del session
    asset_id = str(envelope.payload["asset_id"])
    return RealtimeEffects(
        publications=[
            Publication(
                personal(envelope.tenant_id, uuid.UUID(str(p))), MINE_CHANGED, ids=(asset_id,)
            )
            for p in envelope.payload.get("people", [])
        ]
    )


async def _acknowledgement_changed(
    envelope: EventEnvelope, session: AsyncSession
) -> RealtimeEffects:
    """Asked, accepted or disputed: the person's list and the asset's page refresh. IDs only."""
    del session
    payload = envelope.payload
    asset_id = uuid.UUID(str(payload["asset_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                personal(envelope.tenant_id, uuid.UUID(str(payload["user_id"]))),
                MINE_CHANGED,
                ids=(str(asset_id),),
            ),
            Publication(
                record(envelope.tenant_id, RECORD_KIND, asset_id),
                ASSET_CHANGED,
                ids=(str(asset_id),),
                fields=("acknowledgement",),
            ),
        ]
    )


GROUPS_CHANGED = "assets.groups_changed"


async def _group_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Groups and their counts refresh on every staff screen of the tenant. IDs only."""
    del session
    return RealtimeEffects(
        publications=[
            Publication(
                broadcast(envelope.tenant_id),
                GROUPS_CHANGED,
                ids=(str(envelope.payload["group_id"]),),
            )
        ]
    )


LOANS_CHANGED = "assets.loans_changed"


async def _loan_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A loan changed: the register refreshes on staff screens, and the borrower's own list.

    Made, returned, closed, due or overdue. IDs only; the API checks who may read them.
    """
    del session
    loan_id = str(envelope.payload["loan_id"])
    borrower = uuid.UUID(str(envelope.payload["borrower_id"]))
    return RealtimeEffects(
        publications=[
            Publication(broadcast(envelope.tenant_id), LOANS_CHANGED, ids=(loan_id,)),
            Publication(personal(envelope.tenant_id, borrower), MINE_CHANGED, ids=(loan_id,)),
        ]
    )


CONSUMABLES_CHANGED = "assets.consumables_changed"


async def _consumable_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Stock and consumables (REQ-AST-033..035): every open consumables screen refreshes.

    The consumable's ID only; quantities are read through the API, which checks permissions.
    """
    del session
    return RealtimeEffects(
        publications=[
            Publication(
                broadcast(envelope.tenant_id),
                CONSUMABLES_CHANGED,
                ids=(str(envelope.payload["consumable_id"]),),
                version=envelope.aggregate_version,
                actor_id=_actor(envelope),
            )
        ]
    )


BOOKINGS_CHANGED = "assets.bookings_changed"


async def _booking_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A booking (REQ-AST-032) changed: who shows it hears of it. IDs only.

    The calendar and loan screens, the asset's page, and the booker's own list in the portal.
    """
    del session
    payload = envelope.payload
    booking_id = str(payload["booking_id"])
    asset_id = uuid.UUID(str(payload["asset_id"]))
    borrower = uuid.UUID(str(payload["borrower_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                broadcast(envelope.tenant_id), BOOKINGS_CHANGED, ids=(booking_id, str(asset_id))
            ),
            Publication(
                record(envelope.tenant_id, RECORD_KIND, asset_id),
                ASSET_CHANGED,
                ids=(str(asset_id),),
                fields=("booking",),
            ),
            Publication(personal(envelope.tenant_id, borrower), MINE_CHANGED, ids=(booking_id,)),
        ]
    )


ROUTES = [
    RealtimeRoute(
        ("assets.consumable.changed", "assets.stock.moved", "assets.stock.low"),
        _consumable_changed,
    ),
    RealtimeRoute(("assets.booking.changed",), _booking_changed),
    # Minimum-stock rules are set-up, like the catalogue: every asset screen refetches.
    RealtimeRoute(("assets.stock_rule.changed",), _catalogue_changed),
    RealtimeRoute(("assets.loan.changed",), _loan_changed),
    RealtimeRoute(("assets.group.changed",), _group_changed),
    RealtimeRoute(("assets.catalogue.changed", "assets.product.changed"), _catalogue_changed),
    RealtimeRoute(("assets.asset.changed",), _asset_changed),
    RealtimeRoute(("assets.holder.changed",), _holder_changed),
    RealtimeRoute(("assets.acknowledgement.changed",), _acknowledgement_changed),
]
