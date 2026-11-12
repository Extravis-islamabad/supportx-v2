"""A change's conflicts with freeze and maintenance windows and other changes (WP-045c; ADR-042).

Reads the windows and the other changes' planned times, and asks the pure model what conflicts.
It never imports the work items service (that module calls this one on every save of a change's
window or downtime), so it reads the rows it needs itself.

* `conflicts` lists every conflict of a change's planned times (the record's conflicts panel).
* `guard` runs on a save that moves a change's planned time: a blocking conflict refuses it
  (409 `change_window_blocked`) unless the change carries a freeze override; the rest are only
  shown. Releases reuse it once lane C's releases plan with windows (ADR-042).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.modules.organization import regional_defaults
from app.modules.work_items.domain import change_windows as model
from app.modules.work_items.domain.changes import EMERGENCY_PATH
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.types import WorkItemTypeCode
from app.modules.work_items.infra.models import (
    ChangeWindow,
    WorkItem,
    WorkItemChangeDetails,
    WorkItemDowntime,
    WorkItemReleaseDetails,
    WorkItemRoleHolder,
    WorkItemStageSchedule,
    WorkItemTypeSettings,
)

CHANGE = WorkItemTypeCode.CHANGE.value
BLOCKED = "change_window_blocked"
_OPEN = (StatusCategory.OPEN.value, StatusCategory.PAUSED.value)
Times = Sequence[tuple[datetime, datetime]]


async def tenant_zone(session: AsyncSession) -> tzinfo:
    """The tenant's time zone: a monthly window's weekday is a local one (D-156); UTC if unset."""
    name = (await regional_defaults(session, None)).time_zone
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):  # checked when saved; never fail a check
        return UTC


async def outside_maintenance_blocks(session: AsyncSession) -> bool:
    """The tenant's D-156 setting: outside every maintenance window blocks a change."""
    found = await session.scalar(
        select(WorkItemTypeSettings.outside_maintenance_blocks).where(
            WorkItemTypeSettings.type == CHANGE
        )
    )
    return bool(found)


def window_of(row: ChangeWindow, zone: tzinfo = UTC) -> model.Window:
    """The stored window as the model's (monthly ones on the tenant's local days)."""
    return model.Window(
        id=row.id,
        kind=model.WindowKind(row.kind),
        mode=model.WindowMode(row.mode),
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        scope=model.Scope(
            site_ids=frozenset(row.site_ids or ()),
            group_ids=frozenset(row.group_ids or ()),
            service_ids=frozenset(row.service_ids or ()),
            ci_ids=frozenset(row.ci_ids or ()),
        ),
        repeat_weekly=row.repeat == "weekly",
        repeat_until=row.repeat_until,
        monthly=(
            (row.repeat_week, row.repeat_weekday)
            if row.repeat == "monthly"
            and row.repeat_week is not None
            and row.repeat_weekday is not None
            else None
        ),
        zone=zone,
    )


async def windows_touching(
    session: AsyncSession, start: datetime, end: datetime
) -> list[ChangeWindow]:
    """Live windows that may have an occurrence in [start, end) (weekly ones from their start)."""
    rows = await session.scalars(
        select(ChangeWindow)
        .where(
            ChangeWindow.deleted_at.is_(None),
            ChangeWindow.starts_at < end,
            or_(
                ChangeWindow.ends_at > start,
                and_(
                    ChangeWindow.repeat != "none",
                    or_(ChangeWindow.repeat_until.is_(None), ChangeWindow.repeat_until >= start),
                ),
            ),
        )
        .order_by(ChangeWindow.starts_at, ChangeWindow.id)
    )
    return list(rows)


# A one-off maintenance window counts for a change planned within a week of it; a weekly one for
# as long as it repeats (ADR-042: "outside maintenance" needs windows near the change, not every
# window the tenant ever had).
MAINTENANCE_REACH = timedelta(days=7)


