"""Assets on realtime (WP-011 pattern; docs/architecture/realtime.md).

- The catalogue (product types, products, states, life cycles, settings) is tenant set-up that
  every asset screen reads: a change goes to the tenant-wide channel with no IDs, and open
  screens refetch through the API, which checks permissions (as knowledge does, D-120).
- An asset change goes to the asset list (the whole list, and its site's) and to the asset's own
  channel, with the ID, the changed field names and the version only (§8.2).

WP-049b s2: cost lines and notes go to the asset's own channel (`fields`: costs or notes).

WP-049b s1: consumables and stock go to the tenant channel with the consumable's ID
(`assets.consumables_changed`), bookings to the tenant channel, the asset's own channel and the
booker's personal channel (`assets.bookings_changed`), minimum-stock rules as set-up.

WP-049b s3: an audit's changes go to its own channel (managers and its auditors) and, as IDs,
to the tenant channel for the audit lists; label jobs to their requester's personal channel;
scans to the asset's channel (`fields`: scans).

Channels this module decides about:
    t:{tenant}:queue:assets…    the staff list (LiveList), per site
    t:{tenant}:asset:{id}       one asset, for whoever may see it
    t:{tenant}:asset_audit:{id} one audit, for managers and its named auditors
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets.infra.models import Asset, AssetAudit
from app.modules.assets.service.assets import ASSETS, MANAGE, VIEW
from app.modules.assets.service.audits import is_auditor
from app.modules.assets.service.linked import assets_of_work_item
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


# WP-049b s3: an audit's own channel (REQ-AST-043 AC3): progress for every auditor, live.
AUDIT_KIND = "asset_audit"
AUDIT_CHANGED = "assets.audit_changed"
AUDITS_CHANGED = "assets.audits_changed"
LABELS_CHANGED = "assets.labels_changed"
SCANS_FIELD = "scans"


async def _audit_channel(request: ChannelRequest) -> ChannelAccess | None:
    """Managers and the audit's named auditors (who hold assets.view) may follow it."""
    try:
        audit_id = uuid.UUID(request.channel.key or "")
    except ValueError:
        return None
    subject = request.subject
    if not subject.holds(VIEW):
        return None
    found = await request.session.scalar(select(AssetAudit.id).where(AssetAudit.id == audit_id))
    if found is None:
        return None
    if subject.holds(MANAGE) or await is_auditor(request.session, audit_id, subject.user_id):
        return ChannelAccess(presence=True)
    return None


CHANNELS = [
    LIST.spec(),
    ChannelSpec(kind=RECORD_KIND, authorize=_record_channel),
    ChannelSpec(kind=AUDIT_KIND, authorize=_audit_channel),
]


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


# WP-049b s2: a cost line or a note changed. The asset's page refreshes that tab (the changed
# part's name in `fields`: "costs" or "notes"); IDs only, amounts and text through the API.
_PARTS = {"assets.cost.changed": ("costs", "cost_id"), "assets.note.changed": ("notes", "note_id")}


async def _part_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    part, key = _PARTS[envelope.event_type]
    asset_id = uuid.UUID(str(envelope.payload["asset_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                record(envelope.tenant_id, RECORD_KIND, asset_id),
                ASSET_CHANGED,
                ids=(str(asset_id), str(envelope.payload[key])),
                fields=(part,),
                actor_id=_actor(envelope),
            )
        ]
    )


async def _audit_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """An audit or one of its items changed: its page (progress, items) and the audit lists."""
    del session
    payload = envelope.payload
    audit_id = uuid.UUID(str(payload["audit_id"]))
    item = payload.get("item_id")
    fields = ("items", "progress") if item is not None else tuple(payload.get("changed_fields", ()))
    ids = (str(audit_id),) if item is None else (str(audit_id), str(item))
    publications = [
        Publication(
            record(envelope.tenant_id, AUDIT_KIND, audit_id),
            AUDIT_CHANGED,
            ids=ids,
            fields=(*fields, "progress") if "progress" not in fields else fields,
            version=envelope.aggregate_version if item is None else None,
            actor_id=_actor(envelope),
        ),
        # The lists refetch through the API, which checks who may see which audit. IDs only.
        Publication(broadcast(envelope.tenant_id), AUDITS_CHANGED, ids=(str(audit_id),)),
    ]
    asset = payload.get("asset_id")
    if item is not None and asset is not None and payload.get("action") == "fixed":
        publications.append(
            Publication(
                record(envelope.tenant_id, RECORD_KIND, uuid.UUID(str(asset))),
                ASSET_CHANGED,
                ids=(str(asset),),
                fields=("audit",),
            )
        )
    return RealtimeEffects(publications=publications)


