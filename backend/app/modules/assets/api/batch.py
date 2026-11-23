"""Asset bulk jobs, merges and imports over HTTP (WP-049b S4b; REQ-AST-051, 052, 053). No logic.

- `/assets/bulk-jobs`: queue a bulk edit, move, assign or delete of up to 1,000 assets
  (assets.manage; each asset checked again as it runs), your jobs and their per-asset results.
- `/assets/merge-preview` and `/assets/merges`: what a merge would keep, and the merge itself
  (assets.manage on both assets; one `asset.merged` audit entry with the field mapping).
- `/assets/imports`: upload a CSV or Excel file of assets, consumables or vendors (a dry run
  first), your imports with their per-row problems, and running a checked dry run.

Registered before the record routes: none of these paths is an asset ID.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.body_limit import body_limit
from app.core.database import TenantSession
from app.core.errors import ProblemDetail, ValidationFailed
from app.modules.assets.api.records import AssetOut
from app.modules.assets.domain.batch import (
    IMPORT_LIMITS,
    MAX_BULK,
    AssetBulkAction,
    AssetBulkOutcome,
    AssetBulkStatus,
    AssetImportStatus,
    ImportKind,
    ImportMatch,
    ImportMode,
    MergeSide,
)
from app.modules.assets.infra.models import AssetBulkJob, AssetImport
from app.modules.assets.service import assets as asset_service
from app.modules.assets.service import bulk_jobs, imports, merge
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/assets",
    tags=["assets"],
    dependencies=[Depends(rate_limit("assets"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or feature."},
    },
)
View = Annotated[Subject, Depends(require_permission(asset_service.VIEW))]
Manage = Annotated[Subject, Depends(require_permission(asset_service.MANAGE))]
# A body larger than this is refused by validation; up to it, the service says how many (422
# asset_bulk_too_many with the cap of 1,000), so the screen can word it.
_BODY_IDS_MAX = 10 * MAX_BULK


# --- bulk jobs (REQ-AST-051) -------------------------------------------------------------------


class AssetBulkChanges(BaseModel):
    """What to do to each asset.

    Edit: only the fields to set. Move: the state (and reason). Assign: the holder (both null:
    back to no one). Delete: nothing.
    """

    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    location: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    cost_centre: str | None = Field(default=None, max_length=60)
    gl_code: str | None = Field(default=None, max_length=40)
    acquired_on: date | None = None
    warranty_expires_on: date | None = None
    expires_on: date | None = None
    to_state_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)
    holder_kind: Literal["user", "department"] | None = None
    holder_id: uuid.UUID | None = None


class AssetBulkIn(BaseModel):
    """A bulk action on the picked assets (at most 1,000)."""

    model_config = ConfigDict(extra="forbid")

    action: AssetBulkAction
    asset_ids: list[uuid.UUID] = Field(min_length=1, max_length=_BODY_IDS_MAX)
    changes: AssetBulkChanges = Field(default_factory=AssetBulkChanges)


class AssetBulkResultOut(BaseModel):
    """What happened to one asset; a skip carries the reason as a code (and field)."""

    id: uuid.UUID
    tag: str | None
    outcome: AssetBulkOutcome
    code: str | None = None
    field: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class AssetBulkJobOut(BaseModel):
    """A bulk job with its progress (and, for one job, its per-asset results)."""

    id: uuid.UUID
    action: AssetBulkAction
    status: AssetBulkStatus
    total: int
    processed: int
    done_count: int
    skipped_count: int
    results: list[AssetBulkResultOut]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def of(cls, row: AssetBulkJob, *, results: bool = True) -> "AssetBulkJobOut":
        """From a row (the results only when asked for: up to 1,000 entries)."""
        return cls(
            id=row.id,
            action=AssetBulkAction(row.action),
            status=AssetBulkStatus(row.status),
            total=row.total,
            processed=row.processed,
            done_count=row.done_count,
            skipped_count=row.skipped_count,
            results=[AssetBulkResultOut(**r) for r in row.results] if results else [],
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )


@router.post(
    "/bulk-jobs",
    summary="Act on many assets at once",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AssetBulkJobOut,
    responses={422: {"model": ProblemDetail, "description": "asset_bulk_too_many (max)"}},
    dependencies=[audited("asset.bulk_started", object_type="asset_bulk_job")],
)
async def start_bulk(
    body: AssetBulkIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Queue a background job (up to 1,000 assets); progress arrives on your channel.

    Each asset is changed as you, through the same rules as one change (scope, life cycle,
    disposed assets, licence slots); one that refuses is skipped with the reason. Delete moves
    to the trash. Send an Idempotency-Key.
    """

    async def run() -> Created:
        row = await bulk_jobs.start(
            session,
            subject,
            action=body.action,
            changes=body.changes.model_dump(mode="json", exclude_unset=True),
            asset_ids=body.asset_ids,
            source=source_of(request),
        )
        return Created(body=AssetBulkJobOut.of(row))

    return await idempotency.run(body, run, status_code=status.HTTP_202_ACCEPTED)


