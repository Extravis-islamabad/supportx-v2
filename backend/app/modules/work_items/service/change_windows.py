"""Freeze and maintenance windows, the admin side, and a change's freeze override (WP-045c).

* Windows (REQ-CHG-075..077): anyone who may see changes reads them (the calendar shows them);
  `changes.manage_windows` (the change manager and administrators) adds, changes and removes
  them. A new freeze blocks and a maintenance window warns unless told otherwise (D-156 (a),
  (b)); a window repeats weekly or not at all in v1 (D-156 (c)). Every change is versioned
  (If-Match), kept in field history and announced through the outbox (rule 5c).
* The freeze override (ADR-042; D-144's pattern): someone holding `changes.override_freeze`
  for this change (its scope: all, its site or its group) passes the blocking freezes for it,
  with a reason. The route audits it, refused attempts too; the record's history keeps it.
  Tenant administrators hold every permission, so they may override too, as with D-144.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules.identity_access import Subject
from app.modules.organization import existing_unit_ids
from app.modules.work_items.domain import change_windows as rules
from app.modules.work_items.domain.changes import IMPLEMENTATION
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.events import ChangeWindowChanged
from app.modules.work_items.infra.models import (
    ChangeWindow,
    WorkItem,
    WorkItemChangeDetails,
    WorkItemDowntime,
    WorkItemStageSchedule,
)
from app.modules.work_items.service import change_conflicts
from app.modules.work_items.service import work_items as items
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, ChangeKind, Source, record_changes

RECORD_TYPE = "change_window"
CHANGE = TYPES[WorkItemTypeCode.CHANGE]
MANAGE = ("changes.manage_windows", "settings.manage")
OVERRIDE = "override_freeze"  # the change's own action (its permission's scope decides)
OVERRIDE_PERMISSION = "changes.override_freeze"
NAME_MAX, DESCRIPTION_MAX, LABEL_MAX, REASON_MAX, MAX_IDS = 200, 2000, 200, 500, 200
LANGUAGES = frozenset({"en", "ar", "ur"})
SCOPES = ("site_ids", "group_ids", "service_ids", "ci_ids")
EDITABLE = (
    "kind",
    "mode",
    "name",
    "labels",
    "description",
    "starts_at",
    "ends_at",
    "repeat_weekly",
    "repeat_until",
    *SCOPES,
)
# The field codes a window's checks give (labels: errors.field.*).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "invalid_choice",
        "invalid_value",
        "value_too_long",
        "too_many_items",
        "end_before_start",
        "longer_than_a_week",
        "not_allowed",
        "site_not_found",
        "group_not_found",
        "reason_required",
    }
)


class WindowRepository(Repository[ChangeWindow]):
    """Change windows of the session's tenant."""

    model = ChangeWindow


def _require_manage(subject: Subject) -> None:
    if not any(subject.holds(p) for p in MANAGE):
        raise PermissionDenied(params={"permission": MANAGE[0], "reason": "no_permission"})


def _require_view(subject: Subject) -> None:
    view = CHANGE.permission("view")
    if not subject.holds(view) and not any(subject.holds(p) for p in MANAGE):
        raise PermissionDenied(params={"permission": view, "reason": "no_permission"})


