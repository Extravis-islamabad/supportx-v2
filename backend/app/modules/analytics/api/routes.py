"""Reports API (WP-035): run a definition, the library, saved reports, folders, favourites.

Every route needs `reports.view`; the entity's licence feature and list permission are checked
per run (REQ-RPT-048). Results carry codes and ids with the metadata the UI needs to label them
(rule d); the UI renders every value through the labels package.
"""

import uuid
from datetime import date, datetime
from datetime import time as time_type
from typing import Annotated, Any, Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission
from app.core.database import Database, TenantSession
from app.core.entitlements import ENTITLEMENT_GATE_STATE, EntitlementGate, read_only_exempt
from app.core.errors import (
    AppError,
    FieldError,
    ProblemDetail,
    ServiceUnavailable,
    ValidationFailed,
)
from app.core.tenancy import TenantContext, resolve_tenant
from app.modules.analytics.domain.builtin import BUILTIN_REPORTS
from app.modules.analytics.domain.definition import ReportDefinition
from app.modules.analytics.domain.schedule import Frequency
from app.modules.analytics.infra.models import ReportExport, ReportSchedule, ReportSettings
from app.modules.analytics.service import exports, library, schedules
from app.modules.analytics.service.compiler import available_measures, compile_report
from app.modules.analytics.service.jobs import storage_or_none
from app.modules.analytics.service.runner import (
    ReportResult,
    TenantSlots,
    resolve_provider,
    run_report,
)
from app.modules.analytics.service.settings import limits_of, tenant_settings, update_settings
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import request_zone
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of
from app.shared.mail import mail_configured
from app.shared.reporting import ReportingSource, registered_entities
from app.shared.storage import ObjectStorage

REPORTING_DB_STATE = "reporting_db"
SLOTS_STATE = "report_slots"

Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such report visible to you."},
}
CONFLICT: Responses = {
    409: {"model": ProblemDetail, "description": "Stale If-Match: version_conflict."}
}

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(rate_limit("reports"))],
    responses=RESPONSES,
)

View = Annotated[Subject, Depends(require_permission(library.VIEW))]
Tenant = Annotated[TenantContext, Depends(resolve_tenant)]


# --- schemas --------------------------------------------------------------------------------------


class ReportGroupOut(BaseModel):
    """How to label one grouping's keys."""

    field: str
    kind: str  # DimensionKind code
    label_prefix: str | None
    reference: str | None
    bucket: str | None


class ReportMeasureOut(BaseModel):
    """A measure: its code labels it (`measure.<entity>.<code>`), its unit formats it."""

    code: str
    unit: str
    better: str


class ReportRowOut(BaseModel):
    """One group: keys (codes, ids, ISO bucket starts), values, and the list filter behind it."""

    keys: list[Any]
    values: list[float | int | None]
    drill: Any = Field(description="Filter DSL for the entity's list: exactly these records.")


class ReportResultOut(BaseModel):
    """A run's result."""

    entity: str
    list_path: str
    as_of: datetime
    time_zone: str
    groups: list[ReportGroupOut]
    measures: list[ReportMeasureOut]
    rows: list[ReportRowOut]
    totals: list[float | int | None]
    truncated: bool
    drill_all: Any = Field(description="Filter DSL behind the totals.")

    @classmethod
    def of(cls, result: ReportResult) -> "ReportResultOut":
        """From the service result."""
        return cls(
            entity=result.entity,
            list_path=result.list_path,
            as_of=result.as_of,
            time_zone=result.time_zone,
            groups=[
                ReportGroupOut(
                    field=g.field,
                    kind=g.dimension.kind.value,
                    label_prefix=g.dimension.label_prefix,
                    reference=g.dimension.reference,
                    bucket=g.bucket.value if g.bucket else None,
                )
                for g in result.groups
            ],
            measures=[
                ReportMeasureOut(code=m.code, unit=m.unit, better=m.better) for m in result.measures
            ],
            rows=[
                ReportRowOut(keys=list(r.keys), values=list(r.values), drill=r.drill)
                for r in result.rows
            ],
            totals=list(result.totals),
            truncated=result.truncated,
            drill_all=result.drill_all,
        )


