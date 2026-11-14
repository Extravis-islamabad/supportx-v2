"""Work items on realtime (WP-020; architecture.md §8.1; docs/architecture/realtime.md).

Channels this module decides about:

    t:{tenant}:wi:{id}                         one work item (staff in view scope, with presence)
    t:{tenant}:portal_wi:{id}                  the same record for its requester's side (WP-028
                                               D4): its requester or the person it is for only,
                                               and only what they may see changed
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

from app.modules.identity_access import authorize_stored, restricted_fields
from app.modules.work_items.domain.conversation import Visibility
from app.modules.work_items.domain.lifecycle import DEFAULT_STATUSES, StatusCategory
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.portal import PLANNED_STAGE, portal_changes
from app.modules.work_items.domain.types import (
    CHANGE,
    INCIDENT,
    TYPES,
    WorkItemType,
    WorkItemTypeCode,
)
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemFollower,
    WorkItemLink,
    WorkItemReminder,
    WorkItemRoleHolder,
    WorkItemTask,
    WorkItemTimer,
)
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
PORTAL_KIND = "portal_wi"
PORTAL_CHANGED = "work_items.portal_changed"
PORTAL_CONVERSATION = "work_items.portal_conversation_changed"
_DEFAULT_CATEGORY = {s.code: s.category for s in DEFAULT_STATUSES}
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
# Repeat incident rules and sets (WP-044c D16): screens refetch through the API (no data here).
REPEATS_CHANGED = "work_items.problem_repeats_changed"
# WP-030 s2: a record's approvals (its screens refetch), and an approver's own inbox count.
APPROVALS_CHANGED = "work_items.approvals_changed"
MY_APPROVALS_CHANGED = "work_items.my_approvals_changed"
MY_TASKS_CHANGED = "work_items.my_tasks_changed"
MY_REMINDERS_CHANGED = "work_items.my_reminders_changed"  # WP-046a S2: personal reminders
MY_TIMERS_CHANGED = "work_items.my_timers_changed"  # WP-046a S3: personal timers
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


async def _portal_channel(request: ChannelRequest) -> ChannelAccess | None:
    """Only the record's requester or the person it is for; no presence (staff stay unseen)."""
    try:
        record_id = uuid.UUID(request.channel.key or "")
    except ValueError:
        return None
    row = (
        await request.session.execute(
            select(WorkItem.requester_id, WorkItem.on_behalf_of_id).where(
                WorkItem.id == record_id, WorkItem.deleted_at.is_(None)
            )
        )
    ).one_or_none()
    if row is None or request.subject.user_id not in {row.requester_id, row.on_behalf_of_id}:
        return None
    return ChannelAccess(presence=False)


CHANNELS = [
    *(lst.spec() for lst in LISTS.values()),
    ChannelSpec(kind=RECORD_KIND, authorize=_record_channel),
    ChannelSpec(kind=PORTAL_KIND, authorize=_portal_channel),
]


def _portal(envelope: EventEnvelope, row: WorkItem, fields: tuple[str, ...]) -> list[Publication]:
    """The requester's side hears a change only when something they see changed (D4)."""
    payload = envelope.payload
    if envelope.event_type in {
        "work_items.work_item.created",
        "work_items.work_item.deleted",
        "work_items.work_item.restored",
    }:
        heard: tuple[str, ...] = ("portal_status",)
    else:
        # The event's own statuses: it may be routed after later changes, so not the row's.
        before, after = payload.get("from_status"), payload.get("to_status")
        after_category = _DEFAULT_CATEGORY.get(str(after)) if after else None
        if after and after_category is None and after == row.status:  # a tenant's own status
            after_category = StatusCategory(row.status_category)
        heard = portal_changes(
            [f for f in fields if f != "status"],
            status_before=(str(before), _DEFAULT_CATEGORY.get(str(before))) if before else None,
            status_after=(str(after), after_category) if after and after_category else None,
        )
        if after and after_category is None:  # unknown now: say it changed, the API decides
            heard = tuple(sorted({*heard, "portal_status"}))
        if row.type == CHANGE.code:  # its requester follows the stage and status (REQ-CHG-109)
            shown = {f for f in fields if f in {"stage", "status"}}
            if after:
                shown.add("status")
            heard = tuple(sorted({*heard, *shown}))
    if not heard:
        return []
    return [
        Publication(
            record(envelope.tenant_id, PORTAL_KIND, row.id),
            PORTAL_CHANGED,
            ids=(str(row.id),),
            fields=heard,
            version=envelope.aggregate_version,
        )
    ]


def _actor(envelope: EventEnvelope) -> str | None:
    return envelope.actor.id if envelope.actor.type == "user" else None


def _uuid(value: object) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


