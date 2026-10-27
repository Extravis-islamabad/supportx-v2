"""Reports API (WP-035): run a definition, the library, saved reports, folders, favourites.

Every route needs `reports.view`; the entity's licence feature and list permission are checked
per run (REQ-RPT-048). Results carry codes and ids with the metadata the UI needs to label them
(rule d); the UI renders every value through the labels package.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response, status
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
from app.modules.analytics.service import library
from app.modules.analytics.service.compiler import available_measures, compile_report
from app.modules.analytics.service.runner import (
    ReportResult,
    TenantSlots,
    resolve_provider,
    run_report,
)
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import request_zone
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of
from app.shared.reporting import ReportingSource, registered_entities

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
    settings = request.app.state.settings
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
        timeout_seconds=settings.report_interactive_timeout_seconds,
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
