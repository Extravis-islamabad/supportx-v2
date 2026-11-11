"""Asset labels, scan history and the overdue-scan rule over HTTP (WP-049b s3). No logic.

- `/assets/labels`: ask for labels (assets.view on every asset printed; a job in the worker,
  202), your jobs, the file, the label history and reprints (REQ-AST-039).
- `/assets/{id}/scans`: an asset's scan history (REQ-AST-054).
- `/assets/overdue-rule`: the overdue-scan rule, its preview and its runs (config.assets,
  REQ-AST-056).

Registered before the record routes: `/assets/labels` and `/assets/overdue-rule` are no IDs.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail, ServiceUnavailable
from app.modules.assets.domain.labels import (
    CODE_MAX,
    LABELS_MAX,
    LabelJobStatus,
    LabelLayout,
    LabelTarget,
    Symbology,
)
from app.modules.assets.domain.scans import (
    DAYS_MAX,
    OverdueAction,
    ScanFailure,
    ScanResult,
    ScanSource,
    ScanType,
)
from app.modules.assets.infra.models import (
    AssetLabelJob,
    AssetOverdueRule,
    AssetOverdueRun,
    AssetScan,
)
from app.modules.assets.service import assets as asset_service
from app.modules.assets.service import labels as service
from app.modules.assets.service import scans
from app.modules.assets.service.catalogue import CONFIGURE_ANY
from app.modules.audit import audited
from app.modules.identity_access import Subject, user_names
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
Configure = Annotated[Subject, Depends(require_permission(*CONFIGURE_ANY))]


def _storage_ready(request: Request) -> bool:
    return service.label_storage(request.app.state.settings) is not None


# --- labels (REQ-AST-039) ---------------------------------------------------------------------


class LabelsIn(BaseModel):
    """What to print: assets (by ID) or vendor codes, and how."""

    model_config = ConfigDict(extra="forbid")

    target: LabelTarget = LabelTarget.ASSET
    layout: LabelLayout = LabelLayout.LAPTOP
    symbology: Symbology = Symbology.QR
    language: Literal["en", "ar", "ur"] = "en"
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=LABELS_MAX)
    codes: list[Annotated[str, Field(max_length=CODE_MAX)]] = Field(
        default_factory=list, max_length=LABELS_MAX
    )


class LabelJobOut(BaseModel):
    """A label job and where it stands; `problem` says why a failed one failed."""

    id: uuid.UUID
    target: LabelTarget
    layout: LabelLayout
    symbology: Symbology
    item_count: int
    done: int
    status: LabelJobStatus
    problem: str | None
    pages: int | None
    size_bytes: int | None
    reprint_of: uuid.UUID | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None

    @classmethod
    def of(cls, row: AssetLabelJob) -> "LabelJobOut":
        """From the row."""
        return cls(
            id=row.id,
            target=LabelTarget(row.target),
            layout=LabelLayout(row.layout),
            symbology=Symbology(row.symbology),
            item_count=row.item_count,
            done=row.done,
            status=LabelJobStatus(row.status),
            problem=row.problem,
            pages=row.pages,
            size_bytes=row.size_bytes,
            reprint_of=row.reprint_of,
            created_at=row.created_at,
            finished_at=row.finished_at,
            expires_at=row.expires_at,
        )


STORAGE: dict[int | str, dict[str, object]] = {
    404: {"model": ProblemDetail, "description": "asset_not_found"},
    503: {"model": ProblemDetail, "description": "storage_not_configured"},
}


@router.post(
    "/labels",
    summary="Print labels",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LabelJobOut,
    responses=STORAGE,
    dependencies=[audited("asset_label.requested", object_type="asset_label_job")],
)
async def request_labels(
    body: LabelsIn,
    session: TenantSession,
    subject: View,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Up to 500 labels in one PDF, built in the background; you are told live when it is ready.

    Every asset must be one you may see (404 otherwise, naming none). Idempotency-Key.
    """

    async def run() -> Created:
        job = await service.request_labels(
            session,
            subject,
            service.LabelRequest(
                target=body.target,
                layout=body.layout,
                symbology=body.symbology,
                language=body.language,
                asset_ids=body.asset_ids,
                codes=body.codes,
            ),
            storage_ready=_storage_ready(request),
        )
        return Created(body=LabelJobOut.of(job))

    return await idempotency.run(body, run, status_code=status.HTTP_202_ACCEPTED)


@router.get("/labels/jobs", summary="Your label jobs")
async def my_label_jobs(session: TenantSession, subject: View) -> list[LabelJobOut]:
    """Newest first; files can be downloaded for a week."""
    return [LabelJobOut.of(j) for j in await service.my_jobs(session, subject)]