class ReportRunIn(BaseModel):
    """A definition to run (a built-in one, a saved one, or one being adjusted)."""

    model_config = ConfigDict(extra="forbid")

    definition: ReportDefinition


class ReportFieldOut(BaseModel):
    """A field of an entity: filterable always, groupable when `dimension` is set."""

    name: str
    type: str
    values: list[str]
    multiple: bool
    dimension: ReportGroupOut | None


class ReportEntityOut(BaseModel):
    """What a report on this entity can use (the copy-and-adjust form, REQ-RPT-019)."""

    entity: str
    list_path: str
    fields: list[ReportFieldOut]
    measures: list[ReportMeasureOut]


class BuiltinReportOut(BaseModel):
    """A shipped report; `report.<code>` and `report.<code>.description` label it."""

    code: str
    folder: str
    definition: ReportDefinition


class ReportFolderOut(BaseModel):
    """A shared folder."""

    id: uuid.UUID
    name: str
    version: int


class SavedReportOut(BaseModel):
    """A saved report."""

    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    folder_id: uuid.UUID | None
    copied_from: str | None
    definition: ReportDefinition
    version: int
    updated_at: datetime
    can_edit: bool

    @classmethod
    def of(cls, found: library.SavedReport) -> "SavedReportOut":
        """From the service view."""
        r = found.record
        return cls(
            id=r.id,
            name=r.name,
            description=r.description,
            owner_id=r.owner_id,
            folder_id=r.folder_id,
            copied_from=r.copied_from,
            definition=ReportDefinition.model_validate(r.definition),
            version=r.version,
            updated_at=r.updated_at,
            can_edit=found.can_edit,
        )


class ReportLibraryOut(BaseModel):
    """The reports home: built-in reports the viewer can run, folders, saved reports, stars."""

    builtin: list[BuiltinReportOut]
    folders: list[ReportFolderOut]
    reports: list[SavedReportOut]
    favourites: list[str]


class ReportIn(BaseModel):
    """A new saved report; with no folder it goes to "My reports", private (REQ-RPT-047)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    folder_id: uuid.UUID | None = None
    definition: ReportDefinition
    copied_from: str | None = Field(default=None, max_length=80)


class ReportPatch(BaseModel):
    """The fields to change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    folder_id: uuid.UUID | None = None
    definition: ReportDefinition | None = None


