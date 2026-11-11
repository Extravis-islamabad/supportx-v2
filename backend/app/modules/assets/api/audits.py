"""Asset audits over HTTP (WP-049b s3; REQ-AST-042, 043). No business logic.

- `/assets/audits`: plan (assets.manage), list and open (managers, and named auditors with
  assets.view). Creates take an Idempotency-Key, changes If-Match.
- `/assets/audits/{id}/start`, `/close`: the state moves (If-Match).
- `/assets/audits/{id}/items`: the items; PATCH marks one by hand (named auditors, If-Match),
  `/scans` marks by a scanned code, `/fixes` settles discrepancies in bulk (assets.manage).

Registered before the record routes: `/assets/audits` is not an asset ID.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.assets.domain.audits import (
    FIX_MAX,
    NAME_MAX,
    NOTE_MAX,
    AuditFix,
    AuditItemKind,
    AuditItemResult,
    AuditKind,
    AuditMarkMethod,
    AuditState,
)
from app.modules.assets.service import assets as asset_service
from app.modules.assets.service import audits as service
from app.modules.assets.service.moves import REASON_MAX
from app.modules.assets.service.ownership import Holder
from app.modules.audit import audited
from app.modules.identity_access import Subject, user_names
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/assets/audits",
    tags=["assets"],
    dependencies=[Depends(rate_limit("assets"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or feature."},
    },
)
View = Annotated[Subject, Depends(require_permission(asset_service.VIEW))]
Manage = Annotated[Subject, Depends(require_permission(asset_service.MANAGE))]
NOT_FOUND: dict[int | str, dict[str, object]] = {
    404: {"model": ProblemDetail, "description": "asset_audit_not_found"},
}
WRITE: dict[int | str, dict[str, object]] = {
    404: {"model": ProblemDetail, "description": "asset_audit_not_found"},
    409: {
        "model": ProblemDetail,
        "description": "version_conflict, asset_audit_closed, asset_audit_not_running, "
        "asset_audit_not_draft, asset_audit_scope_frozen",
    },
}
MARK: dict[int | str, dict[str, object]] = {
    403: {"model": ProblemDetail, "description": "asset_audit_not_auditor"},
    404: {
        "model": ProblemDetail,
        "description": "asset_audit_not_found, asset_audit_item_not_found, asset_not_found",
    },
    409: {
        "model": ProblemDetail,
        "description": "version_conflict, asset_audit_closed, asset_audit_not_running",
    },
}


class AuditPersonOut(BaseModel):
    """A named person."""

    id: uuid.UUID
    name: str | None


class AuditProgressOut(BaseModel):
    """Found and marked out of expected (REQ-AST-043 AC3)."""

    expected: int
    marked: int
    found: int
    unexpected: int
    discrepancies: int


class AuditOut(BaseModel):
    """An asset audit, its auditors and its progress."""

    id: uuid.UUID
    display_id: str
    name: str
    kind: AuditKind
    description: str | None
    site_ids: list[uuid.UUID]
    product_type_ids: list[uuid.UUID]
    group_ids: list[uuid.UUID]
    planned_start: date | None
    planned_end: date | None
    state: AuditState
    started_at: datetime | None
    closed_at: datetime | None
    auditors: list[AuditPersonOut]
    progress: AuditProgressOut
    may_manage: bool = Field(description="You may change, start, close and fix.")
    may_mark: bool = Field(description="You are a named auditor and it is running.")
    created_at: datetime
    updated_at: datetime
    version: int


async def _out(session: TenantSession, view: service.AuditView) -> AuditOut:
    audit, progress = view.audit, view.progress
    names = await user_names(session, [str(p) for p in view.auditors])
    return AuditOut(
        id=audit.id,
        display_id=audit.display_id,
        name=audit.name,
        kind=AuditKind(audit.kind),
        description=audit.description,
        site_ids=list(audit.site_ids),
        product_type_ids=list(audit.product_type_ids),
        group_ids=list(audit.group_ids),
        planned_start=audit.planned_start,
        planned_end=audit.planned_end,
        state=AuditState(audit.state),
        started_at=audit.started_at,
        closed_at=audit.closed_at,
        auditors=[AuditPersonOut(id=p, name=names.get(str(p))) for p in view.auditors],
        progress=AuditProgressOut(
            expected=progress.expected,
            marked=progress.marked,
            found=progress.found,
            unexpected=progress.unexpected,
            discrepancies=progress.discrepancies,
        ),
        may_manage=view.may_manage,
        may_mark=view.may_mark,
        created_at=audit.created_at,
        updated_at=audit.updated_at,
        version=audit.version,
    )


@router.get("", summary="Asset audits")
async def list_audits(session: TenantSession, subject: View) -> list[AuditOut]:
    """The audits you may open (all with assets.manage, else those you audit); live."""
    return [await _out(session, v) for v in await service.list_audits(session, subject)]


class AuditIn(BaseModel):
    """A new audit: what, who, where, when."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=NAME_MAX)
    kind: AuditKind
    description: str | None = Field(default=None, max_length=10_000)
    site_ids: list[uuid.UUID] = Field(default_factory=list, max_length=service.SCOPE_MAX)
    product_type_ids: list[uuid.UUID] = Field(default_factory=list, max_length=service.SCOPE_MAX)
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=service.SCOPE_MAX)
    planned_start: date | None = None
    planned_end: date | None = None
    auditor_ids: list[uuid.UUID] = Field(default_factory=list, max_length=service.AUDITORS_MAX)