@router.get(
    "/labels/jobs/{job_id}/file",
    summary="Download a label PDF",
    response_class=StreamingResponse,
    responses={
        404: {"model": ProblemDetail, "description": "asset_label_job_not_found"},
        409: {"model": ProblemDetail, "description": "asset_label_job_not_ready"},
    },
    dependencies=[
        audited("asset_label.downloaded", object_type="asset_label_job", object_param="job_id")
    ],
)
async def download_labels(
    job_id: uuid.UUID, session: TenantSession, subject: View, request: Request
) -> StreamingResponse:
    """Only for the person who asked, signed in, before the file expires."""
    job = await service.download(session, subject, job_id)
    storage = service.label_storage(request.app.state.settings)
    if storage is None or job.object_key is None or job.size_bytes is None:
        raise ServiceUnavailable(code="storage_not_configured")
    name = f"labels-{job.created_at:%Y%m%d-%H%M}.pdf"
    return StreamingResponse(
        storage.read_range(job.object_key, 0, max(job.size_bytes - 1, 0)),
        media_type=service.CONTENT_TYPE,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"
            ),
            "Content-Length": str(job.size_bytes),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


class LabelPrintOut(BaseModel):
    """One print or reprint (REQ-AST-039 AC3): who, when, what, how."""

    id: uuid.UUID
    job_id: uuid.UUID
    target: LabelTarget
    layout: LabelLayout
    symbology: Symbology
    item_count: int
    asset_ids: list[uuid.UUID] = Field(description="The printed assets you may see.")
    codes: list[str]
    reprint: bool
    printed_by: uuid.UUID | None
    printed_by_name: str | None
    printed_at: datetime


@router.get("/labels/prints", summary="Label history")
async def label_prints(
    session: TenantSession,
    subject: View,
    asset_id: Annotated[uuid.UUID | None, Query(description="Only this asset's labels.")] = None,
) -> list[LabelPrintOut]:
    """Every print and reprint, newest first (the latest 100)."""
    views = await service.prints(session, subject, asset_id=asset_id)
    names = await user_names(session, [str(v.row.created_by) for v in views if v.row.created_by])
    return [
        LabelPrintOut(
            id=v.row.id,
            job_id=v.row.job_id,
            target=LabelTarget(v.row.target),
            layout=LabelLayout(v.row.layout),
            symbology=Symbology(v.row.symbology),
            item_count=v.row.item_count,
            asset_ids=v.asset_ids,
            codes=list(v.row.codes),
            reprint=v.row.reprint,
            printed_by=v.row.created_by,
            printed_by_name=names.get(str(v.row.created_by)) if v.row.created_by else None,
            printed_at=v.row.created_at,
        )
        for v in views
    ]