class ReportFolderIn(BaseModel):
    """A shared folder's name."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)


# --- helpers --------------------------------------------------------------------------------------


def _reporting_db(request: Request) -> Database:
    database: Database | None = getattr(request.app.state, REPORTING_DB_STATE, None)
    if database is None:
        raise ServiceUnavailable(code="database_not_configured")
    return database


def _zone(request: Request) -> ZoneInfo:
    zone = request_zone(request)
    return zone if isinstance(zone, ZoneInfo) else ZoneInfo("UTC")


async def _source(
    request: Request,
    session: AsyncSession,
    context: TenantContext,
    subject: Subject,
    entity: str,
) -> ReportingSource:
    """The entity as the viewer sees it, after the permission and licence checks."""
    provider = resolve_provider(entity, subject)
    gate: EntitlementGate | None = getattr(request.app.state, ENTITLEMENT_GATE_STATE, None)
    if gate is not None:
        await gate.check_request(context, feature=provider.feature, write=False, session=session)
    return await provider.source(session, subject)


def _validator(
    request: Request, session: AsyncSession, context: TenantContext, subject: Subject
) -> library.Validator:
    async def validate(definition: ReportDefinition) -> None:
        source = await _source(request, session, context, subject, definition.entity)
        zone = _zone(request)
        compile_report(definition, source, now=datetime.now(zone), zone=zone.key)

    return validate


def _field_type(value: Any) -> str:  # noqa: ANN401 - FieldType
    return str(getattr(value, "value", value))


# --- run ------------------------------------------------------------------------------------------


@router.post(
    "/run",
    summary="Run a report definition",
    responses={
        422: {"model": ProblemDetail, "description": "invalid_report or report_timeout."},
        429: {"model": ProblemDetail, "description": "report_queue_full: try again shortly."},
    },
)
@read_only_exempt
async def run(
    body: ReportRunIn,
    session: TenantSession,
    subject: View,
    context: Tenant,
    request: Request,
) -> ReportResultOut:
    """Run a definition over the records you may see, in your time zone (`X-Time-Zone`)."""
    limits = limits_of(await tenant_settings(session), request.app.state.settings)
    slots: TenantSlots = getattr(request.app.state, SLOTS_STATE)
    source = await _source(request, session, context, subject, body.definition.entity)
    result = await run_report(
        session,
        _reporting_db(request),
        context,
        subject,
        body.definition,
        source=source,
        zone=_zone(request),
        timeout_seconds=limits.interactive_timeout_seconds,
        week_start=limits.week_start,
        slots=slots,
    )
    return ReportResultOut.of(result)


@router.get("/entities/{entity}", summary="What a report on an entity can use")
async def entity_fields(
    entity: str, session: TenantSession, subject: View, context: Tenant, request: Request
) -> ReportEntityOut:
    """Fields (filter and grouping) and measures of an entity, as you may use them."""
    source = await _source(request, session, context, subject, entity)
    fields = []
    for name, spec in source.fields.fields.items():
        if not spec.filterable:
            continue
        dimension = source.dimensions.get(name)
        fields.append(
            ReportFieldOut(
                name=name,
                type=_field_type(spec.type),
                values=sorted(spec.values),
                multiple=spec.array,
                dimension=ReportGroupOut(
                    field=name,
                    kind=dimension.kind.value,
                    label_prefix=dimension.label_prefix,
                    reference=dimension.reference,
                    bucket=None,
                )
                if dimension is not None
                else None,
            )
        )
    measures = [
        ReportMeasureOut(code=m.code, unit=m.unit, better=m.better)
        for m in available_measures(source).values()
    ]
    return ReportEntityOut(
        entity=entity, list_path=source.list_path, fields=fields, measures=measures
    )


# --- library --------------------------------------------------------------------------------------


@router.get("/library", summary="The reports home")
async def get_library(
    session: TenantSession, subject: View, context: Tenant, request: Request
) -> ReportLibraryOut:
    """Built-in reports you can run now, shared folders, your and shared reports, your stars."""
    sources: dict[str, ReportingSource | None] = {}
    for entity in registered_entities():
        try:
            sources[entity] = await _source(request, session, context, subject, entity)
        except AppError:  # an entity the viewer may not use or is not licensed: not listed
            sources[entity] = None
    zone = _zone(request)
    now = datetime.now(zone)
    builtin: list[BuiltinReportOut] = []
    for report in BUILTIN_REPORTS:
        source = sources.get(report.definition.entity)
        if source is None:
            continue
        try:
            compile_report(report.definition, source, now=now, zone=zone.key)
        except ValidationFailed:
            continue  # its data arrives with a later work package
        builtin.append(
            BuiltinReportOut(code=report.code, folder=report.folder, definition=report.definition)
        )
    return ReportLibraryOut(
        builtin=builtin,
        folders=[
            ReportFolderOut(id=f.id, name=f.name, version=f.version)
            for f in await library.list_folders(session)
        ],
        reports=[SavedReportOut.of(r) for r in await library.list_reports(session, subject)],
        favourites=await library.favourites(session, subject),
    )


@router.put(
    "/favourites/{report_ref}",
    summary="Star a report",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def star(report_ref: str, session: TenantSession, subject: View) -> None:
    """`builtin:<code>` or a saved report id."""
    await library.set_favourite(session, subject, report_ref, starred=True)


@router.delete(
    "/favourites/{report_ref}",
    summary="Unstar a report",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unstar(report_ref: str, session: TenantSession, subject: View) -> None:
    """Remove a star (no error when there was none)."""
    await library.set_favourite(session, subject, report_ref, starred=False)


# --- exports --------------------------------------------------------------------------------------


class ReportExportIn(BaseModel):
    """What to export: the definition on screen, the file format and what it holds."""

    model_config = ConfigDict(extra="forbid")

    definition: ReportDefinition
    format: Literal["csv", "xlsx", "pdf"]
    content: Literal["summary", "records"] = "summary"
    title: str = Field(min_length=1, max_length=200)
    language: Literal["en", "ar", "ur"] = "en"


class ReportExportOut(BaseModel):
    """An export and where it stands; `problem` says why a failed one failed."""

    id: uuid.UUID
    title: str
    format: str
    content: str
    status: Literal["running", "ready", "failed", "expired"]
    problem: str | None
    row_count: int | None
    size_bytes: int | None
    created_at: datetime
    expires_at: datetime | None

    @classmethod
    def of(cls, row: ReportExport) -> "ReportExportOut":
        """From the row."""
        return cls(
            id=row.id,
            title=row.title,
            format=row.format,
            content=row.content,
            status=row.status,  # type: ignore[arg-type]  # CHECK constraint keeps it to these
            problem=row.problem,
            row_count=row.row_count,
            size_bytes=row.size_bytes,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )


STORAGE_STATE = "report_storage"


def _storage(request: Request) -> ObjectStorage | None:
    # app.state.report_storage replaces the configured store (tests); normally unset.
    injected: ObjectStorage | None = getattr(request.app.state, STORAGE_STATE, None)
    return injected or storage_or_none(request.app.state.settings)


@router.post(
    "/exports",
    summary="Export a report to a file",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReportExportOut,
    responses={503: {"model": ProblemDetail, "description": "storage_not_configured"}},
)
@read_only_exempt
async def request_export(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: ReportExportIn,
    session: TenantSession,
    subject: View,
    context: Tenant,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Needs `reports.export`. Built in the background; you are told live when it is ready."""

    async def go() -> Created:
        row = await exports.request_export(
            session,
            subject,
            exports.ExportRequest(
                definition=body.definition,
                format=body.format,
                content=body.content,
                title=body.title,
                language=body.language,
                time_zone=_zone(request).key,
            ),
            validate=_validator(request, session, context, subject),
            storage_ready=_storage(request) is not None,
        )
        return Created(body=ReportExportOut.of(row))

    return await idempotency.run(body, go, status_code=status.HTTP_202_ACCEPTED)


