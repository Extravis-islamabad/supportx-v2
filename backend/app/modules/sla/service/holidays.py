"""Holiday lists and holidays (REQ-SLA-012; WP-025 session 1).

Every write: permission, rules (codes), versioned change, field history, outbox event. An
iCalendar import (`icalendar`, D-115 D9) adds what the file holds and reports what it skipped;
"copy to next year" adds the same named holidays a year later, flagged for review because
holidays such as Eid move (REQ-SLA-012 AC3). A change to a list changes the business time of
every calendar that uses it, so its event names those calendars.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.identity_access import Subject, user_names
from app.modules.sla.domain.calendar import HolidayPart
from app.modules.sla.domain.ical import IcalRefused, parse_holidays
from app.modules.sla.domain.setup import HolidayOrigin, holiday_problems, next_year
from app.modules.sla.events import SlaHolidayListDeleted, SlaHolidayListSaved
from app.modules.sla.infra.models import SlaCalendarHoliday, SlaHoliday, SlaHolidayList
from app.modules.sla.service.access import MANAGE, VIEW, require
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, explain_conflict, record_changes

LIST_RECORD_TYPE = "sla_holiday_list"
HOLIDAY_RECORD_TYPE = "sla_holiday"
NAME_MAX = 200
LANGUAGES = frozenset({"en", "ar", "ur"})
DUPLICATE = "duplicate"  # an imported or copied holiday the list already has

FIELD_PROBLEMS = frozenset(
    {
        "required",
        "name_taken",
        "invalid_language",
        "holiday_range_order",
        "holiday_range_too_long",
        "half_day_single_date",
        "ical_too_large",
        "ical_too_many_lines",
        "ical_not_utf8",
        "ical_invalid",
    }
)


class HolidayListRepository(Repository[SlaHolidayList]):
    """Holiday lists of the session's tenant."""

    model = SlaHolidayList


class HolidayRepository(Repository[SlaHoliday]):
    """Holidays of the session's tenant."""

    model = SlaHoliday


@dataclass(frozen=True)
class HolidayListView:
    """A holiday list, how many holidays it has and the calendars that use it."""

    holiday_list: SlaHolidayList
    holiday_count: int = 0
    calendar_ids: list[uuid.UUID] = field(default_factory=list)
    can_manage: bool = False


@dataclass(frozen=True)
class ImportReport:
    """What an import or a copy did: the holidays it added and what it left out, and why."""

    created: list[SlaHoliday] = field(default_factory=list)
    skipped: list[tuple[str | None, str]] = field(default_factory=list)


def _field(name: str, code: str) -> FieldError:
    return FieldError(field=f"body.{name}", code=code, message_key=f"errors.field.{code}")


def _name(value: object, errors: list[FieldError], name: str = "name") -> str:
    text = " ".join(str(value or "").split())
    if not text:
        errors.append(_field(name, "required"))
    return text[:NAME_MAX]


def _labels(value: Mapping[str, str] | None, errors: list[FieldError]) -> dict[str, str]:
    labels = {k: " ".join(v.split()) for k, v in (value or {}).items() if v and v.strip()}
    if set(labels) - LANGUAGES or any(len(v) > NAME_MAX for v in labels.values()):
        errors.append(_field("labels", "invalid_language"))
    return labels


async def _names(session: AsyncSession, ids: Sequence[str]) -> Sequence[str]:
    found = await user_names(session, list(ids))
    return [found.get(i, "") for i in ids]


async def _explained(
    session: AsyncSession, error: Conflict, record_type: str, record_id: uuid.UUID
) -> Conflict:
    return await explain_conflict(
        session,
        error,
        record_type=record_type,
        record_id=record_id,
        names=lambda ids: _names(session, ids),
    )


# --- reading ----------------------------------------------------------------------------------