@router.post(
    "/labels/prints/{print_id}/reprint",
    summary="Reprint labels",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LabelJobOut,
    responses={
        404: {"model": ProblemDetail, "description": "asset_label_print_not_found"},
        503: {"model": ProblemDetail, "description": "storage_not_configured"},
    },
    dependencies=[
        audited("asset_label.reprinted", object_type="asset_label_print", object_param="print_id")
    ],
)
async def reprint_labels(
    print_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """The same labels again: a new job and a new history row. Idempotency-Key."""

    async def run() -> Created:
        job = await service.reprint(
            session, subject, print_id, storage_ready=_storage_ready(request)
        )
        return Created(body=LabelJobOut.of(job))

    return await idempotency.run(None, run, status_code=status.HTTP_202_ACCEPTED)


# --- the overdue-scan rule (REQ-AST-056) ------------------------------------------------------


class OverdueRuleOut(BaseModel):
    """The tenant's overdue-scan rule."""

    enabled: bool
    days: int
    product_type_ids: list[uuid.UUID]
    action: OverdueAction
    state_id: uuid.UUID | None
    version: int

    @classmethod
    def of(cls, row: AssetOverdueRule) -> "OverdueRuleOut":
        """From the row."""
        return cls(
            enabled=row.enabled,
            days=row.days,
            product_type_ids=list(row.product_type_ids),
            action=OverdueAction(row.action),
            state_id=row.state_id,
            version=row.version,
        )


class OverdueRuleIn(BaseModel):
    """Rule fields to change (only those sent)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    days: int | None = Field(default=None, ge=1, le=DAYS_MAX)
    product_type_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    action: OverdueAction | None = None
    state_id: uuid.UUID | None = None


def _sent(body: OverdueRuleIn) -> dict[str, Any]:
    return {
        k: v
        for k, v in body.model_dump(include=body.model_fields_set).items()
        if v is not None or k == "state_id"
    }


@router.get("/overdue-rule", summary="The overdue-scan rule")
async def get_overdue_rule(
    session: TenantSession, subject: Configure, response: Response
) -> OverdueRuleOut:
    """Off by default (Appendix A: 60 days, move to a state)."""
    del subject
    row = await scans.get_rule(session)
    set_etag(response, row.version)
    return OverdueRuleOut.of(row)


@router.patch(
    "/overdue-rule",
    summary="Change the overdue-scan rule",
    responses={409: {"model": ProblemDetail, "description": "version_conflict"}},
    dependencies=[audited("asset_overdue_rule.changed", object_type="asset_overdue_rule")],
)
async def patch_overdue_rule(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: OverdueRuleIn,
    session: TenantSession,
    subject: Configure,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> OverdueRuleOut:
    """The fields sent (If-Match). The strongest action is the trash: never a delete."""
    row = await scans.save_rule(
        session, subject, _sent(body), expected_version=version, source=source_of(request)
    )
    set_etag(response, row.version)
    return OverdueRuleOut.of(row)


class OverduePreviewOut(BaseModel):
    """How many assets the rule, as sent, would act on now (REQ-AST-056 AC2)."""

    count: int


@router.post("/overdue-rule/preview", summary="Preview the overdue-scan rule")
async def preview_overdue_rule(
    body: OverdueRuleIn, session: TenantSession, subject: Configure
) -> OverduePreviewOut:
    """Nothing is changed: the count of the tenant's assets it would move now."""
    return OverduePreviewOut(count=await scans.preview(session, subject, _sent(body)))


class OverdueRunOut(BaseModel):
    """One run and what it changed (REQ-AST-056 AC1): asset IDs and states, nothing else."""

    id: uuid.UUID
    ran_at: datetime
    days: int
    action: OverdueAction
    state_id: uuid.UUID | None
    changed_count: int
    changed: list[dict[str, str | None]]

    @classmethod
    def of(cls, row: AssetOverdueRun) -> "OverdueRunOut":
        """From the row."""
        return cls(
            id=row.id,
            ran_at=row.ran_at,
            days=row.days,
            action=OverdueAction(row.action),
            state_id=row.state_id,
            changed_count=row.changed_count,
            changed=[
                {k: (None if v is None else str(v)) for k, v in c.items()} for c in row.changed
            ],
        )


@router.get("/overdue-rule/runs", summary="The overdue-scan rule's runs")
async def overdue_runs(session: TenantSession, subject: Configure) -> list[OverdueRunOut]:
    """The latest 20, newest first."""
    return [OverdueRunOut.of(r) for r in await scans.list_runs(session, subject)]


# --- scan history (REQ-AST-054) ---------------------------------------------------------------


class ScanChangeOut(BaseModel):
    """One change a scan found (labelled kinds; short texts from the scan)."""

    kind: str = Field(description="hardware_added, hardware_removed, software_installed ...")
    category: str | None = Field(default=None, description="Hardware: disk, memory ...")
    name: str
    model: str | None = None
    capacity: str | None = None
    serial: str | None = None
    version: str | None = None
    publisher: str | None = None


class AssetScanOut(BaseModel):
    """One scan of an asset."""

    id: uuid.UUID
    scanned_at: datetime
    source: ScanSource
    scan_type: ScanType | None
    result: ScanResult
    failure_reason: ScanFailure | None
    changes: list[ScanChangeOut]

    @classmethod
    def of(cls, row: AssetScan) -> "AssetScanOut":
        """From the row."""
        return cls(
            id=row.id,
            scanned_at=row.scanned_at,
            source=ScanSource(row.source),
            scan_type=None if row.scan_type is None else ScanType(row.scan_type),
            result=ScanResult(row.result),
            failure_reason=None if row.failure_reason is None else ScanFailure(row.failure_reason),
            changes=[ScanChangeOut.model_validate(c) for c in row.changes],
        )


class AssetScansOut(BaseModel):
    """A page of scans, newest first."""

    items: list[AssetScanOut]
    next_cursor: datetime | None


@router.get(
    "/{asset_id}/scans",
    summary="An asset's scan history",
    responses={404: {"model": ProblemDetail, "description": "asset_not_found"}},
)
async def asset_scans(
    asset_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    cursor: Annotated[datetime | None, Query(description="next_cursor of the last page")] = None,
    limit: Annotated[int, Query(ge=1, le=scans.SCANS_PAGE_MAX)] = 25,
) -> AssetScansOut:
    """Each scan with its source, result (and reason) and what changed; kept per settings."""
    rows, next_cursor = await scans.list_scans(
        session, subject, asset_id, before=cursor, limit=limit
    )
    return AssetScansOut(items=[AssetScanOut.of(r) for r in rows], next_cursor=next_cursor)