async def _staff_fields(
    session: AsyncSession, record_type: str, fields: tuple[str, ...]
) -> tuple[str, ...]:
    """The changed fields as staff channels name them: restricted ones as "restricted"."""
    restricted = await restricted_fields(session, record_type)
    if not restricted or not set(fields) & restricted:
        return fields
    return tuple(dict.fromkeys("restricted" if f in restricted else f for f in fields))


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
    # Role holders (WP-058a s4): "my releases" lists hear about their records, in person or
    # through a group; a role change also reaches those who held it before (lane B's review).
    held_users, held_groups = await _role_holders(session, record_id)
    owners |= held_users | {
        u
        for key in ("users_before", "users_after")
        for u in map(_uuid, payload.get(key) or [])
        if u
    }
    groups |= held_groups | {
        g
        for key in ("groups_before", "groups_after")
        for g in map(_uuid, payload.get(key) or [])
        if g
    }
    fields = tuple(payload.get("changed_fields", ()))
    if "role" in payload:
        fields = ("roles",)
    if "to_status" in payload:
        fields = ("status",)
    elif "technician_id" in payload and "changed_fields" not in payload:
        fields = ("group_id", "technician_id")
    portal = _portal(envelope, row, fields)  # the requester's own allowlist (templates)
    # Shared channels cannot differ per viewer: a field any role restricts is named only as
    # "restricted" (ADR-047 §7); screens refetch the record and get what they may see.
    fields = await _staff_fields(session, str(payload.get("type") or row.type), fields)
    own = Publication(
        record(tenant, RECORD_KIND, record_id),
        CHANGED,
        ids=(str(record_id),),
        fields=fields,
        version=envelope.aggregate_version,
        actor_id=_actor(envelope),
    )
    if (envelope.correlation_id or "").startswith(BULK_PREFIX):  # the batch refreshes lists
        return RealtimeEffects(publications=[own, *portal])
    # A sub-release moved: its parent's screens refresh too (REQ-REL-037 AC3).
    parent = await session.scalar(
        select(WorkItemLink.target_id).where(
            WorkItemLink.source_id == record_id,
            WorkItemLink.kind == LinkKind.SUB_RELEASE_OF,
            WorkItemLink.deleted_at.is_(None),
        )
    )
    upward = (
        [
            Publication(
                record(tenant, RECORD_KIND, parent),
                PART_CHANGED,
                ids=(str(record_id),),
                fields=("sub_releases",),
                actor_id=_actor(envelope),
            )
        ]
        if parent is not None
        else []
    )
    publications = [
        own,
        *upward,
        *portal,
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


async def _role_holders(
    session: AsyncSession, record_id: uuid.UUID
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    rows = (
        await session.execute(
            select(WorkItemRoleHolder.user_id, WorkItemRoleHolder.group_id).where(
                WorkItemRoleHolder.work_item_id == record_id
            )
        )
    ).all()
    return {r.user_id for r in rows if r.user_id}, {r.group_id for r in rows if r.group_id}


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
    """A reply or note was added or changed visibility: open timelines refetch it.

    Its technician and followers also recount: "updated by others" counts entries by someone
    else on records they own or follow (WP-020d QA BUG-01). The writer's own count does not change.
    """
    payload = envelope.payload
    record_id = uuid.UUID(str(payload["work_item_id"]))
    publications = [
        Publication(
            record(envelope.tenant_id, RECORD_KIND, record_id),
            CONVERSATION_CHANGED,
            ids=(str(payload["entry_id"]),),
            actor_id=_actor(envelope),
        ),
        *_portal_entry(envelope, record_id),
    ]
    if envelope.event_type == "work_items.conversation.added":
        technician = await session.scalar(
            select(WorkItem.technician_id).where(WorkItem.id == record_id)
        )
        followers = await session.scalars(
            select(WorkItemFollower.user_id).where(
                WorkItemFollower.work_item_id == record_id, WorkItemFollower.deleted_at.is_(None)
            )
        )
        people = {u for u in (technician, *followers) if u} - {_uuid(_actor(envelope))}
        publications += [
            _lists_changed(envelope.tenant_id, u, record_id) for u in sorted(people, key=str)
        ]
    return RealtimeEffects(publications=publications)


def _portal_entry(envelope: EventEnvelope, record_id: uuid.UUID) -> list[Publication]:
    """A public entry was added, or one changed sides: the requester's conversation refetches.

    A private entry says nothing there (REQ-INC-147 AC2), nor does an e-mail delivery update.
    """
    payload = envelope.payload
    public = Visibility.PUBLIC.value
    if envelope.event_type == "work_items.conversation.delivery_changed":
        return []
    if public not in {payload.get("visibility"), payload.get("from_visibility")}:
        return []
    return [
        Publication(
            record(envelope.tenant_id, PORTAL_KIND, record_id),
            PORTAL_CONVERSATION,
            ids=(str(payload["entry_id"]),),
        )
    ]


def _lists_changed(tenant: uuid.UUID, user: uuid.UUID, record_id: uuid.UUID) -> Publication:
    """One person's own lists and counts changed (follows, replies by others): they recount.

    On the person's own channel, because someone who sees every record follows only the shared
    list channel, which never hears about personal changes (WP-020d QA BUG-01).
    """
    return Publication(personal(tenant, user), LISTS_CHANGED, ids=(str(record_id),), coalesce=True)


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
        ),
        _lists_changed(tenant, user_id, record_id),  # "Followed by me", "Shared with me"
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


async def _repeats_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A repeat rule or set changed: the problems list and the rules screen refetch (no data)."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), REPEATS_CHANGED)]
    )


