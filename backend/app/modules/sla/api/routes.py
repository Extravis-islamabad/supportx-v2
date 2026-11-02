"""SLA set-up API (WP-025 session 1): working calendars, holiday lists and holidays.

HTTP only: schemas, dependencies and status codes; the rules live in the services. Reading
needs `sla.view`, every change `sla.manage` (checked in the service) and is audited.
"""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail, ValidationFailed
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.sla.domain.calendar import HolidayPart
from app.modules.sla.domain.ical import MAX_BYTES
from app.modules.sla.domain.setup import WeekPreset
from app.modules.sla.infra.models import SlaHoliday
from app.modules.sla.service import calendars, holidays
from app.modules.sla.service.access import VIEW
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

Responses = dict[int | str, dict[str, Any]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such calendar, list or holiday."},
}
CONFLICT: Responses = {409: {"model": ProblemDetail, "description": "Stale If-Match or in use."}}
HHMM = r"^([01]\d|2[0-4]):[0-5]\d$"

router = APIRouter(
    prefix="/sla",
    tags=["sla"],
    dependencies=[Depends(rate_limit("sla"))],
    responses=RESPONSES,
)
Viewer = Annotated[Subject, Depends(require_permission(VIEW))]


# --- schemas ------------------------------------------------------------------------------------


class WorkingPeriod(BaseModel):
    """One working period on a weekday; an end not after the start runs past midnight."""

    model_config = ConfigDict(extra="forbid", title="SlaWorkingPeriod")

    weekday: int = Field(ge=0, le=6, description="0 = Monday ... 6 = Sunday.")
    start: str = Field(pattern=HHMM, examples=["09:00"])
    end: str = Field(pattern=HHMM, examples=["18:00"], description="24:00 is midnight.")


class CalendarUser(BaseModel):
    """A site or support group that names the calendar."""

    model_config = ConfigDict(title="SlaCalendarUser")

    id: uuid.UUID
    name: str


class CalendarOut(BaseModel):
    """A working calendar, who uses it and what you may do with it."""

    model_config = ConfigDict(title="SlaCalendar")

    id: uuid.UUID
    name: str
    labels: dict[str, str] = Field(description="Its name in other languages (ar, ur).")
    time_zone: str
    kind: str = Field(description="`sla_calendar_kind.<code>`: hours or around the clock.")
    system_key: str | None = Field(description="`sla_calendar.<key>`: a calendar every tenant has.")
    week: list[WorkingPeriod]
    holiday_list_ids: list[uuid.UUID]
    used_by_sites: list[CalendarUser]
    used_by_groups: list[CalendarUser]
    fixed: bool = Field(description="Around the clock: only the name can change.")
    can_manage: bool
    delete_refusal: str | None = Field(description="`action_reason.<code>` when it cannot go.")
    version: int

    @classmethod
    def of(cls, view: calendars.CalendarView) -> "CalendarOut":
        """The API form of a calendar view."""
        row = view.calendar
        return cls(
            id=row.id,
            name=row.name,
            labels=dict(row.labels),
            time_zone=row.time_zone,
            kind=row.kind,
            system_key=row.system_key,
            week=[WorkingPeriod.model_validate(p) for p in row.week],
            holiday_list_ids=view.holiday_list_ids,
            used_by_sites=[CalendarUser(id=s.id, name=s.name) for s in view.users.sites],
            used_by_groups=[CalendarUser(id=g.id, name=g.name) for g in view.users.groups],
            fixed=view.fixed,
            can_manage=view.can_manage,
            delete_refusal=view.delete_refusal,
            version=row.version,
        )


class CalendarIn(BaseModel):
    """A new operating-hours calendar: a week, or a preset (Monday to Friday by default)."""

    model_config = ConfigDict(extra="forbid", title="SlaCalendarIn")

    name: str = Field(min_length=1, max_length=200)
    labels: dict[str, str] = Field(default_factory=dict)
    time_zone: str = Field(min_length=1, max_length=64, examples=["Asia/Karachi"])
    preset: WeekPreset | None = None
    week: list[WorkingPeriod] | None = Field(default=None, max_length=28)
    holiday_list_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class CalendarPatch(BaseModel):
    """What to change (only what is sent); `holiday_list_ids` replaces the lists."""

    model_config = ConfigDict(extra="forbid", title="SlaCalendarPatch")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    labels: dict[str, str] | None = None
    time_zone: str | None = Field(default=None, min_length=1, max_length=64)
    preset: WeekPreset | None = None
    week: list[WorkingPeriod] | None = Field(default=None, max_length=28)
    holiday_list_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)