async def maintenance_in_effect(
    session: AsyncSession, start: datetime, end: datetime
) -> list[ChangeWindow]:
    """Maintenance windows a change in [start, end) is measured against, in or out."""
    rows = await session.scalars(
        select(ChangeWindow)
        .where(
            ChangeWindow.deleted_at.is_(None),
            ChangeWindow.kind == model.WindowKind.MAINTENANCE.value,
            or_(
                and_(
                    ChangeWindow.repeat != "none",
                    ChangeWindow.starts_at < end,
                    or_(ChangeWindow.repeat_until.is_(None), ChangeWindow.repeat_until >= start),
                ),
                and_(
                    ChangeWindow.repeat == "none",
                    ChangeWindow.starts_at < end + MAINTENANCE_REACH,
                    ChangeWindow.ends_at > start - MAINTENANCE_REACH,
                ),
            ),
        )
        .order_by(ChangeWindow.starts_at, ChangeWindow.id)
    )
    return list(rows)


async def planned_times(session: AsyncSession, record: WorkItem) -> list[tuple[datetime, datetime]]:
    """The record's planned time: its planned stage's window and its planned downtimes."""
    times: list[tuple[datetime, datetime]] = []
    stage = model.PLANNED_STAGE.get(record.type)
    if stage is None:
        return times
    window = await session.scalar(
        select(WorkItemStageSchedule).where(
            WorkItemStageSchedule.work_item_id == record.id,
            WorkItemStageSchedule.stage == stage,
        )
    )
    if window is not None and window.scheduled_start and window.scheduled_end:
        times.append((window.scheduled_start, window.scheduled_end))
    downtimes = await session.scalars(
        select(WorkItemDowntime).where(
            WorkItemDowntime.work_item_id == record.id,
            WorkItemDowntime.phase == "planned",
            WorkItemDowntime.deleted_at.is_(None),
        )
    )
    times.extend((d.starts_at, d.ends_at) for d in downtimes)
    return times


OTHERS_LIMIT = 200  # other records met in one check: a busy week fits many times over
RELEASE = WorkItemTypeCode.RELEASE.value
RELEASE_ROLES = frozenset({"release_manager", "release_engineer"})  # its people (REQ-REL-023)