@router.get("/bulk-jobs", summary="Your latest asset bulk jobs")
async def list_bulk_jobs(session: TenantSession, subject: Manage) -> list[AssetBulkJobOut]:
    """Newest first, without their results."""
    rows = await bulk_jobs.jobs(session, subject)
    return [AssetBulkJobOut.of(r, results=False) for r in rows]


@router.get(
    "/bulk-jobs/{job_id}",
    summary="One of your asset bulk jobs",
    responses={404: {"model": ProblemDetail, "description": "asset_bulk_job_not_found"}},
)
async def get_bulk_job(
    job_id: uuid.UUID, session: TenantSession, subject: Manage
) -> AssetBulkJobOut:
    """Its progress and a result per finished asset."""
    return AssetBulkJobOut.of(await bulk_jobs.job(session, subject, job_id))


# --- merges (REQ-AST-052) ----------------------------------------------------------------------


class AssetMergeFieldOut(BaseModel):
    """One field: both values (as text or null) and the suggested side.

    Money is hidden (`hidden`, both values null) without assets.view_financials.
    """

    field: str
    survivor: Any = None
    merged: Any = None
    side: MergeSide
    hidden: bool = False


class AssetMergePreviewOut(BaseModel):
    """The two assets with the suggested survivor first, and the field-by-field choice."""

    survivor: AssetOut
    merged: AssetOut
    swapped: bool = Field(description="The suggestion (discovered, newest scan) swapped them.")
    fields: list[AssetMergeFieldOut]


@router.get(
    "/merge-preview",
    summary="What a merge of two assets would keep",
    responses={
        404: {"model": ProblemDetail, "description": "asset_not_found"},
        409: {"model": ProblemDetail, "description": "asset_merge_same"},
    },
)
async def merge_preview(
    first: Annotated[uuid.UUID, Query(description="One asset.")],
    second: Annotated[uuid.UUID, Query(description="The other.")],
    session: TenantSession,
    subject: Manage,
) -> AssetMergePreviewOut:
    """assets.manage on both (each within your scope); the suggested survivor comes first."""
    found = await merge.preview(session, subject, first, second)
    return AssetMergePreviewOut(
        survivor=AssetOut.of(found.survivor, subject),
        merged=AssetOut.of(found.merged, subject),
        swapped=found.swapped,
        fields=[
            AssetMergeFieldOut(
                field=f.field, survivor=f.survivor, merged=f.merged, side=f.side, hidden=f.hidden
            )
            for f in found.fields
        ],
    )


class AssetMergeIn(BaseModel):
    """Merge one asset into another, at the versions you saw, with your field choices."""

    model_config = ConfigDict(extra="forbid")

    survivor_id: uuid.UUID
    survivor_version: int
    merged_id: uuid.UUID
    merged_version: int
    choices: dict[str, MergeSide] = Field(
        default_factory=dict, description="Field -> side; a field left out keeps the suggestion."
    )


class AssetMergeMappingOut(BaseModel):
    """Whose value one field kept."""

    field: str
    side: MergeSide


class AssetMergeOut(BaseModel):
    """The survivor after the merge, the mapping and what moved to it (counts)."""

    merge_id: uuid.UUID
    survivor: AssetOut
    mapping: list[AssetMergeMappingOut]
    moved: dict[str, int]