class HolidayListOut(BaseModel):
    """A holiday list, how many holidays it holds and the calendars that use it."""

    model_config = ConfigDict(title="SlaHolidayList")

    id: uuid.UUID
    name: str
    labels: dict[str, str]
    holiday_count: int
    calendar_ids: list[uuid.UUID]
    can_manage: bool
    version: int

    @classmethod
    def of(cls, view: holidays.HolidayListView) -> "HolidayListOut":
        """The API form of a holiday list view."""
        row = view.holiday_list
        return cls(
            id=row.id,
            name=row.name,
            labels=dict(row.labels),
            holiday_count=view.holiday_count,
            calendar_ids=view.calendar_ids,
            can_manage=view.can_manage,
            version=row.version,
        )


class HolidayListIn(BaseModel):
    """A new holiday list."""

    model_config = ConfigDict(extra="forbid", title="SlaHolidayListIn")

    name: str = Field(min_length=1, max_length=200)
    labels: dict[str, str] = Field(default_factory=dict)


class HolidayListPatch(BaseModel):
    """What to change (only what is sent)."""

    model_config = ConfigDict(extra="forbid", title="SlaHolidayListPatch")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    labels: dict[str, str] | None = None


class HolidayOut(BaseModel):
    """One holiday: a date or a range of whole days, or a half day."""

    model_config = ConfigDict(title="SlaHoliday")

    id: uuid.UUID
    list_id: uuid.UUID
    name: str
    starts_on: date
    ends_on: date
    part: HolidayPart = Field(description="`sla_holiday_part.<code>`.")
    needs_review: bool = Field(description="Copied to this year: check the date.")
    origin: str = Field(description="`sla_holiday_origin.<code>`.")
    version: int

    @classmethod
    def of(cls, row: SlaHoliday) -> "HolidayOut":
        """The API form of a holiday."""
        return cls(
            id=row.id,
            list_id=row.list_id,
            name=row.name,
            starts_on=row.starts_on,
            ends_on=row.ends_on,
            part=HolidayPart(row.part),
            needs_review=row.needs_review,
            origin=row.origin,
            version=row.version,
        )


class HolidayIn(BaseModel):
    """A new holiday; `ends_on` defaults to `starts_on`."""

    model_config = ConfigDict(extra="forbid", title="SlaHolidayIn")

    name: str = Field(min_length=1, max_length=200)
    starts_on: date
    ends_on: date | None = None
    part: HolidayPart = HolidayPart.FULL


class HolidayPatch(BaseModel):
    """What to change; a saved holiday is no longer flagged for review unless `needs_review`."""

    model_config = ConfigDict(extra="forbid", title="SlaHolidayPatch")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    starts_on: date | None = None
    ends_on: date | None = None
    part: HolidayPart | None = None
    needs_review: bool = False


class SkippedHoliday(BaseModel):
    """A holiday the import or copy left out, and why (`sla_import_skip.<code>`)."""

    model_config = ConfigDict(title="SlaSkippedHoliday")

    name: str | None
    reason: str


class HolidayImportOut(BaseModel):
    """What an import or a copy added and what it skipped."""

    model_config = ConfigDict(title="SlaHolidayImport")

    created: list[HolidayOut]
    skipped: list[SkippedHoliday]

    @classmethod
    def of(cls, report: holidays.ImportReport) -> "HolidayImportOut":
        """The API form of an import report."""
        return cls(
            created=[HolidayOut.of(h) for h in report.created],
            skipped=[SkippedHoliday(name=n, reason=r) for n, r in report.skipped],
        )


class CopyYearIn(BaseModel):
    """Copy the holidays that start in `year` to the year after."""

    model_config = ConfigDict(extra="forbid", title="SlaCopyYearIn")

    year: int = Field(ge=2000, le=2200)


class UploadTarget(BaseModel):
    """The Idempotency-Key fingerprint of an iCalendar upload."""

    list_id: uuid.UUID
    size: int
    head: str


def _sent(body: BaseModel) -> dict[str, Any]:
    values = {name: getattr(body, name) for name in body.model_fields_set}
    if "week" in values and values["week"] is not None:
        values["week"] = [p.model_dump() for p in values["week"]]
    return values


# --- calendars ----------------------------------------------------------------------------------


@router.get("/calendars", summary="Working calendars")
async def list_calendars(session: TenantSession, subject: Viewer) -> list[CalendarOut]:
    """Every calendar: around the clock and the default operating hours first."""
    return [CalendarOut.of(v) for v in await calendars.list_calendars(session, subject)]


