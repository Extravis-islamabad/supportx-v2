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

Followers who kept access after a hand-over (D-068) are an audience of their own: their personal
channel hears about the record like the requester's and technician's. The conversation (WP-020b)
publishes `work_items.conversation_changed` on the record channel with the entry ID only, and
`work_items.followers_changed` when someone follows or stops; typing signals go straight to the
record channel from the API (`TYPING`), as they change nothing stored.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import authorize_stored
from app.modules.work_items.domain.types import INCIDENT, TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import WorkItem, WorkItemFollower, WorkItemTask
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
    personal,
    record,
)

RECORD_KIND = "wi"
CHANGED = "work_items.changed"
SETTINGS_CHANGED = "work_items.settings_changed"
CONVERSATION_CHANGED = "work_items.conversation_changed"
FOLLOWERS_CHANGED = "work_items.followers_changed"
TYPING = "work_items.typing"
TEMPLATES_CHANGED = "work_items.reply_templates_changed"
VIEWS_CHANGED = "work_items.views_changed"
LIST_SETTINGS_CHANGED = "work_items.list_settings_changed"
BULK_PROGRESS = "work_items.bulk_progress"
LISTS_CHANGED = "work_items.lists_changed"
# Correlation ID of a bulk job's events (service/bulk.py): lists refresh once per batch instead.
BULK_PREFIX = "bulk:"
PART_CHANGED = "work_items.part_changed"
MY_TASKS_CHANGED = "work_items.my_tasks_changed"
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
    owners |= await _followers_with_access(session, record_id)
    fields = tuple(payload.get("changed_fields", ()))
    if "to_status" in payload:
        fields = ("status",)
    elif "technician_id" in payload and "changed_fields" not in payload:
        fields = ("group_id", "technician_id")
    own = Publication(
        record(tenant, RECORD_KIND, record_id),
        CHANGED,
        ids=(str(record_id),),
        fields=fields,
        version=envelope.aggregate_version,
        actor_id=_actor(envelope),
    )
    if (envelope.correlation_id or "").startswith(BULK_PREFIX):  # the batch refreshes lists
        return RealtimeEffects(publications=[own])
    publications = [
        own,
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


async def _followers_with_access(session: AsyncSession, record_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await session.scalars(
        select(WorkItemFollower.user_id).where(
            WorkItemFollower.work_item_id == record_id,
            WorkItemFollower.grants_access.is_(True),
            WorkItemFollower.deleted_at.is_(None),
        )
    )
    return set(rows)


async def _conversation_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A reply or note was added or changed visibility: open timelines refetch it."""
    del session
    payload = envelope.payload
    record_id = uuid.UUID(str(payload["work_item_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                record(envelope.tenant_id, RECORD_KIND, record_id),
                CONVERSATION_CHANGED,
                ids=(str(payload["entry_id"]),),
                actor_id=_actor(envelope),
            )
        ]
    )


async def _followers_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Someone follows or stopped: the record's followers panel and that person's lists.

    A follower who loses the access the follow gave them is cut and rejoins with fresh tokens, so
    their subscription to the record channel ends (architecture.md §8.2).
    """
    tenant = envelope.tenant_id
    payload = envelope.payload
    record_id = uuid.UUID(str(payload["work_item_id"]))
    user_id = uuid.UUID(str(payload["user_id"]))
    kind = await session.scalar(select(WorkItem.type).where(WorkItem.id == record_id))
    live = LISTS.get(WorkItemTypeCode(kind), LISTS[INCIDENT.code]) if kind else None
    publications = [
        Publication(
            record(tenant, RECORD_KIND, record_id),
            FOLLOWERS_CHANGED,
            ids=(str(user_id),),
            actor_id=_actor(envelope),
        )
    ]
    if live is not None and payload.get("grants_access"):
        publications += live.publications(
            tenant, CHANGED, record_id, owners=[user_id], actor_id=_actor(envelope)
        )
    removed = envelope.event_type == "work_items.follower.removed"
    revoke = [user_id] if removed and payload.get("grants_access") else []
    return RealtimeEffects(publications=publications, revoke_users=revoke)


async def _templates_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Reply templates changed: open composers reload the list (no content)."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), TEMPLATES_CHANGED)]
    )


async def _settings_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Configuration changed: open forms reload their pick lists (no record data)."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), SETTINGS_CHANGED)]
    )


async def _view_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A saved view changed: everyone's view menu for a shared one, else its owner's."""
    del session
    payload = envelope.payload
    owner = uuid.UUID(str(payload["owner_id"]))
    shared = payload.get("visibility") == "shared"
    channel = broadcast(envelope.tenant_id) if shared else personal(envelope.tenant_id, owner)
    return RealtimeEffects(
        publications=[
            Publication(
                channel, VIEWS_CHANGED, ids=(str(payload["view_id"]),), actor_id=_actor(envelope)
            )
        ]
    )


async def _list_settings_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A user's list settings changed: their other windows reload them."""
    del session
    payload = envelope.payload
    user = uuid.UUID(str(payload["user_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                personal(envelope.tenant_id, user),
                LIST_SETTINGS_CHANGED,
                ids=(str(payload["view_key"]),),
                actor_id=_actor(envelope),
            )
        ]
    )


async def _bulk_progressed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A bulk job moved on: its requester's progress, and one list refresh per batch."""
    del session
    payload = envelope.payload
    publications = [
        Publication(
            broadcast(envelope.tenant_id), LISTS_CHANGED, ids=(str(payload["type"]),), coalesce=True
        )
    ]
    if requester := _uuid(payload.get("requested_by")):
        publications.insert(
            0,
            Publication(
                personal(envelope.tenant_id, requester),
                BULK_PROGRESS,
                ids=(str(payload["job_id"]),),
                version=envelope.aggregate_version,
            ),
        )
    return RealtimeEffects(publications=publications)


async def _part_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A task, worklog or link changed: the record's screens, and a task owner's own list."""
    payload = envelope.payload
    record_id = uuid.UUID(str(payload["work_item_id"]))
    part_id = uuid.UUID(str(payload["part_id"]))
    publications = [
        Publication(
            record(envelope.tenant_id, RECORD_KIND, record_id),
            PART_CHANGED,
            ids=(str(part_id),),
            fields=(str(payload["part"]),),
            actor_id=_actor(envelope),
        )
    ]
    if payload["part"] == "task":
        owner = await session.scalar(
            select(WorkItemTask.owner_id).where(WorkItemTask.id == part_id)
        )
        if owner is not None:
            publications.append(
                Publication(
                    personal(envelope.tenant_id, owner),
                    MY_TASKS_CHANGED,
                    ids=(str(part_id),),
                    actor_id=_actor(envelope),
                )
            )
    return RealtimeEffects(publications=publications)


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
    RealtimeRoute(
        ("work_items.conversation.added", "work_items.conversation.visibility_changed"),
        _conversation_changed,
    ),
    RealtimeRoute(("work_items.follower.added", "work_items.follower.removed"), _followers_changed),
    RealtimeRoute(("work_items.reply_templates.changed",), _templates_changed),
    RealtimeRoute(("work_items.view.changed",), _view_changed),
    RealtimeRoute(("work_items.list_settings.changed",), _list_settings_changed),
    RealtimeRoute(("work_items.bulk_job.progressed",), _bulk_progressed),
    RealtimeRoute(("work_items.part.changed",), _part_changed),
]