async def _settings_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Configuration changed: open forms reload their pick lists (no record data)."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), SETTINGS_CHANGED)]
    )


async def _view_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A saved view changed: everyone's view menu for a shared one, else its owner's.

    A view shared with groups also goes to the tenant channel: the payload holds IDs only and
    each menu refetches through the API, which lists only the views its reader may use.
    """
    del session
    payload = envelope.payload
    owner = uuid.UUID(str(payload["owner_id"]))
    shared = (
        payload.get("visibility") != "private"
    )  # groups or everyone: menus refetch, the API filters
    channel = broadcast(envelope.tenant_id) if shared else personal(envelope.tenant_id, owner)
    return RealtimeEffects(
        publications=[
            Publication(
                channel, VIEWS_CHANGED, ids=(str(payload["view_id"]),), actor_id=_actor(envelope)
            )
        ]
    )


PORTAL_SETTINGS_CHANGED = "work_items.portal_settings_changed"
CHANGE_BOARDS_CHANGED = "work_items.change_boards_changed"
CHANGE_WINDOWS_CHANGED = "work_items.change_windows_changed"


async def _change_window_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A freeze or maintenance window changed: open calendars and window settings refetch."""
    del session
    return RealtimeEffects(
        publications=[
            Publication(
                broadcast(envelope.tenant_id),
                CHANGE_WINDOWS_CHANGED,
                ids=(str(envelope.payload["window_id"]),),
                actor_id=_actor(envelope),
            )
        ]
    )


async def _change_board_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A change advisory board changed: open board settings refetch (IDs only, WP-045b S2)."""
    del session
    return RealtimeEffects(
        publications=[
            Publication(
                broadcast(envelope.tenant_id),
                CHANGE_BOARDS_CHANGED,
                ids=(str(envelope.payload["board_id"]),),
                actor_id=_actor(envelope),
            )
        ]
    )


async def _portal_settings_changed(
    envelope: EventEnvelope, session: AsyncSession
) -> RealtimeEffects:
    """Portal settings changed: open portals and the settings page reload them (REQ-PRT-031)."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), PORTAL_SETTINGS_CHANGED)]
    )


APPROVAL_SETTINGS_CHANGED = "work_items.approval_settings_changed"


async def _approval_settings_changed(
    envelope: EventEnvelope, session: AsyncSession
) -> RealtimeEffects:
    """Approval settings changed (the D-146 chair): the open settings page reloads them."""
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), APPROVAL_SETTINGS_CHANGED)]
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


async def _asset_link_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """An asset linked or unlinked (REQ-AST-025): the record's Assets section refreshes."""
    del session
    payload = envelope.payload
    record_id = uuid.UUID(str(payload["work_item_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                record(envelope.tenant_id, RECORD_KIND, record_id),
                PART_CHANGED,
                ids=(str(payload["asset_id"]),),
                fields=("asset",),
                actor_id=_actor(envelope),
            )
        ]
    )


