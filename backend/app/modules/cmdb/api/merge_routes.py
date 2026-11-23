"""CMDB merge and import API under /api/v1/cmdb (WP-053 S4b; REQ-CMDB-017, 018). No logic here.

- `/cmdb/merges/preview`, `/cmdb/merges`: merge a duplicate CI into another (`cmdb.manage` on
  both, checked by the service). One `cmdb.ci_merged` audit entry holds the field mapping.
- `/cmdb/imports`: upload a CSV or Excel file of CIs or relationships (a dry run by default),
  follow its progress live, run a checked dry run for real, and download the refused rows.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.body_limit import body_limit
from app.core.database import TenantSession
from app.core.errors import ProblemDetail, ValidationFailed
from app.modules.audit import AuditNote, audited
from app.modules.cmdb.api.routes import CiOut
from app.modules.cmdb.domain import merge as domain
from app.modules.cmdb.infra.models import CiImport
from app.modules.cmdb.service import catalogue, imports, merge
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/cmdb",
    tags=["cmdb"],
    dependencies=[Depends(rate_limit("cmdb"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
        404: {"model": ProblemDetail, "description": "No such record visible to you."},
    },
)

View = Annotated[Subject, Depends(require_permission(catalogue.VIEW))]
Manage = Annotated[Subject, Depends(require_permission(catalogue.MANAGE))]
# Codes as named schemas (labelled `cmdb_merge_side.<code>` and so on).
CiMergeSide = domain.CiMergeSide
CiImportKind = domain.CiImportKind
CiImportMode = domain.CiImportMode
CiImportMatch = domain.CiImportMatch
CiImportStatus = domain.CiImportStatus


# --- merge (REQ-CMDB-017) -------------------------------------------------------------------------


class CiMergeFieldOut(BaseModel):
    """One field of the preview: both values and the suggested side.

    A custom field the reader may not read (ADR-047 hidden or masked) is never listed: it stays
    the survivor's.
    """

    field: str
    survivor: Any = Field(description="The survivor's value (JSON).")
    merged: Any = Field(description="The merged CI's value (JSON).")
    side: CiMergeSide


class CiMergePreviewOut(BaseModel):
    """The two CIs in the suggested order (`swapped`: reversed from the order asked)."""

    survivor: CiOut
    merged: CiOut
    swapped: bool
    fields: list[CiMergeFieldOut]


@router.get(
    "/merges/preview",
    summary="Preview merging two CIs",
    responses={409: {"model": ProblemDetail, "description": "cmdb_merge_types_differ"}},
)
async def merge_preview(
    first: Annotated[uuid.UUID, Query(description="One CI.")],
    second: Annotated[uuid.UUID, Query(description="The other.")],
    session: TenantSession,
    subject: Manage,
) -> CiMergePreviewOut:
    """cmdb.manage on both (each within your scope); the suggested survivor comes first."""
    found = await merge.preview(session, subject, first, second)
    return CiMergePreviewOut(
        survivor=CiOut.of_view(found.survivor),
        merged=CiOut.of_view(found.merged),
        swapped=found.swapped,
        fields=[
            CiMergeFieldOut(field=f.field, survivor=f.survivor, merged=f.merged, side=f.side)
            for f in found.fields
        ],
    )


class CiMergeIn(BaseModel):
    """Merge one CI into another, at the versions you saw, with your field choices."""

    model_config = ConfigDict(extra="forbid")

    survivor_id: uuid.UUID
    survivor_version: int
    merged_id: uuid.UUID
    merged_version: int
    choices: dict[str, CiMergeSide] = Field(
        default_factory=dict, description="Field -> side; a field left out keeps the suggestion."
    )


class CiMergeMappingOut(BaseModel):
    """Which side one field took."""

    field: str
    side: CiMergeSide


class CiMergeOut(BaseModel):
    """The survivor after the merge, the mapping and what moved to it (counts)."""

    alias_id: uuid.UUID
    survivor: CiOut
    mapping: list[CiMergeMappingOut]
    moved: dict[str, int]


@router.post(
    "/merges",
    summary="Merge a duplicate CI into another",
    status_code=status.HTTP_201_CREATED,
    response_model=CiMergeOut,
    responses={
        409: {
            "model": ProblemDetail,
            "description": "version_conflict, cmdb_merge_types_differ, cmdb_merge_both_assets",
        }
    },
)
async def merge_cis(  # noqa: PLR0913 - FastAPI dependencies
    *,
    body: CiMergeIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    request: Request,
    note: Annotated[AuditNote, audited("cmdb.ci_merged", object_type="ci")],
) -> Response:
    """cmdb.manage on both CIs; the merged one goes to the trash.

    Its ID then opens the survivor, for whoever may see the survivor. One audit entry holds the
    field mapping. Send an Idempotency-Key.
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
        note.object_id = str(done.survivor.record.id)
        note.details = {
            "merged_ci_id": str(body.merged_id),
            "mapping": done.mapping,
            "moved": done.moved,
        }
        return Created(
            body=CiMergeOut(
                alias_id=done.alias.id,
                survivor=CiOut.of_view(done.survivor),
                mapping=[
                    CiMergeMappingOut(field=m["field"], side=CiMergeSide(m["side"]))
                    for m in done.mapping
                ],
                moved=done.moved,
            ),
            headers={"ETag": f'"{done.survivor.record.version}"'},
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


# --- imports (REQ-CMDB-018) -----------------------------------------------------------------------


class CiImportProblemOut(BaseModel):
    """One refused row: its number in the file, the column and the reason code."""

    row: int | None
    field: str | None
    code: str


class CiImportOut(BaseModel):
    """An import and how far it got. Updates live (`cmdb.import_progress`)."""

    id: uuid.UUID
    kind: CiImportKind
    mode: CiImportMode
    match_on: CiImportMatch
    type_id: uuid.UUID | None
    dry_run: bool
    file_name: str
    file_format: Literal["csv", "xlsx"]
    status: CiImportStatus
    total: int
    processed: int
    created_count: int
    updated_count: int
    unchanged_count: int
    kept_count: int = Field(
        description="Rows that changed nothing: a stronger source set the values (who wins)."
    )
    failed_count: int
    problems: list[CiImportProblemOut]
    failure: str | None
    failure_detail: str | None
    created_at: datetime
    checked_at: datetime | None
    finished_at: datetime | None
    version: int

    @classmethod
    def of(cls, row: CiImport) -> "CiImportOut":
        """From the row (never the file)."""
        return cls.model_validate(row, from_attributes=True)


class CiImportTarget(BaseModel):
    """The Idempotency-Key fingerprint of an upload."""

    name: str
    kind: str
    mode: str
    match_on: str
    type_id: uuid.UUID | None
    dry_run: bool
    size: int


@router.post(
    "/imports",
    summary="Import CIs or relationships from a CSV or Excel file",
    dependencies=[Depends(body_limit(domain.IMPORT_LIMITS.max_file_bytes + 1))],
    status_code=status.HTTP_201_CREATED,
    response_model=CiImportOut,
    responses={422: {"model": ProblemDetail, "description": "cmdb_import_file_too_large"}},
)
async def start_import(  # noqa: PLR0913 - the upload's facts, explicit
    *,
    request: Request,
    session: TenantSession,
    subject: View,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("cmdb.import_started", object_type="cmdb_import")],
    name: Annotated[str, Query(min_length=1, max_length=255)],
    kind: Annotated[CiImportKind, Query()],
    mode: Annotated[CiImportMode, Query()] = CiImportMode.ADD_UPDATE,
    match_on: Annotated[CiImportMatch, Query()] = CiImportMatch.NAME,
    type_id: Annotated[uuid.UUID | None, Query(description="CIs: their type.")] = None,
    dry_run: Annotated[bool, Query(description="Check every row and change nothing.")] = True,
) -> Response:
    """The raw file as the body (up to 25 MB, 20,000 rows); it is read in the background.

    CIs need cmdb.add to add and cmdb.edit to update (or cmdb.manage); relationships need
    cmdb.edit. A dry run (the default) changes nothing. Send an Idempotency-Key.
    """
    content = bytearray()
    async for piece in request.stream():
        content += piece
        if len(content) > domain.IMPORT_LIMITS.max_file_bytes:
            raise ValidationFailed(code="cmdb_import_file_too_large", params=imports.FORMAT_WORDS)
    note.skip = True
    target = CiImportTarget(
        name=name,
        kind=kind,
        mode=mode,
        match_on=match_on,
        type_id=type_id,
        dry_run=dry_run,
        size=len(content),
    )

    async def operation() -> Created:
        job = await imports.start_import(
            session,
            subject,
            kind=kind,
            mode=mode,
            match_on=match_on,
            type_id=type_id,
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
        return Created(CiImportOut.of(job), headers={"ETag": f'"{job.version}"'})

    return await idempotency.run(target, operation)


@router.get("/imports", summary="Your latest CMDB imports")
async def list_imports(session: TenantSession, subject: View) -> list[CiImportOut]:
    """The last 20, newest first."""
    return [CiImportOut.of(job) for job in await imports.recent_imports(session, subject)]


@router.get(
    "/imports/{import_id}",
    summary="One of your CMDB imports",
    responses={404: {"model": ProblemDetail, "description": "cmdb_import_not_found"}},
)
async def get_import(
    import_id: uuid.UUID, session: TenantSession, subject: View, response: Response
) -> CiImportOut:
    """Its progress and refused rows."""
    job = await imports.own_import(session, subject, import_id)
    set_etag(response, job.version)
    return CiImportOut.of(job)


@router.get(
    "/imports/{import_id}/problems",
    summary="The refused rows of one of your imports (CSV)",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def import_problems(
    import_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    language: Annotated[Literal["en", "ar", "ur"], Query()] = "en",
) -> Response:
    """Row, column and reason in your language; codes only, never a value from the file."""
    job = await imports.own_import(session, subject, import_id)
    return Response(
        content=imports.problems_csv(job, language),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="import-problems.csv"'},
    )


@router.post(
    "/imports/{import_id}/run",
    summary="Run a checked dry run for real",
    responses={409: {"model": ProblemDetail, "description": "cmdb_import_not_checked"}},
    dependencies=[audited("cmdb.import_run", object_type="cmdb_import", object_param="import_id")],
)
async def run_import(
    import_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    version: ExpectedVersion,
    response: Response,
) -> CiImportOut:
    """The same file, mode and match, applied this time (If-Match)."""
    job = await imports.start_run(session, subject, import_id, expected_version=version)
    set_etag(response, job.version)
    return CiImportOut.of(job)