async def windows(
    session: AsyncSession,
    subject: Subject,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[ChangeWindow]:
    """Live windows, by start; with a range, only those with an occurrence in it."""
    _require_view(subject)
    if start is not None and end is not None:
        rows = await change_conflicts.windows_touching(session, start, end)
        return [r for r in rows if change_conflicts.window_of(r).occurrences(start, end)]
    found = await session.scalars(
        select(ChangeWindow)
        .where(ChangeWindow.deleted_at.is_(None))
        .order_by(ChangeWindow.starts_at, ChangeWindow.id)
    )
    return list(found)


async def window(session: AsyncSession, subject: Subject, window_id: uuid.UUID) -> ChangeWindow:
    """One live window (404 `window_not_found`)."""
    _require_view(subject)
    row = await session.scalar(
        select(ChangeWindow).where(ChangeWindow.id == window_id, ChangeWindow.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="window_not_found")
    return row


def _labels(raw: Any, problems: list[tuple[str, str]]) -> dict[str, str] | None:  # noqa: ANN401 - the request's JSON
    if not raw:
        return None
    if not isinstance(raw, Mapping) or set(raw) - LANGUAGES:
        problems.append(("labels", "invalid_value"))
        return None
    clean = {k: " ".join(str(v).split()) for k, v in raw.items() if str(v).strip()}
    if any(len(v) > LABEL_MAX for v in clean.values()):
        problems.append(("labels", "value_too_long"))
    return clean or None


def _ids(raw: Any, name: str, problems: list[tuple[str, str]]) -> list[uuid.UUID]:  # noqa: ANN401 - the request's JSON
    values = list(raw or [])
    if len(values) > MAX_IDS:
        problems.append((name, "too_many_items"))
        return []
    try:
        return sorted({uuid.UUID(str(v)) for v in values})
    except ValueError:
        problems.append((name, "invalid_value"))
        return []


async def _scope(
    session: AsyncSession, merged: Mapping[str, Any], problems: list[tuple[str, str]]
) -> dict[str, list[uuid.UUID]]:
    """The window's sites, groups, services and CIs; sites and groups must exist here."""
    scope = {n: _ids(merged.get(n), n, problems) for n in SCOPES}
    if scope["site_ids"] and set(scope["site_ids"]) - await existing_unit_ids(
        session, "site", scope["site_ids"]
    ):
        problems.append(("site_ids", "site_not_found"))
    if scope["group_ids"] and set(scope["group_ids"]) - await existing_unit_ids(
        session, "group", scope["group_ids"]
    ):
        problems.append(("group_ids", "group_not_found"))
    return scope


async def _check(session: AsyncSession, merged: Mapping[str, Any]) -> dict[str, Any]:
    """The window's values, cleaned and checked together (422 with every problem)."""
    problems: list[tuple[str, str]] = []
    kind = merged.get("kind")
    if kind not in {k.value for k in rules.WindowKind}:
        problems.append(("kind", "required" if kind is None else "invalid_choice"))
    mode = merged.get("mode")
    if mode is None and kind in {k.value for k in rules.WindowKind}:
        mode = rules.KIND_DEFAULT_MODE[rules.WindowKind(kind)].value  # D-156 (a), (b)
    if mode not in {m.value for m in rules.WindowMode}:
        problems.append(("mode", "invalid_choice"))
    name = " ".join(str(merged.get("name") or "").split())
    if not name:
        problems.append(("name", "required"))
    elif len(name) > NAME_MAX:
        problems.append(("name", "value_too_long"))
    description = (merged.get("description") or "").strip() or None
    if description is not None and len(description) > DESCRIPTION_MAX:
        problems.append(("description", "value_too_long"))
    labels = _labels(merged.get("labels"), problems)
    weekly = bool(merged.get("repeat_weekly"))
    problems.extend(
        rules.window_problems(
            merged.get("starts_at"),
            merged.get("ends_at"),
            repeat_weekly=weekly,
            repeat_until=merged.get("repeat_until"),
        )
    )
    scope = await _scope(session, merged, problems)
    if problems:
        raise items.field_errors(list(dict.fromkeys(problems)))
    return {
        "kind": kind,
        "mode": mode,
        "name": name,
        "labels": labels,
        "description": description,
        "starts_at": merged["starts_at"],
        "ends_at": merged["ends_at"],
        "repeat_weekly": weekly,
        "repeat_until": merged.get("repeat_until"),
        **scope,
    }


def _plain(value: object) -> object:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


async def _changed(
    session: AsyncSession,
    row: ChangeWindow,
    kind: ChangeKind,
    changes: list[Change],
    source: Source,
) -> None:
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind=kind,
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        ChangeWindowChanged(window_id=row.id, change=kind),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create_window(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> ChangeWindow:
    """Add a window: its kind, name and times are required; the mode follows the kind."""
    _require_manage(subject)
    clean = await _check(session, values)
    row = await WindowRepository(session).add(ChangeWindow(**clean))
    changes = [Change(k, None, _plain(v)) for k, v in clean.items() if v not in (None, [], False)]
    await _changed(session, row, "created", changes, source)
    return row


async def update_window(  # noqa: PLR0913 - the window, its version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    window_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> ChangeWindow:
    """Change a window (If-Match). Fields left out keep their value."""
    _require_manage(subject)
    row = await window(session, subject, window_id)
    merged = {**{k: getattr(row, k) for k in EDITABLE}, **values}
    clean = await _check(session, merged)
    changes = [
        Change(k, _plain(getattr(row, k)), _plain(v))
        for k, v in clean.items()
        if getattr(row, k) != v
    ]
    if not changes:
        if row.version != expected_version:
            raise Conflict(params={"current_version": row.version})
        return row
    updated = await WindowRepository(session).update(
        row.id, expected_version=expected_version, changes=clean
    )
    await _changed(session, updated, "updated", changes, source)
    return updated


async def delete_window(
    session: AsyncSession,
    subject: Subject,
    window_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a window (soft delete; its history stays)."""
    _require_manage(subject)
    await window(session, subject, window_id)
    removed = await WindowRepository(session).soft_delete(
        window_id, expected_version=expected_version
    )
    await _changed(session, removed, "deleted", [], source)


# --- a change's conflicts and its freeze override -------------------------------------------------


async def change_conflicts_of(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID
) -> tuple[WorkItem, list[rules.Conflict], dict[uuid.UUID, ChangeWindow], frozenset[uuid.UUID]]:
    """A change's conflicts now, the windows they name, and the freezes passed for it."""
    record = await items.visible_record(session, subject, CHANGE, record_id)
    found, named = await change_conflicts.conflicts(session, record)
    return record, found, named, await change_conflicts.passed_windows(session, record.id)


async def override_freeze(  # noqa: PLR0913 - the change, its version and why, explicit
    session: AsyncSession,
    subject: Subject,
    record_id: uuid.UUID,
    *,
    reason: str,
    window_ids: Sequence[uuid.UUID],
    expected_version: int,
    source: Source,
) -> WorkItem:
    """Pass these blocking freezes for this change, with a reason (ADR-042; D-144's pattern).

    Decided on this change at the scope it was granted (all, its site or its group): holding it
    for one group never reaches another group's change (lane B's review). Only the freezes named
    are passed: a different freeze, or one added later, still blocks until someone passes it too
    (lane B's review of #376). The route audits it.
    """
    record = await items.visible_record(session, subject, CHANGE, record_id)
    if items.is_closed(record):  # a closed or canceled change is locked (REQ-CHG-097)
        raise Conflict(code=items.RECORD_CLOSED, params={"status": record.status})
    if not await items.may(session, subject, CHANGE, OVERRIDE, record.id):
        raise PermissionDenied(
            params={
                "permission": OVERRIDE_PERMISSION,
                "reason": items.OUT_OF_SCOPE
                if subject.holds(OVERRIDE_PERMISSION)
                else "no_permission",
            }
        )
    if record.version != expected_version:
        raise Conflict(code="version_conflict", params={"current_version": record.version})
    text = " ".join((reason or "").split())
    if not text:
        raise items.field_errors([("reason", "reason_required")])
    if len(text) > REASON_MAX:
        raise items.field_errors([("reason", "value_too_long")])
    wanted = sorted(set(window_ids))
    freezes = set(
        await session.scalars(
            select(ChangeWindow.id).where(
                ChangeWindow.id.in_(wanted),
                ChangeWindow.deleted_at.is_(None),
                ChangeWindow.kind == rules.WindowKind.FREEZE.value,
                ChangeWindow.mode == rules.WindowMode.BLOCK.value,
            )
        )
    )
    if not wanted or freezes != set(wanted):
        raise items.field_errors([("window_ids", "required" if not wanted else "invalid_value")])
    # Locked: two overrides of one change apply one after the other (lane B's review).
    details = await session.scalar(
        select(WorkItemChangeDetails)
        .where(WorkItemChangeDetails.work_item_id == record.id)
        .with_for_update()
    )
    if details is None:
        details = WorkItemChangeDetails(tenant_id=record.tenant_id, work_item_id=record.id)
        session.add(details)
    before = sorted(str(w) for w in details.freeze_override_window_ids or [])
    passed = sorted({*(details.freeze_override_window_ids or []), *wanted})
    details.freeze_override_reason = text
    details.freeze_override_by = subject.user_id
    details.freeze_override_at = datetime.now(UTC)
    details.freeze_override_window_ids = passed
    await session.flush()
    return await items.save_detail_change(
        session,
        record,
        expected_version,
        [
            Change("freeze_override", None, text),
            Change("freeze_override_windows", before, sorted(str(w) for w in passed)),
        ],
        source=source,
        reason=text,
    )


# --- the change calendar (WP-045c S3; ADR-042 §5) -------------------------------------------------

CALENDAR_LIMIT = 2000  # entries in one range; a month of a busy tenant fits many times over


@dataclass(frozen=True)
class CalendarEntry:
    """A change's planned time on the calendar: its implementation window or a downtime."""

    record: WorkItem
    kind: str  # "window" (the implementation window) or "downtime"
    starts_at: datetime
    ends_at: datetime
    part_id: uuid.UUID | None = None  # the downtime, for a downtime
    version: int = 0  # the window's or downtime's own version (If-Match when moved)


async def calendar(
    session: AsyncSession,
    subject: Subject,
    *,
    start: datetime,
    end: datetime,
    mine: bool = False,
) -> list[CalendarEntry]:
    """The changes you may see planned in [start, end): windows and planned downtimes, by start.

    `mine`: only those you hold (technician). Windows are listed by `windows(start=, end=)`.
    """
    visible = items.staff_rows(subject, CHANGE).with_only_columns(WorkItem.id)
    if mine:
        visible = visible.where(WorkItem.technician_id == subject.user_id)
    windows_q = (
        select(WorkItem, WorkItemStageSchedule)
        .join(WorkItemStageSchedule, WorkItemStageSchedule.work_item_id == WorkItem.id)
        .where(
            WorkItem.id.in_(visible),
            WorkItemStageSchedule.stage == IMPLEMENTATION,
            WorkItemStageSchedule.scheduled_start < end,
            WorkItemStageSchedule.scheduled_end > start,
        )
        .limit(CALENDAR_LIMIT)
    )
    entries = [
        CalendarEntry(
            record=w,
            kind="window",
            starts_at=row.scheduled_start,
            ends_at=row.scheduled_end,
            version=row.version,
        )
        for w, row in await session.execute(windows_q)
        if row.scheduled_start is not None and row.scheduled_end is not None
    ]
    downtimes_q = (
        select(WorkItem, WorkItemDowntime)
        .join(WorkItemDowntime, WorkItemDowntime.work_item_id == WorkItem.id)
        .where(
            WorkItem.id.in_(visible),
            WorkItemDowntime.phase == "planned",
            WorkItemDowntime.deleted_at.is_(None),
            WorkItemDowntime.starts_at < end,
            WorkItemDowntime.ends_at > start,
        )
        .limit(CALENDAR_LIMIT)
    )
    entries += [
        CalendarEntry(
            record=w,
            kind="downtime",
            starts_at=d.starts_at,
            ends_at=d.ends_at,
            part_id=d.id,
            version=d.version,
        )
        for w, d in await session.execute(downtimes_q)
    ]
    return sorted(entries, key=lambda e: (e.starts_at, e.record.display_id))