@router.get("/exports", summary="Your recent exports")
async def my_exports(session: TenantSession, subject: View) -> list[ReportExportOut]:
    """Newest first; files can be downloaded until they expire."""
    return [ReportExportOut.of(r) for r in await exports.list_exports(session, subject)]


@router.get(
    "/exports/{export_id}/file",
    summary="Download an export",
    response_class=StreamingResponse,
    responses={409: {"model": ProblemDetail, "description": "report_export_not_ready"}},
    dependencies=[audited("report.export_downloaded", object_param="export_id")],
)
async def download_export(
    export_id: uuid.UUID, session: TenantSession, subject: View, request: Request
) -> StreamingResponse:
    """Only for the person who asked, signed in, before the file expires."""
    row = await exports.download(session, subject, export_id)
    storage = _storage(request)
    if storage is None or row.object_key is None or row.size_bytes is None:
        raise ServiceUnavailable(code="storage_not_configured")
    name = f"{row.title}.{row.format}"
    ascii_name = name.encode("ascii", "replace").decode().replace('"', "")
    return StreamingResponse(
        storage.read_range(row.object_key, 0, max(row.size_bytes - 1, 0)),
        media_type=exports.CONTENT_TYPES[row.format],
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
            ),
            "Content-Length": str(row.size_bytes),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- schedules ------------------------------------------------------------------------------------


