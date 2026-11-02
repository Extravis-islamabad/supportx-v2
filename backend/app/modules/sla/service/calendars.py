"""Working calendars (REQ-SLA-010, 013, REQ-ADM-040; WP-025 session 1).

Every write: permission, rules (codes), versioned change, field history, outbox event. Every
tenant has two system calendars, created on first use (D-041): "around the clock", which cannot
change or go, and the default operating hours (Monday to Friday 09:00-18:00 in the default
site's time zone, D-115 D2), which can change but not go. A calendar a site or group uses
cannot be deleted; the refusal names them (REQ-ADM-040 AC2).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules import organization
from app.modules.identity_access import Subject, user_names
from app.modules.sla.domain.calendar import Calendar, CalendarKind, HolidayPart, zone_or_none
from app.modules.sla.domain.setup import (
    DEFAULT_PRESET,
    DEFAULT_ZONE,
    HolidayDates,
    SpecialRange,
    SystemCalendar,
    WeekPreset,
    build_calendar,
    normal_week,
    preset_week,
    week_problems,
)
from app.modules.sla.events import SlaCalendarDeleted, SlaCalendarSaved
from app.modules.sla.infra.models import (
    SlaCalendar,
    SlaCalendarException,
    SlaCalendarHoliday,
    SlaHoliday,
    SlaHolidayList,
)
from app.modules.sla.service.access import MANAGE, VIEW, require
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, explain_conflict, record_changes
from app.shared.ids import new_id

RECORD_TYPE = "sla_calendar"
NAME_MAX = 200
LANGUAGES = frozenset({"en", "ar", "ur"})
# The system calendars' English names (their labels in the UI come from `sla_calendar.<key>`).
SYSTEM_NAMES: Mapping[SystemCalendar, str] = {
    SystemCalendar.AROUND_THE_CLOCK: "Around the clock",
    SystemCalendar.OPERATING_HOURS: "Operating hours",
}
_HISTORY_FIELDS = ("name", "labels", "time_zone", "week", "holiday_list_ids")

# Every field problem code this module returns (labels `errors.field.<code>`, checked in CI).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "name_taken",
        "unknown_time_zone",
        "invalid_language",
        "week_empty",
        "week_too_many_periods",
        "period_time_invalid",
        "period_weekday_invalid",
        "periods_overlap",
        "holiday_list_not_found",
        "system_calendar_fixed",
    }
)


class CalendarRepository(Repository[SlaCalendar]):
    """Calendars of the session's tenant."""

    model = SlaCalendar


@dataclass(frozen=True)
class CalendarView:
    """A calendar with its holiday lists, who uses it and what the viewer may do with it."""

    calendar: SlaCalendar
    holiday_list_ids: list[uuid.UUID] = field(default_factory=list)
    users: organization.CalendarUsers = field(default_factory=organization.CalendarUsers)
    can_manage: bool = False
    special: list[SlaCalendarException] = field(default_factory=list)

    @property
    def delete_refusal(self) -> str | None:
        """Why it cannot be deleted (an `action_reason` code), or None."""
        if self.calendar.system_key is not None:
            return "system_calendar"
        if self.users.count:
            return "calendar_in_use"
        return None

    @property
    def fixed(self) -> bool:
        """Around the clock: only its name and translations can change."""
        return self.calendar.kind == CalendarKind.AROUND_THE_CLOCK


def _field(name: str, code: str, **params: Any) -> FieldError:  # noqa: ANN401 - label params
    return FieldError(
        field=f"body.{name}", code=code, message_key=f"errors.field.{code}", params=params
    )


def _invalid(errors: Sequence[FieldError]) -> ValidationFailed:
    return ValidationFailed(errors=list(errors))


# --- system calendars -----------------------------------------------------------------------