class AuditPatch(BaseModel):
    """Plan fields to change (only those sent); a running audit keeps its scope."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    description: str | None = Field(default=None, max_length=10_000)
    site_ids: list[uuid.UUID] | None = Field(default=None, max_length=service.SCOPE_MAX)
    product_type_ids: list[uuid.UUID] | None = Field(default=None, max_length=service.SCOPE_MAX)
    group_ids: list[uuid.UUID] | None = Field(default=None, max_length=service.SCOPE_MAX)
    planned_start: date | None = None
    planned_end: date | None = None
    auditor_ids: list[uuid.UUID] | None = Field(default=None, max_length=service.AUDITORS_MAX)


@router.post(
    "",
    summary="Plan an asset audit",
    status_code=status.HTTP_201_CREATED,
    response_model=AuditOut,
    dependencies=[audited("asset_audit.created", object_type="asset_audit")],
)
async def create_audit(
    body: AuditIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """A draft (assets.manage). Idempotency-Key."""

    async def run() -> Created:
        view = await service.create_audit(
            session, subject, body.model_dump(), source=source_of(request)
        )
        return Created(body=await _out(session, view), headers={"ETag": f'"{view.audit.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get("/{audit_id}", summary="An asset audit", responses=NOT_FOUND)
async def get_audit(
    audit_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> AuditOut:
    """With its auditors and progress (404 when you may not open it)."""
    view = await service.get_audit(session, subject, audit_id)
    set_etag(response, view.audit.version)
    return await _out(session, view)


@router.patch(
    "/{audit_id}",
    summary="Change an asset audit's plan",
    responses=WRITE,
    dependencies=[
        audited("asset_audit.updated", object_type="asset_audit", object_param="audit_id")
    ],
)
async def patch_audit(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    audit_id: uuid.UUID,
    body: AuditPatch,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AuditOut:
    """The fields sent (If-Match). A closed audit is read-only (409 asset_audit_closed)."""
    sent = body.model_dump(include=body.model_fields_set)
    view = await service.update_audit(
        session, subject, audit_id, sent, expected_version=version, source=source_of(request)
    )
    set_etag(response, view.audit.version)
    return await _out(session, view)


@router.post(
    "/{audit_id}/start",
    summary="Start an asset audit",
    responses=WRITE,
    dependencies=[
        audited("asset_audit.started", object_type="asset_audit", object_param="audit_id")
    ],
)
async def start_audit(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    audit_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AuditOut:
    """Freezes the expected items (the assets in scope now); a self-audit asks each holder."""
    view = await service.start_audit(
        session, subject, audit_id, expected_version=version, source=source_of(request)
    )
    set_etag(response, view.audit.version)
    return await _out(session, view)


@router.post(
    "/{audit_id}/close",
    summary="Close an asset audit",
    responses=WRITE,
    dependencies=[
        audited("asset_audit.closed", object_type="asset_audit", object_param="audit_id")
    ],
)
async def close_audit(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    audit_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AuditOut:
    """Read-only from now on (If-Match)."""
    view = await service.close_audit(
        session, subject, audit_id, expected_version=version, source=source_of(request)
    )
    set_etag(response, view.audit.version)
    return await _out(session, view)


class AuditItemOut(BaseModel):
    """One asset in the audit, with what was found and any fix applied."""

    id: uuid.UUID
    asset_id: uuid.UUID
    tag: str | None
    name: str
    kind: AuditItemKind
    expected_site_id: uuid.UUID | None = Field(description="Its site when the audit started.")
    site_id: uuid.UUID | None = Field(description="Its site now.")
    state_id: uuid.UUID
    result: AuditItemResult | None
    method: AuditMarkMethod | None
    marked_by: AuditPersonOut | None
    marked_at: datetime | None
    seen_site_id: uuid.UUID | None
    note: str | None
    fix: AuditFix | None
    fixed_at: datetime | None
    discrepancy: bool
    version: int


async def _items_out(session: TenantSession, views: list[service.ItemView]) -> list[AuditItemOut]:
    people = sorted({str(v.item.marked_by) for v in views if v.item.marked_by})
    names = await user_names(session, people)
    return [
        AuditItemOut(
            id=v.item.id,
            asset_id=v.item.asset_id,
            tag=v.tag,
            name=v.name,
            kind=AuditItemKind(v.item.kind),
            expected_site_id=v.item.expected_site_id,
            site_id=v.site_id,
            state_id=v.state_id,
            result=None if v.item.result is None else AuditItemResult(v.item.result),
            method=None if v.item.method is None else AuditMarkMethod(v.item.method),
            marked_by=None
            if v.item.marked_by is None
            else AuditPersonOut(id=v.item.marked_by, name=names.get(str(v.item.marked_by))),
            marked_at=v.item.marked_at,
            seen_site_id=v.item.seen_site_id,
            note=v.item.note,
            fix=None if v.item.fix is None else AuditFix(v.item.fix),
            fixed_at=v.item.fixed_at,
            discrepancy=v.discrepancy,
            version=v.item.version,
        )
        for v in views
    ]


@router.get("/{audit_id}/items", summary="An audit's items", responses=NOT_FOUND)
async def list_items(
    audit_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    discrepancies: Annotated[bool, Query(description="Only the discrepancy list.")] = False,  # noqa: FBT002 - a query flag (FastAPI)
) -> list[AuditItemOut]:
    """Expected first, then unexpected; with `discrepancies`, only those to settle."""
    views = await service.list_items(session, subject, audit_id, discrepancies_only=discrepancies)
    return await _items_out(session, views)


class AuditMarkIn(BaseModel):
    """What the auditor found, by hand."""

    model_config = ConfigDict(extra="forbid")

    result: AuditItemResult
    seen_site_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=NOTE_MAX)


async def _item_out(
    session: TenantSession, subject: Subject, audit_id: uuid.UUID, item_id: uuid.UUID
) -> AuditItemOut:
    views = await service.list_items(session, subject, audit_id)
    found = [v for v in views if v.item.id == item_id]
    (out,) = await _items_out(session, found)
    return out


@router.patch(
    "/{audit_id}/items/{item_id}",
    summary="Mark an audit item",
    responses=MARK,
    dependencies=[
        audited("asset_audit.item_marked", object_type="asset_audit_item", object_param="item_id")
    ],
)
async def mark_item(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    audit_id: uuid.UUID,
    item_id: uuid.UUID,
    body: AuditMarkIn,
    session: TenantSession,
    subject: View,
    version: ExpectedVersion,
    response: Response,
    request: Request,
) -> AuditItemOut:
    """Named auditors only, while it runs (If-Match). Found elsewhere is the wrong place."""
    item = await service.mark_item(
        session, subject, audit_id, item_id,
        result=body.result, seen_site_id=body.seen_site_id, note=body.note,
        expected_version=version, source=source_of(request),
    )  # fmt: skip
    set_etag(response, item.version)
    return await _item_out(session, subject, audit_id, item.id)


class AuditScanIn(BaseModel):
    """A scanned code (the label's link, a tag, serial or barcode) and where it was seen."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=500)
    seen_site_id: uuid.UUID | None = None
    result: Literal["found", "damaged"] = "found"


@router.post(
    "/{audit_id}/scans",
    summary="Mark an audit item by scanning",
    status_code=status.HTTP_201_CREATED,
    response_model=AuditItemOut,
    responses=MARK,
    dependencies=[
        audited("asset_audit.item_marked", object_type="asset_audit", object_param="audit_id")
    ],
)
async def scan_item(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    audit_id: uuid.UUID,
    body: AuditScanIn,
    session: TenantSession,
    subject: View,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """The expected item, or a new unexpected one (an asset you may see). Idempotency-Key."""

    async def run() -> Created:
        item = await service.scan_mark(
            session, subject, audit_id,
            code=body.code, seen_site_id=body.seen_site_id, result=AuditItemResult(body.result),
            source=source_of(request),
        )  # fmt: skip
        out = await _item_out(session, subject, audit_id, item.id)
        return Created(body=out, headers={"ETag": f'"{item.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


class AuditHolderIn(BaseModel):
    """Who should hold the assets."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["user", "department"]
    id: uuid.UUID


class AuditFixIn(BaseModel):
    """One fix for many discrepancies: move site, change state, or assign."""

    model_config = ConfigDict(extra="forbid")

    fix: AuditFix
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=FIX_MAX)
    site_id: uuid.UUID | None = None
    state_id: uuid.UUID | None = None
    holder: AuditHolderIn | None = None
    reason: str | None = Field(default=None, max_length=REASON_MAX)


class FixOutcomeOut(BaseModel):
    """One item: fixed, or the problem code that stopped it (labelled in the UI)."""

    item_id: uuid.UUID
    applied: bool
    code: str | None


class AuditFixesOut(BaseModel):
    """Every item's outcome."""

    outcomes: list[FixOutcomeOut]
    applied: int


@router.post(
    "/{audit_id}/fixes",
    summary="Settle discrepancies",
    response_model=AuditFixesOut,
    responses=WRITE,
    dependencies=[
        audited("asset_audit.fixes_applied", object_type="asset_audit", object_param="audit_id")
    ],
)
async def apply_fixes(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    audit_id: uuid.UUID,
    body: AuditFixIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
) -> Response:
    """Each item through the asset service (permissions, life cycle, history naming the audit)."""

    async def run() -> AuditFixesOut:
        outcomes = await service.apply_fixes(
            session,
            subject,
            audit_id,
            service.FixRequest(
                fix=body.fix,
                item_ids=body.item_ids,
                site_id=body.site_id,
                state_id=body.state_id,
                holder=None if body.holder is None else Holder(body.holder.kind, body.holder.id),
                reason=body.reason,
            ),
            source=source_of(request),
        )
        return AuditFixesOut(
            outcomes=[
                FixOutcomeOut(item_id=o.item_id, applied=o.applied, code=o.code) for o in outcomes
            ],
            applied=sum(o.applied for o in outcomes),
        )

    return await idempotency.run(body, run, status_code=status.HTTP_200_OK)