async def _calendars_using(
    session: AsyncSession, list_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    using: dict[uuid.UUID, list[uuid.UUID]] = {i: [] for i in list_ids}
    if list_ids:
        for list_id, calendar_id in await session.execute(
            select(SlaCalendarHoliday.list_id, SlaCalendarHoliday.calendar_id).where(
                SlaCalendarHoliday.list_id.in_(list_ids)
            )
        ):
            using[list_id].append(calendar_id)
    return using


async def _list_row(session: AsyncSession, list_id: uuid.UUID) -> SlaHolidayList:
    row = await session.scalar(
        select(SlaHolidayList).where(
            SlaHolidayList.id == list_id, SlaHolidayList.deleted_at.is_(None)
        )
    )
    if row is None:
        raise NotFound(code="holiday_list_not_found", params={"id": str(list_id)})
    return row


async def list_holiday_lists(session: AsyncSession, subject: Subject) -> list[HolidayListView]:
    """Every holiday list by name, with its count and the calendars that use it."""
    require(subject, VIEW)
    rows = (
        await session.scalars(
            select(SlaHolidayList)
            .where(SlaHolidayList.deleted_at.is_(None))
            .order_by(SlaHolidayList.name)
        )
    ).all()
    ids = [row.id for row in rows]
    counts = (
        dict(
            (
                await session.execute(
                    select(SlaHoliday.list_id, func.count())
                    .where(SlaHoliday.list_id.in_(ids), SlaHoliday.deleted_at.is_(None))
                    .group_by(SlaHoliday.list_id)
                )
            )
            .tuples()
            .all()
        )
        if ids
        else {}
    )
    using = await _calendars_using(session, ids)
    manage = subject.holds(MANAGE)
    return [HolidayListView(row, int(counts.get(row.id, 0)), using[row.id], manage) for row in rows]


async def get_holiday_list(
    session: AsyncSession, subject: Subject, list_id: uuid.UUID
) -> HolidayListView:
    """One holiday list (404 for another tenant's or a deleted one)."""
    require(subject, VIEW)
    row = await _list_row(session, list_id)
    count = await session.scalar(
        select(func.count()).where(SlaHoliday.list_id == row.id, SlaHoliday.deleted_at.is_(None))
    )
    using = await _calendars_using(session, [row.id])
    return HolidayListView(row, int(count or 0), using[row.id], subject.holds(MANAGE))


async def list_holidays(
    session: AsyncSession, subject: Subject, list_id: uuid.UUID, *, year: int | None = None
) -> list[SlaHoliday]:
    """A list's holidays by date; `year`: those that touch that year."""
    require(subject, VIEW)
    await _list_row(session, list_id)
    query = select(SlaHoliday).where(SlaHoliday.list_id == list_id, SlaHoliday.deleted_at.is_(None))
    if year is not None:
        query = query.where(
            SlaHoliday.starts_on <= date(year, 12, 31), SlaHoliday.ends_on >= date(year, 1, 1)
        )
    return list(
        (await session.scalars(query.order_by(SlaHoliday.starts_on, SlaHoliday.name))).all()
    )


# --- lists ------------------------------------------------------------------------------------


async def _list_event(
    session: AsyncSession,
    row: SlaHolidayList,
    *,
    created: bool,
    fields: Sequence[str],
    holiday_ids: Sequence[uuid.UUID] = (),
) -> None:
    using = await _calendars_using(session, [row.id])
    await record_event(
        session,
        SlaHolidayListSaved(
            list_id=row.id,
            created=created,
            changed_fields=list(fields),
            holiday_ids=list(holiday_ids),
            calendar_ids=using[row.id],
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create_holiday_list(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any], *, source: Source
) -> HolidayListView:
    """A new, empty holiday list."""
    require(subject, MANAGE)
    errors: list[FieldError] = []
    row = SlaHolidayList(
        name=_name(values.get("name"), errors), labels=_labels(values.get("labels"), errors)
    )
    if errors:
        raise ValidationFailed(errors=errors)
    try:
        async with session.begin_nested():
            await HolidayListRepository(session).add(row)
    except IntegrityError:
        raise ValidationFailed(errors=[_field("name", "name_taken")]) from None
    await record_changes(
        session,
        record_type=LIST_RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created",
        changes=[Change("name", None, row.name), Change("labels", None, dict(row.labels))],
        source=source,
    )
    await _list_event(session, row, created=True, fields=[])
    return await get_holiday_list(session, subject, row.id)


async def update_holiday_list(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    list_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> HolidayListView:
    """Rename a list or change its translations."""
    require(subject, MANAGE)
    row = await _list_row(session, list_id)
    errors: list[FieldError] = []
    columns: dict[str, Any] = {}
    if "name" in values:
        columns["name"] = _name(values["name"], errors)
    if "labels" in values:
        columns["labels"] = _labels(values["labels"], errors)
    if errors:
        raise ValidationFailed(errors=errors)
    before = {"name": row.name, "labels": dict(row.labels)}
    columns = {k: v for k, v in columns.items() if before[k] != v}
    if not columns:
        return await get_holiday_list(session, subject, row.id)
    try:
        async with session.begin_nested():
            updated = await HolidayListRepository(session).update(
                row.id, expected_version=expected_version, changes=columns
            )
    except Conflict as error:
        raise await _explained(session, error, LIST_RECORD_TYPE, row.id) from None
    except IntegrityError:
        raise ValidationFailed(errors=[_field("name", "name_taken")]) from None
    await record_changes(
        session,
        record_type=LIST_RECORD_TYPE,
        record_id=row.id,
        version=updated.version,
        kind="updated",
        changes=[Change(k, before[k], v) for k, v in columns.items()],
        source=source,
    )
    await _list_event(session, updated, created=False, fields=sorted(columns))
    return await get_holiday_list(session, subject, row.id)


async def delete_holiday_list(
    session: AsyncSession,
    subject: Subject,
    list_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """To the trash with its holidays; the calendars that used it stop using it."""
    require(subject, MANAGE)
    await _list_row(session, list_id)
    using = (await _calendars_using(session, [list_id]))[list_id]
    try:
        deleted = await HolidayListRepository(session).soft_delete(
            list_id, expected_version=expected_version
        )
    except Conflict as error:
        raise await _explained(session, error, LIST_RECORD_TYPE, list_id) from None
    await session.execute(delete(SlaCalendarHoliday).where(SlaCalendarHoliday.list_id == list_id))
    await record_changes(
        session,
        record_type=LIST_RECORD_TYPE,
        record_id=list_id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        SlaHolidayListDeleted(list_id=list_id, calendar_ids=using),
        aggregate_id=list_id,
        aggregate_version=deleted.version,
    )


# --- holidays ---------------------------------------------------------------------------------


def _holiday_columns(
    values: Mapping[str, Any], current: SlaHoliday | None
) -> tuple[dict[str, Any], list[FieldError]]:
    errors: list[FieldError] = []
    columns: dict[str, Any] = {}
    if "name" in values or current is None:
        columns["name"] = _name(values.get("name"), errors)
    starts = values.get("starts_on", current.starts_on if current else None)
    ends = values.get("ends_on") or (
        current.ends_on if current and "starts_on" not in values else starts
    )
    part = HolidayPart(values.get("part") or (current.part if current else HolidayPart.FULL))
    if starts is None:
        errors.append(_field("starts_on", "required"))
        return columns, errors
    errors.extend(
        _field("part" if code == "half_day_single_date" else "ends_on", code)
        for code in holiday_problems(starts, ends, part)
    )
    columns |= {"starts_on": starts, "ends_on": ends, "part": part.value}
    return columns, errors


def _holiday_snapshot(row: SlaHoliday) -> dict[str, Any]:
    return {
        "name": row.name,
        "starts_on": row.starts_on.isoformat(),
        "ends_on": row.ends_on.isoformat(),
        "part": row.part,
        "needs_review": row.needs_review,
    }


async def _add(session: AsyncSession, row: SlaHoliday, source: Source) -> SlaHoliday:
    await HolidayRepository(session).add(row)
    await record_changes(
        session,
        record_type=HOLIDAY_RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created",
        changes=[Change(k, None, v) for k, v in _holiday_snapshot(row).items()],
        source=source,
    )
    return row


async def add_holiday(
    session: AsyncSession,
    subject: Subject,
    list_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    source: Source,
) -> SlaHoliday:
    """A holiday on a date, a range of whole days, or a half day."""
    require(subject, MANAGE)
    holiday_list = await _list_row(session, list_id)
    columns, errors = _holiday_columns(values, None)
    if errors:
        raise ValidationFailed(errors=errors)
    row = await _add(
        session, SlaHoliday(list_id=list_id, origin=HolidayOrigin.MANUAL.value, **columns), source
    )
    await _list_event(
        session, holiday_list, created=False, fields=["holidays"], holiday_ids=[row.id]
    )
    return row


async def _holiday_row(
    session: AsyncSession, list_id: uuid.UUID, holiday_id: uuid.UUID
) -> SlaHoliday:
    row = await session.scalar(
        select(SlaHoliday).where(
            SlaHoliday.id == holiday_id,
            SlaHoliday.list_id == list_id,
            SlaHoliday.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFound(code="holiday_not_found", params={"id": str(holiday_id)})
    return row


async def update_holiday(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    list_id: uuid.UUID,
    holiday_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> SlaHoliday:
    """Change a holiday; saving a copied one clears its "check this date" flag."""
    require(subject, MANAGE)
    holiday_list = await _list_row(session, list_id)
    row = await _holiday_row(session, list_id, holiday_id)
    columns, errors = _holiday_columns(values, row)
    if errors:
        raise ValidationFailed(errors=errors)
    columns["needs_review"] = bool(values.get("needs_review", False))
    before = _holiday_snapshot(row)
    changed = {k: v for k, v in columns.items() if getattr(row, k) != v}
    if not changed:
        return row
    try:
        updated = await HolidayRepository(session).update(
            row.id, expected_version=expected_version, changes=changed
        )
    except Conflict as error:
        raise await _explained(session, error, HOLIDAY_RECORD_TYPE, row.id) from None
    after = _holiday_snapshot(updated)
    await record_changes(
        session,
        record_type=HOLIDAY_RECORD_TYPE,
        record_id=row.id,
        version=updated.version,
        kind="updated",
        changes=[Change(k, before[k], after[k]) for k in after if before[k] != after[k]],
        source=source,
    )
    await _list_event(
        session, holiday_list, created=False, fields=["holidays"], holiday_ids=[row.id]
    )
    return updated


async def delete_holiday(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    list_id: uuid.UUID,
    holiday_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a holiday from its list."""
    require(subject, MANAGE)
    holiday_list = await _list_row(session, list_id)
    await _holiday_row(session, list_id, holiday_id)
    try:
        deleted = await HolidayRepository(session).soft_delete(
            holiday_id, expected_version=expected_version
        )
    except Conflict as error:
        raise await _explained(session, error, HOLIDAY_RECORD_TYPE, holiday_id) from None
    await record_changes(
        session,
        record_type=HOLIDAY_RECORD_TYPE,
        record_id=holiday_id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await _list_event(
        session, holiday_list, created=False, fields=["holidays"], holiday_ids=[holiday_id]
    )


async def _existing(session: AsyncSession, list_id: uuid.UUID) -> set[tuple[str, date, date]]:
    rows = await session.execute(
        select(SlaHoliday.name, SlaHoliday.starts_on, SlaHoliday.ends_on).where(
            SlaHoliday.list_id == list_id, SlaHoliday.deleted_at.is_(None)
        )
    )
    return {(name.casefold(), starts, ends) for name, starts, ends in rows}


async def import_ical(
    session: AsyncSession, subject: Subject, list_id: uuid.UUID, data: bytes, *, source: Source
) -> ImportReport:
    """Add the holidays of an iCalendar file; report each one skipped and why (REQ-SLA-012 AC2)."""
    require(subject, MANAGE)
    holiday_list = await _list_row(session, list_id)
    try:
        parsed = parse_holidays(data)
    except IcalRefused as refused:
        raise ValidationFailed(errors=[_field("file", refused.code)]) from None
    have = await _existing(session, list_id)
    report = ImportReport(skipped=[(s.name, s.reason.value) for s in parsed.skipped])
    for holiday in parsed.holidays:
        key = (holiday.name.casefold(), holiday.starts_on, holiday.ends_on)
        if key in have:
            report.skipped.append((holiday.name, DUPLICATE))
            continue
        have.add(key)
        row = SlaHoliday(
            list_id=list_id,
            name=holiday.name,
            starts_on=holiday.starts_on,
            ends_on=holiday.ends_on,
            part=HolidayPart.FULL.value,
            origin=HolidayOrigin.IMPORT.value,
        )
        report.created.append(await _add(session, row, source))
    if report.created:
        await _list_event(
            session,
            holiday_list,
            created=False,
            fields=["holidays"],
            holiday_ids=[r.id for r in report.created],
        )
    return report


async def copy_to_next_year(
    session: AsyncSession, subject: Subject, list_id: uuid.UUID, year: int, *, source: Source
) -> ImportReport:
    """The holidays that start in `year`, again a year later, each flagged for review (AC3)."""
    require(subject, MANAGE)
    holiday_list = await _list_row(session, list_id)
    have = await _existing(session, list_id)
    report = ImportReport()
    rows = await session.scalars(
        select(SlaHoliday)
        .where(
            SlaHoliday.list_id == list_id,
            SlaHoliday.deleted_at.is_(None),
            SlaHoliday.starts_on >= date(year, 1, 1),
            SlaHoliday.starts_on <= date(year, 12, 31),
        )
        .order_by(SlaHoliday.starts_on, SlaHoliday.name)
    )
    for holiday in rows.all():
        starts, ends = next_year(holiday.starts_on), next_year(holiday.ends_on)
        key = (holiday.name.casefold(), starts, ends)
        if key in have:
            report.skipped.append((holiday.name, DUPLICATE))
            continue
        have.add(key)
        copy = SlaHoliday(
            list_id=list_id,
            name=holiday.name,
            starts_on=starts,
            ends_on=ends,
            part=holiday.part,
            needs_review=True,
            origin=HolidayOrigin.COPY.value,
        )
        report.created.append(await _add(session, copy, source))
    if report.created:
        await _list_event(
            session,
            holiday_list,
            created=False,
            fields=["holidays"],
            holiday_ids=[r.id for r in report.created],
        )
    return report