async def ensure_system_calendars(session: AsyncSession) -> None:
    """Create the two system calendars if the tenant has not got them yet (idempotent)."""
    present = set(
        await session.scalars(
            select(SlaCalendar.system_key).where(
                SlaCalendar.system_key.is_not(None), SlaCalendar.deleted_at.is_(None)
            )
        )
    )
    missing = [key for key in SystemCalendar if key.value not in present]
    if not missing:
        return
    context = session.info[SESSION_TENANT_KEY]
    zone = (await organization.site_defaults(session)).time_zone
    zone = zone if zone and zone_or_none(zone) else DEFAULT_ZONE
    for key in missing:
        around = key is SystemCalendar.AROUND_THE_CLOCK
        await session.execute(
            insert(SlaCalendar)
            .values(
                id=new_id(),
                tenant_id=context.tenant_id,
                name=SYSTEM_NAMES[key],
                labels={},
                time_zone=DEFAULT_ZONE if around else zone,
                kind=CalendarKind.AROUND_THE_CLOCK if around else CalendarKind.HOURS,
                week=[] if around else preset_week(DEFAULT_PRESET),
                system_key=key.value,
            )
            # A parallel first request made it already, or a calendar holds the name.
            .on_conflict_do_nothing()
        )


async def system_calendar_id(session: AsyncSession, key: SystemCalendar) -> uuid.UUID:
    """The ID of a system calendar (created if needed)."""
    await ensure_system_calendars(session)
    found = await session.scalar(
        select(SlaCalendar.id).where(
            SlaCalendar.system_key == key.value, SlaCalendar.deleted_at.is_(None)
        )
    )
    if found is None:  # pragma: no cover - the name was taken before the calendar was made
        raise NotFound(code="calendar_not_found")
    return found


# --- reading ----------------------------------------------------------------------------------