async def _part_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A task, worklog or link changed: the record's screens, and a task owner's own list."""
    payload = envelope.payload
    record_id = uuid.UUID(str(payload["work_item_id"]))
    part_id = uuid.UUID(str(payload["part_id"]))
    if payload["part"] == "timer":
        # A personal timer (WP-046a S3, REQ-INC-069): its owner's channel only, as reminders.
        timer_owner = await session.scalar(
            select(WorkItemTimer.user_id).where(WorkItemTimer.id == part_id)
        )
        if timer_owner is None:
            return RealtimeEffects()
        return RealtimeEffects(
            publications=[
                Publication(
                    personal(envelope.tenant_id, timer_owner),
                    MY_TIMERS_CHANGED,
                    ids=(str(part_id),),
                    actor_id=_actor(envelope),
                )
            ]
        )
    if payload["part"] == "reminder":
        # A personal reminder (WP-046a S2, REQ-INC-082 AC2): its owner's channel only, never the
        # record's, so nobody else even hears that one exists.
        owner = await session.scalar(
            select(WorkItemReminder.user_id).where(WorkItemReminder.id == part_id)
        )
        if owner is None:
            return RealtimeEffects()
        return RealtimeEffects(
            publications=[
                Publication(
                    personal(envelope.tenant_id, owner),
                    MY_REMINDERS_CHANGED,
                    ids=(str(part_id),),
                    actor_id=_actor(envelope),
                )
            ]
        )
    publications = [
        Publication(
            record(envelope.tenant_id, RECORD_KIND, record_id),
            PART_CHANGED,
            ids=(str(part_id),),
            fields=(str(payload["part"]),),
            actor_id=_actor(envelope),
        )
    ]
    if payload["part"] == "stage_schedule" and part_id == uuid.uuid5(record_id, PLANNED_STAGE):
        # A change's planned window, which its requester sees (REQ-CHG-109); other stages not.
        publications.append(
            Publication(
                record(envelope.tenant_id, PORTAL_KIND, record_id),
                PORTAL_CHANGED,
                ids=(str(record_id),),
                fields=(
                    "planned_end",
                    "planned_start",
                ),
            )
        )
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


async def _approval_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """An approval opened or was decided: the record's screens and the approver's inbox.

    The administrators' approvals (no approver) signal every screen once (broadcast, coalesced);
    only those with `work_items.approve_any` get rows back when their inbox refetches.
    """
    del session
    payload = envelope.payload
    tenant = envelope.tenant_id
    record_id = uuid.UUID(str(payload["work_item_id"]))
    approval = str(payload["approval_id"])
    publications = [
        Publication(
            record(tenant, RECORD_KIND, record_id),
            APPROVALS_CHANGED,
            ids=(approval,),
            actor_id=_actor(envelope),
        )
    ]
    approver = _uuid(payload.get("approver_id"))
    publications.append(
        Publication(personal(tenant, approver), MY_APPROVALS_CHANGED, ids=(approval,))
        if approver is not None
        else Publication(broadcast(tenant), MY_APPROVALS_CHANGED, ids=(approval,), coalesce=True)
    )
    return RealtimeEffects(publications=publications)


DRAFT_CHANGED = "work_items.draft_changed"


async def _draft_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A person's kept draft changed: their own other tabs refresh (form key and version only)."""
    del session
    payload = envelope.payload
    return RealtimeEffects(
        publications=[
            Publication(
                personal(envelope.tenant_id, uuid.UUID(str(payload["owner_id"]))),
                DRAFT_CHANGED,
                ids=(str(payload["form_key"]),),
                version=int(payload["version"]),
            )
        ]
    )


ROUTES = [
    RealtimeRoute(("work_items.draft.changed",), _draft_changed),
    RealtimeRoute(
        (
            "work_items.work_item.created",
            "work_items.work_item.updated",
            "work_items.work_item.status_changed",
            "work_items.work_item.roles_changed",
            "work_items.work_item.assigned",
            "work_items.work_item.deleted",
            "work_items.work_item.restored",
        ),
        _work_item_changed,
    ),
    RealtimeRoute(("work_items.settings.changed",), _settings_changed),
    RealtimeRoute(("work_items.portal_settings.changed",), _portal_settings_changed),
    RealtimeRoute(("work_items.approval_settings.changed",), _approval_settings_changed),
    RealtimeRoute(("work_items.change_board.changed",), _change_board_changed),
    RealtimeRoute(("work_items.change_window.changed",), _change_window_changed),
    RealtimeRoute(
        (
            "work_items.conversation.added",
            "work_items.conversation.visibility_changed",
            "work_items.conversation.delivery_changed",
        ),
        _conversation_changed,
    ),
    RealtimeRoute(("work_items.follower.added", "work_items.follower.removed"), _followers_changed),
    RealtimeRoute(("work_items.reply_templates.changed",), _templates_changed),
    RealtimeRoute(("work_items.view.changed",), _view_changed),
    RealtimeRoute(("work_items.list_settings.changed",), _list_settings_changed),
    RealtimeRoute(("work_items.bulk_job.progressed",), _bulk_progressed),
    RealtimeRoute(("work_items.part.changed",), _part_changed),
    RealtimeRoute(("work_items.asset_link.changed",), _asset_link_changed),
    RealtimeRoute(("work_items.approval.changed",), _approval_changed),
    RealtimeRoute(
        ("work_items.problem_repeat.detected", "work_items.problem_repeat.changed"),
        _repeats_changed,
    ),
]