@router.post(
    "/merges",
    summary="Merge a duplicate asset into another",
    status_code=status.HTTP_201_CREATED,
    response_model=AssetMergeOut,
    responses={
        404: {"model": ProblemDetail, "description": "asset_not_found"},
        409: {"model": ProblemDetail, "description": "version_conflict, asset_merge_on_loan"},
    },
)
async def merge_assets(  # noqa: PLR0913 - FastAPI dependencies
    *,
    body: AssetMergeIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
    note: Annotated[AuditNote, audited("asset.merged", object_type="asset")],
) -> Response:
    """assets.manage on both assets; the merged one goes to the trash.

    Its tag, serial and barcode then find the survivor. One audit entry holds the field
    mapping. Send an Idempotency-Key.
    """

    async def run() -> Created:
        done = await merge.merge(
            session,
            subject,
            body.survivor_id,
            body.merged_id,
            survivor_version=body.survivor_version,
            merged_version=body.merged_version,
            choices={k: v.value for k, v in body.choices.items()},
            source=source_of(request),
        )
        note.object_id = str(done.survivor.id)
        note.details = {
            "merged_asset_id": str(body.merged_id),
            "mapping": done.mapping,
            "moved": done.moved,
        }
        return Created(
            body=AssetMergeOut(
                merge_id=done.merge.id,
                survivor=AssetOut.of(done.survivor, subject),
                mapping=[
                    AssetMergeMappingOut(field=m["field"], side=MergeSide(m["side"]))
                    for m in done.mapping
                ],
                moved=done.moved,
            ),
            headers={"ETag": f'"{done.survivor.version}"'},
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


# --- imports (REQ-AST-053) ---------------------------------------------------------------------


class AssetImportProblemOut(BaseModel):
    """One refused row: its number in the file, the column and the reason code."""

    row: int | None
    field: str | None
    code: str


class AssetImportOut(BaseModel):
    """An import and how far it got. Updates live (`assets.import_progress`)."""

    id: uuid.UUID
    kind: ImportKind
    mode: ImportMode
    match_on: ImportMatch
    dry_run: bool
    file_name: str
    file_format: Literal["csv", "xlsx"]
    status: AssetImportStatus
    total: int
    processed: int
    created_count: int
    updated_count: int
    failed_count: int
    problems: list[AssetImportProblemOut]
    failure: str | None
    failure_detail: str | None
    created_at: datetime
    checked_at: datetime | None
    finished_at: datetime | None
    version: int

    @classmethod
    def of(cls, row: AssetImport) -> "AssetImportOut":
        """From the row (never the file)."""
        return cls.model_validate(row, from_attributes=True)


class AssetImportTarget(BaseModel):
    """The Idempotency-Key fingerprint of an upload."""

    name: str
    kind: str
    mode: str
    match_on: str
    dry_run: bool
    size: int


@router.post(
    "/imports",
    summary="Import assets, consumables or vendors from a CSV or Excel file",
    dependencies=[Depends(body_limit(IMPORT_LIMITS.max_file_bytes + 1))],  # it checks its own
    status_code=status.HTTP_201_CREATED,
    response_model=AssetImportOut,
    responses={422: {"model": ProblemDetail, "description": "asset_import_file_too_large"}},
)
async def start_import(  # noqa: PLR0913 - the upload's facts, explicit
    *,
    request: Request,
    session: TenantSession,
    subject: View,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("asset_import.started", object_type="asset_import")],
    name: Annotated[str, Query(min_length=1, max_length=255)],
    kind: Annotated[ImportKind, Query()],
    mode: Annotated[ImportMode, Query()] = ImportMode.ADD_UPDATE,
    match_on: Annotated[ImportMatch, Query()] = ImportMatch.TAG,
    dry_run: Annotated[bool, Query(description="Check every row and change nothing.")] = True,
) -> Response:
    """The raw file as the body (up to 25 MB, 20,000 rows); it is read in the background.

    Assets and consumables need assets.manage; vendors vendors.create (to add) and
    vendors.manage (to update). A dry run (the default) changes nothing.
    """
    content = bytearray()
    async for piece in request.stream():
        content += piece
        if len(content) > IMPORT_LIMITS.max_file_bytes:
            raise ValidationFailed(code="asset_import_file_too_large", params=imports.FORMAT_WORDS)
    note.skip = True
    target = AssetImportTarget(
        name=name, kind=kind, mode=mode, match_on=match_on, dry_run=dry_run, size=len(content)
    )

    async def operation() -> Created:
        job = await imports.start_import(
            session,
            subject,
            kind=kind,
            mode=mode,
            match_on=match_on,
            file_name=name,
            content=bytes(content),
            dry_run=dry_run,
        )
        note.skip = False
        note.object_id = str(job.id)
        note.details = {
            "kind": kind.value,
            "mode": mode.value,
            "dry_run": dry_run,
            "file_bytes": len(content),
        }
        return Created(AssetImportOut.of(job), headers={"ETag": f'"{job.version}"'})

    return await idempotency.run(target, operation)


@router.get("/imports", summary="Your latest imports")
async def list_imports(session: TenantSession, subject: View) -> list[AssetImportOut]:
    """The last 20, newest first."""
    return [AssetImportOut.of(job) for job in await imports.recent_imports(session, subject)]


@router.get(
    "/imports/{import_id}",
    summary="One of your imports",
    responses={404: {"model": ProblemDetail, "description": "asset_import_not_found"}},
)
async def get_import(
    import_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> AssetImportOut:
    """Its progress and refused rows."""
    job = await imports.own_import(session, subject, import_id)
    set_etag(response, job.version)
    return AssetImportOut.of(job)


@router.post(
    "/imports/{import_id}/run",
    summary="Run a checked dry run for real",
    responses={409: {"model": ProblemDetail, "description": "asset_import_not_checked"}},
    dependencies=[
        audited("asset_import.run", object_type="asset_import", object_param="import_id")
    ],
)
async def run_import(
    import_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    version: ExpectedVersion,
    response: Response,
) -> AssetImportOut:
    """The same file, mode and match, applied this time (If-Match)."""
    job = await imports.start_run(session, subject, import_id, expected_version=version)
    set_etag(response, job.version)
    return AssetImportOut.of(job)
