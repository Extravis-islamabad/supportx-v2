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
from app.modules.work_items.domain.changes import EMERGENCY_PATH, IMPLEMENTATION
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.types import WorkItemTypeCode
from app.modules.work_items.infra.models import (
    ChangeWindow,
    WorkItem,
    WorkItemChangeDetails,
    WorkItemDowntime,
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


async def planned_times(
    session: AsyncSession, record_id: uuid.UUID
) -> list[tuple[datetime, datetime]]:
    """The change's planned time: its implementation window and its planned downtimes."""
    times: list[tuple[datetime, datetime]] = []
    window = await session.scalar(
        select(WorkItemStageSchedule).where(
            WorkItemStageSchedule.work_item_id == record_id,
            WorkItemStageSchedule.stage == IMPLEMENTATION,
        )
    )
    if window is not None and window.scheduled_start and window.scheduled_end:
        times.append((window.scheduled_start, window.scheduled_end))
    downtimes = await session.scalars(
        select(WorkItemDowntime).where(
            WorkItemDowntime.work_item_id == record_id,
            WorkItemDowntime.phase == "planned",
            WorkItemDowntime.deleted_at.is_(None),
        )
    )
    times.extend((d.starts_at, d.ends_at) for d in downtimes)
    return times


async def _others(
    session: AsyncSession, record: WorkItem, start: datetime, end: datetime
) -> list[model.Planned]:
    """Other open changes in the same group or at the same site planned in [start, end)."""
    place = [
        c
        for c in (
            WorkItem.group_id == record.group_id if record.group_id else None,
            WorkItem.site_id == record.site_id if record.site_id else None,
        )
        if c is not None
    ]
    if not place:
        return []
    rows = await session.execute(
        select(
            WorkItem.id,
            WorkItem.site_id,
            WorkItem.group_id,
            WorkItemStageSchedule.scheduled_start,
            WorkItemStageSchedule.scheduled_end,
        )
        .join(WorkItemStageSchedule, WorkItemStageSchedule.work_item_id == WorkItem.id)
        .where(
            WorkItem.type == CHANGE,
            WorkItem.id != record.id,
            WorkItem.deleted_at.is_(None),
            WorkItem.status_category.in_(_OPEN),
            or_(*place),
            WorkItemStageSchedule.stage == IMPLEMENTATION,
            WorkItemStageSchedule.scheduled_start < end,
            WorkItemStageSchedule.scheduled_end > start,
        )
    )
    return [
        model.Planned(r.id, r.scheduled_start, r.scheduled_end, r.site_id, r.group_id) for r in rows
    ]


async def conflicts(
    session: AsyncSession, record: WorkItem, times: Times | None = None
) -> tuple[list[model.Conflict], dict[uuid.UUID, ChangeWindow]]:
    """Every conflict of the change's planned times (or of `times`), and the windows named."""
    planned = list(times) if times is not None else await planned_times(session, record.id)
    if record.type != CHANGE or not planned:
        return [], {}
    start = min(s for s, _ in planned)
    end = max(e for _, e in planned)
    touching = await windows_touching(session, start, end)
    near = await maintenance_in_effect(session, start, end)
    rows = list({r.id: r for r in (*touching, *near)}.values())
    zone = await tenant_zone(session)
    found = model.conflicts(
        planned,
        site_id=record.site_id,
        group_id=record.group_id,
        windows=[window_of(r, zone) for r in rows],
        others=await _others(session, record, start, end),
        record_id=record.id,
        outside_blocks=await outside_maintenance_blocks(session),
    )
    return found, {r.id: r for r in rows}


async def passed_windows(session: AsyncSession, record_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """The freezes someone allowed to has passed for this change, by ID (none: nothing passed).

    Only these: a different freeze, or one added later, still blocks the change until someone
    passes it too (lane B's review of #376).
    """
    ids = await session.scalar(
        select(WorkItemChangeDetails.freeze_override_window_ids).where(
            WorkItemChangeDetails.work_item_id == record_id
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
    if record.stage_path == EMERGENCY_PATH:
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