async def _links(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    links: dict[uuid.UUID, list[uuid.UUID]] = {i: [] for i in ids}
    if ids:
        rows = await session.execute(
            select(SlaCalendarHoliday.calendar_id, SlaCalendarHoliday.list_id)
            .join(
                SlaHolidayList,
                (SlaHolidayList.id == SlaCalendarHoliday.list_id)
                & SlaHolidayList.deleted_at.is_(None),
            )
            .where(SlaCalendarHoliday.calendar_id.in_(ids))
            .order_by(SlaHolidayList.name)
        )
        for calendar_id, list_id in rows:
            links[calendar_id].append(list_id)
    return links


async def _views(
    session: AsyncSession, subject: Subject, rows: Sequence[SlaCalendar]
) -> list[CalendarView]:
    ids = [row.id for row in rows]
    links = await _links(session, ids)
    users = await organization.calendar_users(session, ids)
    manage = subject.holds(MANAGE)
    special = await special_of(session, ids)
    return [
        CalendarView(row, links[row.id], users[row.id], manage, special[row.id]) for row in rows
    ]


async def special_of(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[SlaCalendarException]]:
    """Each calendar's live special date-range hours, by first day."""
    found: dict[uuid.UUID, list[SlaCalendarException]] = {i: [] for i in ids}
    if ids:
        rows = await session.scalars(
            select(SlaCalendarException)
            .where(
                SlaCalendarException.calendar_id.in_(ids),
                SlaCalendarException.deleted_at.is_(None),
            )
            .order_by(SlaCalendarException.starts_on)
        )
        for row in rows:
            found[row.calendar_id].append(row)
    return found


async def list_calendars(session: AsyncSession, subject: Subject) -> list[CalendarView]:
    """Every calendar: the system ones first, then by name."""
    require(subject, VIEW)
    await ensure_system_calendars(session)
    rows = (
        await session.scalars(
            select(SlaCalendar)
            .where(SlaCalendar.deleted_at.is_(None))
            .order_by(SlaCalendar.system_key.is_(None), SlaCalendar.system_key, SlaCalendar.name)
        )
    ).all()
    return await _views(session, subject, rows)


async def _row(session: AsyncSession, calendar_id: uuid.UUID) -> SlaCalendar:
    row = await session.scalar(
        select(SlaCalendar).where(SlaCalendar.id == calendar_id, SlaCalendar.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="calendar_not_found", params={"id": str(calendar_id)})
    return row


async def get_calendar(
    session: AsyncSession, subject: Subject, calendar_id: uuid.UUID
) -> CalendarView:
    """One calendar (404 for another tenant's or a deleted one)."""
    require(subject, VIEW)
    (view,) = await _views(session, subject, [await _row(session, calendar_id)])
    return view


async def calendar_exists(session: AsyncSession, calendar_id: uuid.UUID) -> bool:
    """Whether a site or group may name this calendar (organization's check, D-115 D3)."""
    found = await session.scalar(
        select(SlaCalendar.id).where(
            SlaCalendar.id == calendar_id, SlaCalendar.deleted_at.is_(None)
        )
    )
    return found is not None


async def calendar_for_maths(session: AsyncSession, calendar_id: uuid.UUID) -> Calendar:
    """The calendar ready for business-time maths, with every holiday of its lists."""
    row = await _row(session, calendar_id)
    holidays = (
        await session.execute(
            select(SlaHoliday.starts_on, SlaHoliday.ends_on, SlaHoliday.part)
            .join(SlaCalendarHoliday, SlaCalendarHoliday.list_id == SlaHoliday.list_id)
            .join(
                SlaHolidayList,
                (SlaHolidayList.id == SlaHoliday.list_id) & SlaHolidayList.deleted_at.is_(None),
            )
            .where(SlaCalendarHoliday.calendar_id == row.id, SlaHoliday.deleted_at.is_(None))
        )
    ).all()
    special = (await special_of(session, [row.id]))[row.id]
    return build_calendar(
        kind=row.kind,
        time_zone=row.time_zone,
        week=row.week,
        holidays=[HolidayDates(s, e, HolidayPart(p)) for s, e, p in holidays],
        special=[SpecialRange(x.starts_on, x.ends_on, x.week) for x in special],
    )


# --- writing ----------------------------------------------------------------------------------


def _labels(value: Mapping[str, str] | None, errors: list[FieldError]) -> dict[str, str]:
    labels = {k: " ".join(v.split()) for k, v in (value or {}).items() if v and v.strip()}
    if set(labels) - LANGUAGES or any(len(v) > NAME_MAX for v in labels.values()):
        errors.append(_field("labels", "invalid_language"))
    return labels


def _columns(values: Mapping[str, Any], *, fixed: bool) -> tuple[dict[str, Any], list[FieldError]]:
    """The columns of a create or edit, and the field problems (all at once)."""
    errors: list[FieldError] = []
    columns: dict[str, Any] = {}
    if "name" in values:
        name = " ".join(str(values["name"] or "").split())
        if not name:
            errors.append(_field("name", "required"))
        columns["name"] = name[:NAME_MAX]
    if "labels" in values:
        columns["labels"] = _labels(values["labels"], errors)
    shape = {"time_zone", "week", "preset"} & set(values)
    if fixed and shape:
        errors.extend(_field(name, "system_calendar_fixed") for name in sorted(shape))
        return columns, errors
    if "time_zone" in values:
        zone = str(values["time_zone"] or "")
        if zone_or_none(zone) is None:
            errors.append(_field("time_zone", "unknown_time_zone"))
        columns["time_zone"] = zone
    week = values.get("week")
    if week is None and values.get("preset") is not None:
        week = preset_week(WeekPreset(values["preset"]))
    if week is not None:
        problems = week_problems(week)
        errors.extend(_field("week", code) for code in problems)
        if not problems:
            columns["week"] = normal_week(week)
    return columns, errors


async def _check_lists(session: AsyncSession, list_ids: Sequence[uuid.UUID]) -> list[FieldError]:
    if not list_ids:
        return []
    known = set(
        await session.scalars(
            select(SlaHolidayList.id).where(
                SlaHolidayList.id.in_(list_ids), SlaHolidayList.deleted_at.is_(None)
            )
        )
    )
    return [] if known >= set(list_ids) else [_field("holiday_list_ids", "holiday_list_not_found")]


async def _replace_lists(
    session: AsyncSession, calendar_id: uuid.UUID, list_ids: Sequence[uuid.UUID]
) -> None:
    await session.execute(
        delete(SlaCalendarHoliday).where(SlaCalendarHoliday.calendar_id == calendar_id)
    )
    context = session.info[SESSION_TENANT_KEY]
    for list_id in dict.fromkeys(list_ids):
        session.add(
            SlaCalendarHoliday(
                tenant_id=context.tenant_id, calendar_id=calendar_id, list_id=list_id
            )
        )
    await session.flush()


def _snapshot(row: SlaCalendar, list_ids: Sequence[uuid.UUID]) -> dict[str, Any]:
    return {
        "name": row.name,
        "labels": dict(row.labels),
        "time_zone": row.time_zone,
        "week": list(row.week),
        "holiday_list_ids": sorted(str(i) for i in list_ids),
    }


async def _names(session: AsyncSession, ids: Sequence[str]) -> Sequence[str]:
    found = await user_names(session, list(ids))
    return [found.get(i, "") for i in ids]


async def create_calendar(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> CalendarView:
    """A new operating-hours calendar: a name, a time zone, a week or a preset, holiday lists."""
    require(subject, MANAGE)
    await ensure_system_calendars(session)
    values = {"preset": DEFAULT_PRESET.value, **values} if "week" not in values else values
    columns, errors = _columns(values, fixed=False)
    for required in ("name", "time_zone"):
        if required not in values:
            errors.append(_field(required, "required"))
    list_ids: list[uuid.UUID] = list(values.get("holiday_list_ids") or [])
    errors += await _check_lists(session, list_ids)
    if errors:
        raise _invalid(errors)
    row = SlaCalendar(**{"kind": CalendarKind.HOURS.value, "labels": {}, **columns})
    try:
        async with session.begin_nested():
            await CalendarRepository(session).add(row)
    except IntegrityError:
        raise _invalid([_field("name", "name_taken")]) from None
    await _replace_lists(session, row.id, list_ids)
    after = _snapshot(row, list_ids)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created",
        changes=[Change(k, None, v) for k, v in after.items()],
        source=source,
    )
    await record_event(
        session,
        SlaCalendarSaved(calendar_id=row.id, created=True, changed_fields=[]),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return await get_calendar(session, subject, row.id)


async def update_calendar(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    calendar_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> CalendarView:
    """Change a calendar's name, translations, zone, week or holiday lists (only what is sent).

    Around the clock keeps its shape: only the name and translations change.
    """
    require(subject, MANAGE)
    row = await _row(session, calendar_id)
    links = (await _links(session, [row.id]))[row.id]
    before = _snapshot(row, links)
    fixed = row.kind == CalendarKind.AROUND_THE_CLOCK
    columns, errors = _columns(values, fixed=fixed)
    list_ids = links
    if "holiday_list_ids" in values:
        if fixed:
            errors.append(_field("holiday_list_ids", "system_calendar_fixed"))
        list_ids = list(dict.fromkeys(values["holiday_list_ids"] or []))
        errors += await _check_lists(session, list_ids)
    if errors:
        raise _invalid(errors)
    columns = {k: v for k, v in columns.items() if getattr(row, k) != v}
    lists_changed = sorted(map(str, list_ids)) != before["holiday_list_ids"]
    if not columns and not lists_changed:  # a no-op save: no new version, no event
        return await get_calendar(session, subject, row.id)
    try:
        async with session.begin_nested():
            updated = await CalendarRepository(session).update(
                row.id, expected_version=expected_version, changes=columns
            )
    except Conflict as error:
        raise await explain_conflict(
            session,
            error,
            record_type=RECORD_TYPE,
            record_id=row.id,
            names=lambda ids: _names(session, ids),
        ) from None
    except IntegrityError:
        raise _invalid([_field("name", "name_taken")]) from None
    if lists_changed:
        await _replace_lists(session, row.id, list_ids)
    after = _snapshot(updated, list_ids)
    changes = [Change(k, before[k], after[k]) for k in _HISTORY_FIELDS if before[k] != after[k]]
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        SlaCalendarSaved(
            calendar_id=updated.id, created=False, changed_fields=[c.field for c in changes]
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return await get_calendar(session, subject, updated.id)


async def delete_calendar(
    session: AsyncSession,
    subject: Subject,
    calendar_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """To the trash; refused for a system calendar and one in use, naming its users."""
    require(subject, MANAGE)
    view = await get_calendar(session, subject, calendar_id)
    if view.calendar.system_key is not None:
        raise Conflict(code="system_calendar_required")
    if view.users.count:
        raise Conflict(
            code="calendar_in_use",
            params={
                "sites": ", ".join(s.name for s in view.users.sites),
                "groups": ", ".join(g.name for g in view.users.groups),
                "count": view.users.count,
            },
        )
    try:
        deleted = await CalendarRepository(session).soft_delete(
            calendar_id, expected_version=expected_version
        )
    except Conflict as error:
        raise await explain_conflict(
            session,
            error,
            record_type=RECORD_TYPE,
            record_id=calendar_id,
            names=lambda ids: _names(session, ids),
        ) from None
    await session.execute(
        delete(SlaCalendarHoliday).where(SlaCalendarHoliday.calendar_id == calendar_id)
    )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=calendar_id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        SlaCalendarDeleted(calendar_id=calendar_id),
        aggregate_id=calendar_id,
        aggregate_version=deleted.version,
    )
