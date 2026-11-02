"""Special working hours for a date range of a calendar (product owner, 2026-11-02; WP-025).

Ramadan 09:00-14:00 for a month, a Friday prayer break 12:30-14:00: inside the range its own
week replaces the calendar's week (rule: special date-range hours, `Calendar._week_on`).
Every write: permission, rules (codes), versioned change, field history, outbox event (the
calendar's, since its business time changed). Ranges of one calendar never overlap: the check
runs under a lock on the calendar row, so two admins cannot add overlapping ranges at once.
Around the clock has none.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.identity_access import Subject, user_names
from app.modules.sla.domain.calendar import CalendarKind, SpecialHours, special_hours_problems
from app.modules.sla.domain.setup import normal_week, periods_of, week_problems
from app.modules.sla.events import SlaCalendarSaved
from app.modules.sla.infra.models import SlaCalendar, SlaCalendarException
from app.modules.sla.service.access import MANAGE, require
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, explain_conflict, record_changes

RECORD_TYPE = "sla_calendar_exception"
NAME_MAX = 200

FIELD_PROBLEMS = frozenset(
    {
        "required",
        "exception_range_order",
        "exception_range_too_long",
        "exception_ranges_overlap",
        "period_time_invalid",
        "period_weekday_invalid",
        "periods_overlap",
        "week_too_many_periods",
        "system_calendar_fixed",
    }
)


class SpecialRepository(Repository[SlaCalendarException]):
    """Special date-range hours of the session's tenant."""

    model = SlaCalendarException


def _field(name: str, code: str) -> FieldError:
    return FieldError(field=f"body.{name}", code=code, message_key=f"errors.field.{code}")


async def _calendar(session: AsyncSession, calendar_id: uuid.UUID) -> SlaCalendar:
    """The calendar, locked for the rest of the transaction (serialises the overlap check)."""
    row = await session.scalar(
        select(SlaCalendar)
        .where(SlaCalendar.id == calendar_id, SlaCalendar.deleted_at.is_(None))
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="calendar_not_found", params={"id": str(calendar_id)})
    if row.kind == CalendarKind.AROUND_THE_CLOCK:
        raise ValidationFailed(errors=[_field("calendar_id", "system_calendar_fixed")])
    return row


async def _others(
    session: AsyncSession, calendar_id: uuid.UUID, except_id: uuid.UUID | None
) -> list[SlaCalendarException]:
    query = select(SlaCalendarException).where(
        SlaCalendarException.calendar_id == calendar_id, SlaCalendarException.deleted_at.is_(None)
    )
    if except_id is not None:
        query = query.where(SlaCalendarException.id != except_id)
    return list((await session.scalars(query)).all())


def _check(
    name: str,
    starts_on: date,
    ends_on: date,
    week: Sequence[Mapping[str, Any]],
    others: Sequence[SlaCalendarException],
) -> list[FieldError]:
    errors: list[FieldError] = []
    if not name:
        errors.append(_field("name", "required"))
    shape = week_problems(week) if week else []
    errors.extend(_field("week", code) for code in shape if code != "week_empty")
    if shape and shape != ["week_empty"]:
        return errors
    mine = SpecialHours(starts_on, ends_on, periods_of(week))
    ranges = [mine, *(SpecialHours(o.starts_on, o.ends_on, ()) for o in others)]
    for code in special_hours_problems(ranges):
        target = "starts_on" if code == "exception_ranges_overlap" else "ends_on"
        errors.append(_field(target if code.startswith("exception") else "week", code))
    return errors


def _snapshot(row: SlaCalendarException) -> dict[str, Any]:
    return {
        "name": row.name,
        "starts_on": row.starts_on.isoformat(),
        "ends_on": row.ends_on.isoformat(),
        "week": list(row.week),
    }


async def _names(session: AsyncSession, ids: Sequence[str]) -> Sequence[str]:
    found = await user_names(session, list(ids))
    return [found.get(i, "") for i in ids]


async def _saved(session: AsyncSession, calendar: SlaCalendar) -> None:
    await record_event(
        session,
        SlaCalendarSaved(calendar_id=calendar.id, created=False, changed_fields=["special_hours"]),
        aggregate_id=calendar.id,
        aggregate_version=calendar.version,
    )


async def add_special_hours(
    session: AsyncSession,
    subject: Subject,
    calendar_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    source: Source,
) -> SlaCalendarException:
    """New special hours for a date range of the calendar."""
    require(subject, MANAGE)
    calendar = await _calendar(session, calendar_id)
    name = " ".join(str(values.get("name") or "").split())[:NAME_MAX]
    week = list(values.get("week") or [])
    errors = _check(
        name,
        values["starts_on"],
        values["ends_on"],
        week,
        await _others(session, calendar.id, None),
    )
    if errors:
        raise ValidationFailed(errors=errors)
    row = SlaCalendarException(
        calendar_id=calendar.id,
        name=name,
        starts_on=values["starts_on"],
        ends_on=values["ends_on"],
        week=normal_week(week) if week else [],
    )
    await SpecialRepository(session).add(row)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created",
        changes=[Change(k, None, v) for k, v in _snapshot(row).items()],
        source=source,
    )
    await _saved(session, calendar)
    return row


async def update_special_hours(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    calendar_id: uuid.UUID,
    special_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> SlaCalendarException:
    """Change a range's name, dates or week (only what is sent)."""
    require(subject, MANAGE)
    calendar = await _calendar(session, calendar_id)
    row = await _row(session, calendar.id, special_id)
    before = _snapshot(row)
    name = " ".join(str(values.get("name", row.name) or "").split())[:NAME_MAX]
    starts_on = values.get("starts_on") or row.starts_on
    ends_on = values.get("ends_on") or row.ends_on
    week = list(values["week"] or []) if "week" in values else list(row.week)
    errors = _check(name, starts_on, ends_on, week, await _others(session, calendar.id, row.id))
    if errors:
        raise ValidationFailed(errors=errors)
    columns = {
        "name": name,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "week": normal_week(week) if week else [],
    }
    columns = {k: v for k, v in columns.items() if getattr(row, k) != v}
    if not columns:
        return row
    try:
        updated = await SpecialRepository(session).update(
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
    after = _snapshot(updated)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=updated.version,
        kind="updated",
        changes=[Change(k, before[k], after[k]) for k in after if before[k] != after[k]],
        source=source,
    )
    await _saved(session, calendar)
    return updated


async def _row(
    session: AsyncSession, calendar_id: uuid.UUID, special_id: uuid.UUID
) -> SlaCalendarException:
    row = await session.scalar(
        select(SlaCalendarException).where(
            SlaCalendarException.id == special_id,
            SlaCalendarException.calendar_id == calendar_id,
            SlaCalendarException.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFound(code="special_hours_not_found", params={"id": str(special_id)})
    return row


async def delete_special_hours(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    calendar_id: uuid.UUID,
    special_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a range; the calendar's normal week applies on those dates again."""
    require(subject, MANAGE)
    calendar = await _calendar(session, calendar_id)
    await _row(session, calendar.id, special_id)
    try:
        deleted = await SpecialRepository(session).soft_delete(
            special_id, expected_version=expected_version
        )
    except Conflict as error:
        raise await explain_conflict(
            session,
            error,
            record_type=RECORD_TYPE,
            record_id=special_id,
            names=lambda ids: _names(session, ids),
        ) from None
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=special_id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await _saved(session, calendar)