async def _label_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A label job was asked for or finished: its requester's screens refresh. IDs only."""
    del session
    payload = envelope.payload
    person = uuid.UUID(str(payload["requested_by"]))
    return RealtimeEffects(
        publications=[
            Publication(
                personal(envelope.tenant_id, person), LABELS_CHANGED, ids=(str(payload["job_id"]),)
            )
        ]
    )


# WP-049b S4b: a bulk job's or an import's progress, to the person who asked for it. The assets
# a job changes reach the lists through their own `assets.asset.changed` (coalesced).
BULK_PROGRESS = "assets.bulk_progress"
IMPORT_PROGRESS = "assets.import_progress"


async def _job_progressed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A bulk job or an import moved on: its requester's screens refresh. IDs only."""
    del session
    payload = envelope.payload
    person = uuid.UUID(str(payload["requested_by"]))
    bulk = envelope.event_type == "assets.bulk_job.progressed"
    job_id = str(payload["job_id"] if bulk else payload["import_id"])
    return RealtimeEffects(
        publications=[
            Publication(
                personal(envelope.tenant_id, person),
                BULK_PROGRESS if bulk else IMPORT_PROGRESS,
                ids=(job_id,),
            )
        ]
    )


async def _scan_recorded(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A scan of an asset was recorded: its Scans tab refreshes. IDs only."""
    del session
    asset_id = uuid.UUID(str(envelope.payload["asset_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                record(envelope.tenant_id, RECORD_KIND, asset_id),
                ASSET_CHANGED,
                ids=(str(asset_id), str(envelope.payload["scan_id"])),
                fields=(SCANS_FIELD,),
            )
        ]
    )


# WP-049b s4a (REQ-AST-044): the linked records panel counts live. A link made or removed names
# the asset; a status change of a linked work item reaches its assets through lane A's port
# (none registered yet: nothing to send). `fields`: linked. IDs only; counts through the API.
LINKED_FIELD = "linked"


def _linked(tenant: uuid.UUID, asset_id: uuid.UUID, work_item: str) -> Publication:
    return Publication(
        record(tenant, RECORD_KIND, asset_id),
        ASSET_CHANGED,
        ids=(str(asset_id), work_item),
        fields=(LINKED_FIELD,),
    )


async def _link_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    payload = envelope.payload
    asset_id = uuid.UUID(str(payload["asset_id"]))
    return RealtimeEffects(
        publications=[_linked(envelope.tenant_id, asset_id, str(payload["work_item_id"]))]
    )


async def _work_item_moved(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    work_item = uuid.UUID(str(envelope.payload["work_item_id"]))
    return RealtimeEffects(
        publications=[
            _linked(envelope.tenant_id, asset_id, str(work_item))
            for asset_id in await assets_of_work_item(session, work_item)
        ]
    )


ROUTES = [
    RealtimeRoute(("work_items.asset_link.changed",), _link_changed),
    RealtimeRoute(("work_items.work_item.status_changed",), _work_item_moved),
    RealtimeRoute(("assets.audit.changed", "assets.audit.item_changed"), _audit_changed),
    RealtimeRoute(("assets.label.requested", "assets.label.printed"), _label_changed),
    RealtimeRoute(("assets.scan.recorded",), _scan_recorded),
    RealtimeRoute(("assets.bulk_job.progressed", "assets.import.progressed"), _job_progressed),
    # The overdue-scan rule is set-up, like the catalogue: the settings screen refetches.
    RealtimeRoute(("assets.overdue_rule.changed",), _catalogue_changed),
    RealtimeRoute(tuple(_PARTS), _part_changed),
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