async def _items_of(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> tuple[dict[uuid.UUID, set[uuid.UUID]], dict[uuid.UUID, set[uuid.UUID]]]:
    """The service and CI IDs the records' planned downtimes name (stored IDs only)."""
    services: dict[uuid.UUID, set[uuid.UUID]] = {i: set() for i in ids}
    cis: dict[uuid.UUID, set[uuid.UUID]] = {i: set() for i in ids}
    if not ids:
        return services, cis
    rows = await session.execute(
        select(
            WorkItemDowntime.work_item_id, WorkItemDowntime.service_ids, WorkItemDowntime.ci_ids
        ).where(
            WorkItemDowntime.work_item_id.in_(ids),
            WorkItemDowntime.phase == "planned",
            WorkItemDowntime.deleted_at.is_(None),
        )
    )
    for item, service_ids, ci_ids in rows:
        services[item] |= set(service_ids or ())
        cis[item] |= set(ci_ids or ())
    return services, cis


async def _people_of(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """The release manager and engineer of each release: its details and its role holders."""
    people: dict[uuid.UUID, set[uuid.UUID]] = {i: set() for i in ids}
    if not ids:
        return people
    details = await session.execute(
        select(
            WorkItemReleaseDetails.work_item_id,
            WorkItemReleaseDetails.release_manager_id,
            WorkItemReleaseDetails.release_engineer_id,
        ).where(WorkItemReleaseDetails.work_item_id.in_(ids))
    )
    for item, manager, engineer in details:
        people[item] |= {p for p in (manager, engineer) if p is not None}
    holders = await session.execute(
        select(WorkItemRoleHolder.work_item_id, WorkItemRoleHolder.user_id).where(
            WorkItemRoleHolder.work_item_id.in_(ids),
            WorkItemRoleHolder.role.in_(RELEASE_ROLES),
            WorkItemRoleHolder.user_id.is_not(None),
        )
    )
    for item, user in holders:
        if user is not None:
            people[item].add(user)
    return people


async def _others(  # noqa: PLR0913 - the record, its range and what it may meet, explicit
    session: AsyncSession,
    record: WorkItem,
    start: datetime,
    end: datetime,
    *,
    service_ids: frozenset[uuid.UUID],
    ci_ids: frozenset[uuid.UUID],
    people: frozenset[uuid.UUID],
) -> list[model.Planned]:
    """Other open changes and releases planned in [start, end) that this one may meet.

    One query per type (ADR-042 addendum A): the same group or site, a planned downtime naming
    one of the same services or CIs, or (releases) a release role held by the same person.
    """
    found: list[model.Planned] = []
    for wtype, stage in model.PLANNED_STAGE.items():
        meets = [
            c
            for c in (
                WorkItem.group_id == record.group_id if record.group_id else None,
                WorkItem.site_id == record.site_id if record.site_id else None,
            )
            if c is not None
        ]
        if service_ids or ci_ids:
            meets.append(
                WorkItem.id.in_(
                    select(WorkItemDowntime.work_item_id).where(
                        # The tenant explicitly too (lane A's #397 note): the tenant-leading
                        # indexes serve it, not only RLS's filter.
                        WorkItemDowntime.tenant_id == record.tenant_id,
                        WorkItemDowntime.phase == "planned",
                        WorkItemDowntime.deleted_at.is_(None),
                        or_(
                            *(
                                [WorkItemDowntime.service_ids.overlap(sorted(service_ids))]
                                if service_ids
                                else []
                            ),
                            *([WorkItemDowntime.ci_ids.overlap(sorted(ci_ids))] if ci_ids else []),
                        ),
                    )
                )
            )
        if people and wtype == RELEASE:
            meets.append(
                WorkItem.id.in_(
                    select(WorkItemReleaseDetails.work_item_id).where(
                        WorkItemReleaseDetails.tenant_id == record.tenant_id,
                        or_(
                            WorkItemReleaseDetails.release_manager_id.in_(people),
                            WorkItemReleaseDetails.release_engineer_id.in_(people),
                        ),
                    )
                )
            )
            meets.append(
                WorkItem.id.in_(
                    select(WorkItemRoleHolder.work_item_id).where(
                        WorkItemRoleHolder.tenant_id == record.tenant_id,
                        WorkItemRoleHolder.role.in_(RELEASE_ROLES),
                        WorkItemRoleHolder.user_id.in_(people),
                    )
                )
            )
        if not meets:
            continue
        rows = (
            await session.execute(
                select(
                    WorkItem.id,
                    WorkItem.site_id,
                    WorkItem.group_id,
                    WorkItemStageSchedule.scheduled_start,
                    WorkItemStageSchedule.scheduled_end,
                    WorkItemStageSchedule.version,
                )
                .join(WorkItemStageSchedule, WorkItemStageSchedule.work_item_id == WorkItem.id)
                .where(
                    WorkItem.tenant_id == record.tenant_id,
                    WorkItemStageSchedule.tenant_id == record.tenant_id,
                    WorkItem.type == wtype,
                    WorkItem.id != record.id,
                    WorkItem.deleted_at.is_(None),
                    WorkItem.status_category.in_(_OPEN),
                    or_(*meets),
                    WorkItemStageSchedule.stage == stage,
                    WorkItemStageSchedule.scheduled_start < end,
                    WorkItemStageSchedule.scheduled_end > start,
                )
                .order_by(WorkItemStageSchedule.scheduled_start, WorkItem.id)
                .limit(OTHERS_LIMIT)
            )
        ).all()
        ids = [r.id for r in rows]
        services, cis = await _items_of(session, ids) if service_ids or ci_ids else ({}, {})
        holders = await _people_of(session, ids) if people and wtype == RELEASE else {}
        found.extend(
            model.Planned(
                r.id,
                r.scheduled_start,
                r.scheduled_end,
                r.site_id,
                r.group_id,
                record_type=wtype,
                service_ids=frozenset(services.get(r.id, ())),
                ci_ids=frozenset(cis.get(r.id, ())),
                people=frozenset(holders.get(r.id, ())),
                version=r.version,
            )
            for r in rows
        )
    return found


async def conflicts(
    session: AsyncSession, record: WorkItem, times: Times | None = None
) -> tuple[list[model.Conflict], dict[uuid.UUID, ChangeWindow]]:
    """Every conflict of the record's planned times (or of `times`), and the windows named.

    A change or a release (ADR-042 addendum A); any other type has none.
    """
    if record.type not in model.PLANNED_STAGE:
        return [], {}
    planned = list(times) if times is not None else await planned_times(session, record)
    if not planned:
        return [], {}
    start = min(s for s, _ in planned)
    end = max(e for _, e in planned)
    touching = await windows_touching(session, start, end)
    near = await maintenance_in_effect(session, start, end)
    rows = list({r.id: r for r in (*touching, *near)}.values())
    zone = await tenant_zone(session)
    services, cis = await _items_of(session, [record.id])
    own_services = frozenset(services.get(record.id, ()))
    own_cis = frozenset(cis.get(record.id, ()))
    own_people = (
        frozenset((await _people_of(session, [record.id])).get(record.id, ()))
        if record.type == RELEASE
        else frozenset()
    )
    found = model.conflicts(
        planned,
        site_id=record.site_id,
        group_id=record.group_id,
        windows=[window_of(r, zone) for r in rows],
        others=await _others(
            session,
            record,
            start,
            end,
            service_ids=own_services,
            ci_ids=own_cis,
            people=own_people,
        ),
        record_id=record.id,
        # D-156's setting is the change type's only: a release warns (lane A, addendum A).
        outside_blocks=record.type == CHANGE and await outside_maintenance_blocks(session),
        service_ids=own_services,
        ci_ids=own_cis,
        people=own_people,
    )
    return found, {r.id: r for r in rows}


async def passed_windows(session: AsyncSession, record_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """The freezes someone allowed to has passed for this change or release, by ID.

    Only these: a different freeze, or one added later, still blocks the record until someone
    passes it too (lane B's review of #376). A release's are its own override's only (0139; no
    CAB path, ADR-042 addendum A).
    """
    ids = await session.scalar(
        select(WorkItemChangeDetails.freeze_override_window_ids).where(
            WorkItemChangeDetails.work_item_id == record_id
        )
    )
    if ids is None:
        ids = await session.scalar(
            select(WorkItemReleaseDetails.freeze_override_window_ids).where(
                WorkItemReleaseDetails.work_item_id == record_id
            )
        )
    return frozenset(ids or ())


def still_blocking(
    found: Sequence[model.Conflict], passed: frozenset[uuid.UUID]
) -> list[model.Conflict]:
    """The blocking conflicts no override covers (a maintenance block is never a freeze's)."""
    return [c for c in found if c.blocks and c.window_id not in passed]


def frozen_still(
    found: Sequence[model.Conflict], passed: frozenset[uuid.UUID]
) -> list[model.Conflict]:
    """The blocking freezes no override covers (what an emergency change's CAB may pass)."""
    return [c for c in still_blocking(found, passed) if c.kind is model.ConflictKind.FREEZE]


async def guard(session: AsyncSession, record: WorkItem, times: Times) -> list[model.Conflict]:
    """On a save that moves the change's time: refuse a blocking conflict, return the others.

    The refusal names the first blocking window (its ID and kind, never its text) so the screen
    can say which and offer the override to those who hold it, for that window.

    D-156: an emergency change's window in a blocking freeze is saved, never refused; the
    change is marked by the conflict itself, and its move into implementation waits for its
    emergency CAB or the override (change_guard). A maintenance block still refuses it.
    """
    found, _ = await conflicts(session, record, times)
    blocking = still_blocking(found, await passed_windows(session, record.id))
    # Changes only (lane A, addendum A): a release's emergency path is refused like any other.
    if record.type == CHANGE and record.stage_path == EMERGENCY_PATH:
        blocking = [c for c in blocking if c.kind is not model.ConflictKind.FREEZE]
    if blocking:
        first = blocking[0]
        raise Conflict(
            code=BLOCKED,
            params={
                "kind": first.kind.value,
                "window_id": str(first.window_id) if first.window_id else None,
                # Every blocking freeze, comma-separated: the override dialog passes these.
                "window_ids": ",".join(sorted({str(c.window_id) for c in blocking if c.window_id})),
                "count": len(blocking),
            },
        )
    return found