class ReportScheduleIn(BaseModel):
    """A scheduled report: what, when, to whom, in which file type."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    report_ref: str = Field(
        min_length=1, max_length=100, description="builtin:<code> or a saved report id"
    )
    frequency: Literal["daily", "weekly", "monthly"]
    at_time: time_type = Field(description="Wall-clock time in `time_zone`, e.g. 07:00")
    time_zone: str = Field(min_length=1, max_length=64)
    start_date: date
    end_date: date | None = None
    weekdays: list[int] = Field(default_factory=list, max_length=7, description="0 = Monday")
    day_of_month: int | None = Field(default=None, ge=1, le=28)
    recipient_users: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    recipient_groups: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    format: Literal["csv", "xlsx", "pdf"] = "xlsx"
    content: Literal["summary", "records"] = "summary"
    message: str | None = Field(default=None, max_length=2000)

    def values(self) -> schedules.ScheduleInput:
        """For the service."""
        return schedules.ScheduleInput(
            title=self.title,
            report_ref=self.report_ref,
            frequency=Frequency(self.frequency),
            at_time=self.at_time.replace(second=0, microsecond=0),
            time_zone=self.time_zone,
            start_date=self.start_date,
            end_date=self.end_date,
            weekdays=tuple(self.weekdays),
            day_of_month=self.day_of_month,
            recipient_users=tuple(self.recipient_users),
            recipient_groups=tuple(self.recipient_groups),
            format=self.format,
            content=self.content,
            message=self.message,
        )


class ReportScheduleOut(BaseModel):
    """A schedule with its next run and the result of its last one (REQ-RPT-052 AC2)."""

    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    report_ref: str
    frequency: Literal["daily", "weekly", "monthly"]
    at_time: time_type
    time_zone: str
    start_date: date
    end_date: date | None
    weekdays: list[int]
    day_of_month: int | None
    recipient_users: list[uuid.UUID]
    recipient_groups: list[uuid.UUID]
    format: Literal["csv", "xlsx", "pdf"]
    content: Literal["summary", "records"]
    message: str | None
    status: Literal["active", "paused", "finished"]
    paused_reason: str | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_result: str | None
    last_sent: int | None
    last_failed: int | None
    version: int

    @classmethod
    def of(cls, row: ReportSchedule) -> "ReportScheduleOut":
        """From the row."""
        return cls.model_validate(
            {
                **{name: getattr(row, name) for name in cls.model_fields},
                "weekdays": list(row.weekdays or ()),
            }
        )


class ReportSchedulesOut(BaseModel):
    """Your schedules, and whether e-mail can be sent at all (REQ-RPT-055)."""

    mail_configured: bool
    items: list[ReportScheduleOut]


@router.get("/schedules", summary="Scheduled reports")
async def list_schedules(
    session: TenantSession, subject: View, request: Request
) -> ReportSchedulesOut:
    """Yours (administrators: every one), next run first."""
    rows = await schedules.list_schedules(session, subject)
    return ReportSchedulesOut(
        mail_configured=mail_configured(request.app.state.settings),
        items=[ReportScheduleOut.of(r) for r in rows],
    )


@router.post(
    "/schedules",
    summary="Schedule a report",
    status_code=status.HTTP_201_CREATED,
    response_model=ReportScheduleOut,
    responses={409: {"model": ProblemDetail, "description": "mail_not_configured"}},
)
async def create_schedule(
    body: ReportScheduleIn,
    session: TenantSession,
    subject: View,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Needs `reports.schedule` and outgoing mail."""

    async def go() -> Created:
        row = await schedules.create_schedule(
            session,
            subject,
            body.values(),
            settings=request.app.state.settings,
            source=source_of(request),
        )
        return Created(body=ReportScheduleOut.of(row), headers={"ETag": f'"{row.version}"'})

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)