@router.post(
    "/calendars",
    summary="Create a working calendar",
    status_code=status.HTTP_201_CREATED,
    response_model=CalendarOut,
)
async def create_calendar(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: CalendarIn,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("sla.calendar_created", object_type="sla_calendar")],
) -> Response:
    """Needs `sla.manage`. A week or a preset in a time zone, with holiday lists."""
    note.skip = True

    async def go() -> Created:
        view = await calendars.create_calendar(
            session, subject, _sent(body) | {"labels": body.labels}, source=source_of(request)
        )
        note.skip = False
        note.object_id = str(view.calendar.id)
        out = CalendarOut.of(view)
        return Created(body=out, headers={"ETag": f'"{out.version}"'})

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)


@router.get("/calendars/{calendar_id}", summary="One working calendar")
async def get_calendar(
    calendar_id: uuid.UUID, session: TenantSession, subject: Viewer, response: Response
) -> CalendarOut:
    """A calendar with its holiday lists and the sites and groups that use it."""
    view = await calendars.get_calendar(session, subject, calendar_id)
    set_etag(response, view.calendar.version)
    return CalendarOut.of(view)


@router.patch(
    "/calendars/{calendar_id}",
    summary="Change a working calendar",
    responses=CONFLICT,
    dependencies=[
        audited("sla.calendar_changed", object_type="sla_calendar", object_param="calendar_id")
    ],
)
async def update_calendar(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    calendar_id: uuid.UUID,
    body: CalendarPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> CalendarOut:
    """Needs `sla.manage` and If-Match. Around the clock: only its name and translations."""
    view = await calendars.update_calendar(
        session,
        subject,
        calendar_id,
        _sent(body),
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, view.calendar.version)
    return CalendarOut.of(view)


@router.delete(
    "/calendars/{calendar_id}",
    summary="Delete a working calendar",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[
        audited("sla.calendar_deleted", object_type="sla_calendar", object_param="calendar_id")
    ],
)
async def delete_calendar(
    calendar_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
) -> None:
    """Needs `sla.manage`. Refused (409) for a system calendar and one a site or group uses."""
    await calendars.delete_calendar(
        session, subject, calendar_id, expected_version=version, source=source_of(request)
    )


# --- holiday lists ------------------------------------------------------------------------------


@router.get("/holiday-lists", summary="Holiday lists")
async def list_holiday_lists(session: TenantSession, subject: Viewer) -> list[HolidayListOut]:
    """Every holiday list by name."""
    return [HolidayListOut.of(v) for v in await holidays.list_holiday_lists(session, subject)]


@router.post(
    "/holiday-lists",
    summary="Create a holiday list",
    status_code=status.HTTP_201_CREATED,
    response_model=HolidayListOut,
)
async def create_holiday_list(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: HolidayListIn,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("sla.holiday_list_created", object_type="sla_holiday_list")],
) -> Response:
    """Needs `sla.manage`."""
    note.skip = True

    async def go() -> Created:
        view = await holidays.create_holiday_list(
            session, subject, body.model_dump(), source=source_of(request)
        )
        note.skip = False
        note.object_id = str(view.holiday_list.id)
        out = HolidayListOut.of(view)
        return Created(body=out, headers={"ETag": f'"{out.version}"'})

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)


@router.get("/holiday-lists/{list_id}", summary="One holiday list")
async def get_holiday_list(
    list_id: uuid.UUID, session: TenantSession, subject: Viewer, response: Response
) -> HolidayListOut:
    """A holiday list with its count and the calendars that use it."""
    view = await holidays.get_holiday_list(session, subject, list_id)
    set_etag(response, view.holiday_list.version)
    return HolidayListOut.of(view)


