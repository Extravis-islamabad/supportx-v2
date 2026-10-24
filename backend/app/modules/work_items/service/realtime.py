"""Work items on realtime (WP-020; architecture.md §8.1; docs/architecture/realtime.md).

Channels this module decides about:

    t:{tenant}:wi:{id}                         one work item (staff in view scope, with presence)
    t:{tenant}:queue:incidents…                the incident lists, one channel per audience:
                                               all / site / group / own (personal) and the
                                               unassigned queue of each site (D-052)

A change is published to the audiences the record belongs to *now and before the change*, so a
row that moved from group A to group B leaves A's list and joins B's (REQ-WI-005 AC2). Payloads
carry the ID, changed field names and the version; screens refetch through the API, where the
scope rules apply again, so a channel never reveals a record's content.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import authorize_stored
from app.modules.work_items.domain.types import INCIDENT, TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service.access import RESOURCE
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

RECORD_KIND = "wi"
CHANGED = "work_items.changed"
SETTINGS_CHANGED = "work_items.settings_changed"
LISTS: dict[WorkItemTypeCode, LiveList] = {
    code: LiveList(wtype.path, wtype.permission("view"), unassigned_by_site=True)
    for code, wtype in TYPES.items()
}


async def _record_channel(request: ChannelRequest) -> ChannelAccess | None:
    try:
        record_id = uuid.UUID(request.channel.key or "")
    except ValueError:
        return None
    kind = await request.session.scalar(select(WorkItem.type).where(WorkItem.id == record_id))
    wtype: WorkItemType | None = TYPES.get(WorkItemTypeCode(kind)) if kind else None
    if wtype is None:
        return None
    permission = wtype.permission("view")
    subject = request.subject
    if subject.holds(permission) and await authorize_stored(
        request.session, subject, permission, RESOURCE, WorkItem.id, record_id
    ):
        return ChannelAccess(presence=True)
    return None


CHANNELS = [
    *(lst.spec() for lst in LISTS.values()),
    ChannelSpec(kind=RECORD_KIND, authorize=_record_channel),
]


def _actor(envelope: EventEnvelope) -> str | None:
    return envelope.actor.id if envelope.actor.type == "user" else None


def _uuid(value: object) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


async def _work_item_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    tenant = envelope.tenant_id
    payload = envelope.payload
    record_id = uuid.UUID(str(payload["work_item_id"]))
    row = await session.scalar(select(WorkItem).where(WorkItem.id == record_id))
    if row is None:  # pragma: no cover - rows are never hard-deleted by the API
        return RealtimeEffects()
    live = LISTS.get(WorkItemTypeCode(row.type), LISTS[INCIDENT.code])
    before = payload.get("audience_before") or {}
    # Where it is now, where the event says it went, and where it was before (events may be routed
    # after later changes, so the row alone is not enough).
    sites = {s for s in (row.site_id, _uuid(before.get("site_id"))) if s}
    groups = {
        g
        for g in (row.group_id, _uuid(payload.get("group_id")), _uuid(before.get("group_id")))
        if g
    }
    owners = {
        o
        for o in (
            row.requester_id,
            row.on_behalf_of_id,
            row.technician_id,
            _uuid(payload.get("technician_id")),
            _uuid(before.get("technician_id")),
        )
        if o
    }
    unassigned: set[uuid.UUID] = set()
    if row.group_id is None and row.technician_id is None and row.site_id:
        unassigned.add(row.site_id)
    if before.get("unassigned") and before.get("site_id"):
        unassigned.add(uuid.UUID(str(before["site_id"])))
    fields = tuple(payload.get("changed_fields", ()))
    if "to_status" in payload:
        fields = ("status",)
    elif "technician_id" in payload and "changed_fields" not in payload:
        fields = ("group_id", "technician_id")
    publications = [
        Publication(
            record(tenant, RECORD_KIND, record_id),
            CHANGED,
            ids=(str(record_id),),
            fields=fields,
            version=envelope.aggregate_version,
            actor_id=_actor(envelope),
        ),
        *live.publications(
            tenant,
            CHANGED,
            record_id,
            sites=sorted(sites, key=str),
            groups=sorted(groups, key=str),
            owners=sorted(owners, key=str),
            unassigned_sites=sorted(unassigned, key=str),
            actor_id=_actor(envelope),
        ),
    ]
    return RealtimeEffects(publications=publications)


async def _settings_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Configuration changed: open forms reload their pick lists (no record data)."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), SETTINGS_CHANGED)]
    )


ROUTES = [
    RealtimeRoute(
        (
            "work_items.work_item.created",
            "work_items.work_item.updated",
            "work_items.work_item.status_changed",
            "work_items.work_item.assigned",
            "work_items.work_item.deleted",
            "work_items.work_item.restored",
        ),
        _work_item_changed,
    ),
    RealtimeRoute(("work_items.settings.changed",), _settings_changed),
]