@router.put("/schedules/{schedule_id}", summary="Change a scheduled report", responses=CONFLICT)
async def update_schedule(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    schedule_id: uuid.UUID,
    body: ReportScheduleIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: View,
    response: Response,
    request: Request,
) -> ReportScheduleOut:
    """Replace its settings (If-Match)."""
    row = await schedules.update_schedule(
        session,
        subject,
        schedule_id,
        body.values(),
        expected_version=version,
        settings=request.app.state.settings,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return ReportScheduleOut.of(row)


@router.post(
    "/schedules/{schedule_id}/{action}",
    summary="Pause or resume a scheduled report",
    responses=CONFLICT,
)
async def pause_or_resume(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    schedule_id: uuid.UUID,
    action: Literal["pause", "resume"],
    version: ExpectedVersion,
    session: TenantSession,
    subject: View,
    response: Response,
    request: Request,
) -> ReportScheduleOut:
    """Resuming clears the failure count and plans the next run."""
    row = await schedules.set_paused(
        session,
        subject,
        schedule_id,
        paused=action == "pause",
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return ReportScheduleOut.of(row)


@router.delete(
    "/schedules/{schedule_id}",
    summary="Delete a scheduled report",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: View,
    request: Request,
) -> None:
    """Needs If-Match."""
    await schedules.delete_schedule(
        session, subject, schedule_id, expected_version=version, source=source_of(request)
    )


# --- settings -------------------------------------------------------------------------------------


class ReportSettingsOut(BaseModel):
    """The tenant's reporting defaults (D-041: editable by an admin)."""

    week_start: Literal["monday", "sunday"]
    interactive_timeout_seconds: int
    export_link_days: int
    max_export_rows: int
    version: int


class ReportSettingsPatch(BaseModel):
    """The settings to change."""

    model_config = ConfigDict(extra="forbid")

    week_start: Literal["monday", "sunday"] | None = None
    interactive_timeout_seconds: int | None = Field(default=None, ge=5, le=60)
    export_link_days: int | None = Field(default=None, ge=1, le=30)
    max_export_rows: int | None = Field(default=None, ge=1000, le=1_000_000)


def _settings_out(row: ReportSettings) -> ReportSettingsOut:
    return ReportSettingsOut(
        week_start="sunday" if row.week_start == "sunday" else "monday",
        interactive_timeout_seconds=row.interactive_timeout_seconds,
        export_link_days=row.export_link_days,
        max_export_rows=row.max_export_rows,
        version=row.version,
    )


@router.get("/settings", summary="Report settings of your organisation")
async def get_settings(
    session: TenantSession, subject: View, response: Response
) -> ReportSettingsOut:
    """Week start, query time limit, export link lifetime and row cap."""
    del subject
    row = await tenant_settings(session)
    set_etag(response, row.version)
    return _settings_out(row)


@router.patch(
    "/settings",
    summary="Change report settings",
    responses=CONFLICT,
    dependencies=[audited("report.settings_changed", object_type="report_settings")],
)
async def patch_settings(
    body: ReportSettingsPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: View,
    response: Response,
) -> ReportSettingsOut:
    """Needs `settings.manage` and If-Match."""
    row = await update_settings(
        session,
        subject,
        {name: getattr(body, name) for name in body.model_fields_set},
        expected_version=version,
    )
    set_etag(response, row.version)
    return _settings_out(row)


# --- folders --------------------------------------------------------------------------------------


@router.post(
    "/folders",
    summary="Create a shared folder",
    status_code=status.HTTP_201_CREATED,
    response_model=ReportFolderOut,
)
async def create_folder(
    body: ReportFolderIn,
    session: TenantSession,
    subject: View,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Needs `reports.manage_folders`."""

    async def go() -> Created:
        folder = await library.create_folder(
            session, subject, name=body.name, source=source_of(request)
        )
        return Created(
            body=ReportFolderOut(id=folder.id, name=folder.name, version=folder.version),
            headers={"ETag": f'"{folder.version}"'},
        )

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)


@router.patch("/folders/{folder_id}", summary="Rename a shared folder", responses=CONFLICT)
async def rename_folder(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    folder_id: uuid.UUID,
    body: ReportFolderIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: View,
    response: Response,
    request: Request,
) -> ReportFolderOut:
    """Needs `reports.manage_folders` and If-Match."""
    folder = await library.rename_folder(
        session,
        subject,
        folder_id,
        name=body.name,
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, folder.version)
    return ReportFolderOut(id=folder.id, name=folder.name, version=folder.version)


@router.delete(
    "/folders/{folder_id}",
    summary="Delete a shared folder",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_folder(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    folder_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: View,
    request: Request,
    move_to: Annotated[
        str,
        Query(
            description="Where its reports go: a folder id, or `owners` (each owner's own).",
            max_length=40,
        ),
    ],
) -> None:
    """Needs `reports.manage_folders`; you must say where its reports go (REQ-RPT-045 AC3)."""
    target: uuid.UUID | None = None
    if move_to != "owners":
        try:
            target = uuid.UUID(move_to)
        except ValueError:
            raise ValidationFailed(
                errors=[
                    FieldError(
                        field="query.move_to",
                        code="invalid_value",
                        message_key="errors.field.invalid_value",
                    )
                ]
            ) from None
    await library.delete_folder(
        session,
        subject,
        folder_id,
        move_to=target,
        expected_version=version,
        source=source_of(request),
    )


# --- saved reports --------------------------------------------------------------------------------


@router.post(
    "",
    summary="Save a report",
    status_code=status.HTTP_201_CREATED,
    response_model=SavedReportOut,
)
async def create_report(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: ReportIn,
    session: TenantSession,
    subject: View,
    context: Tenant,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Needs `reports.create`. A copy of a built-in report names it in `copied_from`."""

    async def go() -> Created:
        saved = await library.create_report(
            session,
            subject,
            name=body.name,
            description=body.description,
            folder_id=body.folder_id,
            definition=body.definition,
            copied_from=body.copied_from,
            validate=_validator(request, session, context, subject),
            source=source_of(request),
        )
        out = SavedReportOut.of(saved)
        return Created(
            body=out,
            headers={"Location": f"/api/v1/reports/{out.id}", "ETag": f'"{out.version}"'},
        )

    return await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)


@router.get("/{report_id}", summary="Get a saved report")
async def get_report(
    report_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> SavedReportOut:
    """Yours, or one in a shared folder; 404 otherwise."""
    found = await library.get_report(session, subject, report_id)
    set_etag(response, found.record.version)
    return SavedReportOut.of(found)


@router.patch("/{report_id}", summary="Change a saved report", responses=CONFLICT)
async def update_report(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    report_id: uuid.UUID,
    body: ReportPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: View,
    context: Tenant,
    response: Response,
    request: Request,
) -> SavedReportOut:
    """The fields you send. Needs If-Match; built-in reports are never changed (copy them)."""
    values = {name: getattr(body, name) for name in body.model_fields_set}
    saved = await library.update_report(
        session,
        subject,
        report_id,
        expected_version=version,
        values=values,
        validate=_validator(request, session, context, subject),
        source=source_of(request),
    )
    set_etag(response, saved.record.version)
    return SavedReportOut.of(saved)


@router.delete(
    "/{report_id}",
    summary="Delete a saved report",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
)
async def delete_report(
    report_id: uuid.UUID,
    version: ExpectedVersion,
    session: TenantSession,
    subject: View,
    request: Request,
) -> None:
    """Needs If-Match."""
    await library.delete_report(
        session, subject, report_id, expected_version=version, source=source_of(request)
    )