@router.patch(
    "/holiday-lists/{list_id}",
    summary="Change a holiday list",
    responses=CONFLICT,
    dependencies=[
        audited("sla.holiday_list_changed", object_type="sla_holiday_list", object_param="list_id")
    ],
)
async def update_holiday_list(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    list_id: uuid.UUID,
    body: HolidayListPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> HolidayListOut:
    """Needs `sla.manage` and If-Match."""
    view = await holidays.update_holiday_list(
        session, subject, list_id, _sent(body), expected_version=version, source=source_of(request)
    )
    set_etag(response, view.holiday_list.version)
    return HolidayListOut.of(view)


@router.delete(
    "/holiday-lists/{list_id}",
    summary="Delete a holiday list",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[
        audited("sla.holiday_list_deleted", object_type="sla_holiday_list", object_param="list_id")
    ],
)
async def delete_holiday_list(
    list_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
) -> None:
    """Needs `sla.manage`. The calendars that used it stop using it."""
    await holidays.delete_holiday_list(
        session, subject, list_id, expected_version=version, source=source_of(request)
    )


# --- holidays -----------------------------------------------------------------------------------


@router.get("/holiday-lists/{list_id}/holidays", summary="A list's holidays")
async def list_holidays(
    list_id: uuid.UUID,
    session: TenantSession,
    subject: Viewer,
    year: Annotated[int | None, Query(ge=2000, le=2200)] = None,
) -> list[HolidayOut]:
    """By date; `year`: the holidays that touch that year."""
    rows = await holidays.list_holidays(session, subject, list_id, year=year)
    return [HolidayOut.of(row) for row in rows]


@router.post(
    "/holiday-lists/{list_id}/holidays",
    summary="Add a holiday",
    status_code=status.HTTP_201_CREATED,
    response_model=HolidayOut,
)
async def add_holiday(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    list_id: uuid.UUID,
    body: HolidayIn,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    idempotency: Idempotency,
    note: Annotated[
        AuditNote,
        audited("sla.holidays_changed", object_type="sla_holiday_list", object_param="list_id"),
    ],
) -> Response:
    """Needs `sla.manage`. A date, a range of whole days, or a morning or afternoon off."""
    del note

    async def go() -> Created:
        row = await holidays.add_holiday(
            session, subject, list_id, body.model_dump(), source=source_of(request)
        )
        return Created(body=HolidayOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/holiday-lists/{list_id}/holidays/{holiday_id}",
    summary="Change a holiday",
    responses=CONFLICT,
    dependencies=[
        audited("sla.holidays_changed", object_type="sla_holiday_list", object_param="list_id")
    ],
)
async def update_holiday(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    list_id: uuid.UUID,
    holiday_id: uuid.UUID,
    body: HolidayPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    response: Response,
) -> HolidayOut:
    """Needs `sla.manage` and If-Match. Saving clears "check this date" unless it is sent."""
    values = _sent(body) | {"needs_review": body.needs_review}
    row = await holidays.update_holiday(
        session,
        subject,
        list_id,
        holiday_id,
        values,
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return HolidayOut.of(row)


@router.delete(
    "/holiday-lists/{list_id}/holidays/{holiday_id}",
    summary="Remove a holiday",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[
        audited("sla.holidays_changed", object_type="sla_holiday_list", object_param="list_id")
    ],
)
async def delete_holiday(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    list_id: uuid.UUID,
    holiday_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Viewer,
    request: Request,
) -> None:
    """Needs `sla.manage`."""
    await holidays.delete_holiday(
        session, subject, list_id, holiday_id, expected_version=version, source=source_of(request)
    )


@router.post(
    "/holiday-lists/{list_id}/import",
    summary="Import holidays from an iCalendar file",
    status_code=status.HTTP_201_CREATED,
    response_model=HolidayImportOut,
)
async def import_holidays(  # noqa: PLR0913 - FastAPI dependencies
    *,
    list_id: uuid.UUID,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    idempotency: Idempotency,
    note: Annotated[
        AuditNote,
        audited("sla.holidays_imported", object_type="sla_holiday_list", object_param="list_id"),
    ],
) -> Response:
    """Needs `sla.manage`. The raw .ics file as the body (up to 1 MB); reports what it skipped."""
    content = bytearray()
    async for piece in request.stream():
        content += piece
        if len(content) > MAX_BYTES:
            raise ValidationFailed(code="ical_too_large")
    target = UploadTarget(list_id=list_id, size=len(content), head=bytes(content[:64]).hex())

    async def go() -> Created:
        report = await holidays.import_ical(
            session, subject, list_id, bytes(content), source=source_of(request)
        )
        note.details = {"created": len(report.created), "skipped": len(report.skipped)}
        return Created(body=HolidayImportOut.of(report))

    return await idempotency.run(target, go, status_code=status.HTTP_201_CREATED)


@router.post(
    "/holiday-lists/{list_id}/copy-year",
    summary="Copy a year's holidays to the next year",
    status_code=status.HTTP_201_CREATED,
    response_model=HolidayImportOut,
)
async def copy_year(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    list_id: uuid.UUID,
    body: CopyYearIn,
    session: TenantSession,
    subject: Viewer,
    request: Request,
    idempotency: Idempotency,
    note: Annotated[
        AuditNote,
        audited("sla.holidays_copied", object_type="sla_holiday_list", object_param="list_id"),
    ],
) -> Response:
    """Needs `sla.manage`. Each copy is flagged "check this date" (REQ-SLA-012 AC3)."""

    async def go() -> Created:
        report = await holidays.copy_to_next_year(
            session, subject, list_id, body.year, source=source_of(request)
        )
        note.details = {"year": body.year, "created": len(report.created)}
        return Created(body=HolidayImportOut.of(report))

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)
