"""Audit log API (WP-018): read, search, verify, settings.

There is no route that changes or deletes an entry, for anyone (REQ-AUD-008); a route-table
test keeps it that way.

Reading the log is itself audited (`read.audit_log`, REQ-AUD-004). Auditors hold `audit.view`,
`audit.export` and `audit.verify` and change nothing; settings need `audit.manage` (tenant
administrators), and every settings change is audited with its old and new values.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import PERMISSION_ATTR, require_permission
from app.core.database import TenantSession
from app.core.errors import (
    FieldError,
    NotFound,
    PermissionDenied,
    ProblemDetail,
    ValidationFailed,
)
from app.modules.audit.domain.catalogue import (
    AuditActorType,
    AuditCategory,
    AuditClient,
    AuditOutcome,
    ReadCategory,
)
from app.modules.audit.events import AuditVerificationRequested
from app.modules.audit.infra.models import AuditVerificationRun
from app.modules.audit.service import exports, queries, retention, saved
from app.modules.audit.service.jobs import signer_from, storage_or_none
from app.modules.audit.service.recording import AuditNote, audit_read, audited
from app.modules.audit.service.settings import AuditSettingsView, load_settings, update_settings
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.listing import ListQuery, Page, list_query
from app.shared.api.ratelimit import rate_limit
from app.shared.clock import system_clock
from app.shared.events import record_event
from app.shared.history import source_of
from app.shared.ids import new_id
from app.shared.storage import StorageNotConfigured


class ExportFilter(StrEnum):
    """Fields an export can be filtered on (exact match)."""

    ACTION = "action"
    CATEGORY = "category"
    OUTCOME = "outcome"
    ACTOR_ID = "actor_id"
    OBJECT_TYPE = "object_type"
    OBJECT_ID = "object_id"
    CLIENT = "client"


VIEW = "audit.view"
EXPORT = "audit.export"
VERIFY = "audit.verify"
MANAGE = "audit.manage"

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(rate_limit("audit"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission."},
        404: {"model": ProblemDetail, "description": "No such entry or run."},
    },
)


def _hidden(permission: str) -> Any:  # noqa: ANN401 - a FastAPI dependency
    """`require_permission`, but answering 404.

    Without the permission the audit log does not exist for you (REQ-AUD-008 AC1).
    """
    inner = require_permission(permission)

    async def dependency(request: Request) -> Any:  # noqa: ANN401 - the policy's Subject
        try:
            return await inner(request)
        except PermissionDenied as exc:
            raise NotFound(code="not_found") from exc

    setattr(dependency, PERMISSION_ATTR, (permission,))
    return dependency


View = Annotated[Any, Depends(_hidden(VIEW))]
Verify = Annotated[Any, Depends(_hidden(VERIFY))]
Manage = Annotated[Any, Depends(_hidden(MANAGE))]
Export = Annotated[Any, Depends(_hidden(EXPORT))]
EntriesQuery = Annotated[ListQuery, Depends(list_query(queries.ENTRY_FIELDS))]


# --- schemas ------------------------------------------------------------------------------------


class AuditEntryOut(BaseModel):
    """One audit entry. `seq` is null while it waits to be sealed ("pending seal")."""

    id: uuid.UUID
    occurred_at: datetime
    action: str = Field(description="Action code; labels: `audit.action.<code>`.")
    category: AuditCategory
    module: str
    outcome: AuditOutcome
    reason_code: str | None
    actor_type: AuditActorType
    actor_id: uuid.UUID | None
    actor_name: str | None = Field(description="Null for system actors and erased people.")
    on_behalf_id: uuid.UUID | None
    object_type: str | None
    object_id: str | None
    object_name: str | None = Field(description="Name of a person the entry is about, if any.")
    details: dict[str, Any]
    client: AuditClient
    request_id: str | None
    change_id: uuid.UUID | None = Field(description="The field history this entry belongs to.")
    seq: int | None = Field(description="Position in the chain; null = pending seal.")


class AuditPersonalOut(BaseModel):
    """Personal values of one person in one entry (absent once the person is erased)."""

    subject_id: uuid.UUID
    ip: str | None = None
    user_agent: str | None = None
    reason: str | None = None


class AuditEntryDetailOut(AuditEntryOut):
    """An entry with its integrity data."""

    entry_hash: str
    prev_hash: str | None
    chain_hash: str | None
    sealed_at: datetime | None
    personal: list[AuditPersonalOut]
    names: dict[str, str] = Field(
        description="Names of the people this entry mentions (by user ID), looked up now."
    )


class AuditEntryPage(Page[AuditEntryOut]):
    """A page of the audit log."""


class AuditRunOut(BaseModel):
    """A verification run."""

    id: uuid.UUID
    kind: str = Field(description="daily | weekly | on_demand")
    status: str = Field(description="running | passed | failed | error")
    range_from: datetime | None
    range_to: datetime | None
    entries_checked: int
    unsealed_overdue: int
    first_broken_seq: int | None
    first_broken_entry_id: uuid.UUID | None
    problem: str | None = Field(description="Labels: `audit.problem.<code>`.")
    requested_by: uuid.UUID | None
    started_at: datetime
    finished_at: datetime | None


class AuditRunIn(BaseModel):
    """Verify a time range now (both empty = the whole chain)."""

    model_config = ConfigDict(extra="forbid")

    range_from: datetime | None = None
    range_to: datetime | None = None


class AuditStatusOut(BaseModel):
    """The integrity panel and the console banner."""

    sealed_entries: int
    pending_seal: int
    pending_overdue: int
    anchoring_configured: bool
    last_anchor_at: datetime | None
    last_anchor_seq: int | None
    last_daily: AuditRunOut | None
    last_weekly: AuditRunOut | None
    last_on_demand: AuditRunOut | None
    alert: str | None = Field(description="Unresolved problem code (banner), or null.")


class AuditSettingsOut(BaseModel):
    """Audit settings (defaults until changed; `version` 0 = never changed)."""

    retention_days: int
    read_window_minutes: int
    refusal_threshold: int
    refusal_window_minutes: int
    read_categories: list[ReadCategory]
    version: int
    limits: dict[str, list[int]] = Field(description="Allowed [min, max] per number.")


class AuditSettingsIn(BaseModel):
    """Settings to change (only those sent)."""

    model_config = ConfigDict(extra="forbid")

    retention_days: int | None = None
    read_window_minutes: int | None = None
    refusal_threshold: int | None = None
    refusal_window_minutes: int | None = None
    read_categories: list[ReadCategory] | None = None


async def _names(session: TenantSession, ids: list[uuid.UUID | None]) -> dict[str, str]:
    """Names of people, looked up now (entries hold IDs only)."""
    # Imported here: identity_access imports this package at load time.
    from app.modules.identity_access import user_names  # noqa: PLC0415

    wanted = sorted({str(i) for i in ids if i is not None})
    return await user_names(session, wanted) if wanted else {}


class AuditExportIn(BaseModel):
    """What to export: a time range, a format and optional filters (exact matches)."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["jsonl", "csv"] = "jsonl"
    range_from: datetime | None = None
    range_to: datetime | None = None
    filters: dict[ExportFilter, str] = Field(
        default_factory=dict, description="Without filters the export proves completeness."
    )


class AuditExportOut(BaseModel):
    """An export and where it stands."""

    id: uuid.UUID
    status: str = Field(description="running | ready | failed | expired")
    format: str
    range_from: datetime | None
    range_to: datetime | None
    filters: dict[str, str]
    entries: int
    size_bytes: int | None
    sha256: str | None
    verification: str | None = Field(description="The server's own verification: passed | failed")
    problem: str | None = Field(description="Why it failed; labels: `errors.<code>`.")
    requested_by: uuid.UUID | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None


class AuditSavedSearchIn(BaseModel):
    """A search to keep (the list's query parameters)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    query: dict[str, str] = Field(description="Query parameters of /audit/entries.")


class AuditSavedSearchOut(BaseModel):
    """A saved search of yours."""

    id: uuid.UUID
    name: str
    query: dict[str, str]
    created_at: datetime


def _as_uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _people(entry: Any) -> list[uuid.UUID | None]:  # noqa: ANN401 - AuditEntry row
    """The actor, and the object when it is a person."""
    found = [entry.actor_id, entry.on_behalf_id]
    if entry.object_type == "user":
        found.append(_as_uuid(entry.object_id))
    return found


def _mentioned(entry: Any) -> list[uuid.UUID | None]:  # noqa: ANN401 - AuditEntry row
    """IDs in the details that may be people (names are looked up; unknown IDs drop out)."""
    return [_as_uuid(v) for v in entry.details.values() if isinstance(v, str)]


def _entry(view: queries.EntryView, names: dict[str, str]) -> AuditEntryOut:
    e = view.entry
    return AuditEntryOut(
        id=e.id,
        occurred_at=e.occurred_at,
        action=e.action,
        category=AuditCategory(e.category),
        module=e.module,
        outcome=AuditOutcome(e.outcome),
        reason_code=e.reason_code,
        actor_type=AuditActorType(e.actor_type),
        actor_id=e.actor_id,
        actor_name=names.get(str(e.actor_id)) if e.actor_id else None,
        on_behalf_id=e.on_behalf_id,
        object_type=e.object_type,
        object_id=e.object_id,
        object_name=names.get(e.object_id or "") if e.object_type == "user" else None,
        details=dict(e.details),
        client=AuditClient(e.client),
        request_id=e.request_id,
        change_id=e.change_id,
        seq=view.seq,
    )


def _run(run: AuditVerificationRun | None) -> AuditRunOut | None:
    if run is None:
        return None
    return AuditRunOut.model_validate(run, from_attributes=True)


def _settings(view: AuditSettingsView) -> AuditSettingsOut:
    from app.modules.audit.service.settings import LIMITS  # noqa: PLC0415 - small constant

    return AuditSettingsOut(
        retention_days=view.retention_days,
        read_window_minutes=view.read_window_minutes,
        refusal_threshold=view.refusal_threshold,
        refusal_window_minutes=view.refusal_window_minutes,
        read_categories=[ReadCategory(c) for c in view.read_categories],
        version=view.version,
        limits={name: list(bounds) for name, bounds in LIMITS.items()},
    )


# --- routes -------------------------------------------------------------------------------------


@router.get(
    "/entries",
    summary="Search the audit log",
    dependencies=[audit_read(ReadCategory.AUDIT_LOG)],
)
async def list_entries(
    session: TenantSession, query: EntriesQuery, subject: View
) -> AuditEntryPage:
    """Newest first by default; filter by actor, action, outcome, object, client, time range."""
    del subject
    views, page = await queries.list_entries(session, query)
    names = await _names(session, [i for v in views for i in _people(v.entry)])
    return AuditEntryPage(
        items=[_entry(v, names) for v in views],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


@router.get("/status", summary="Integrity status of the audit log")
async def get_status(request: Request, session: TenantSession, subject: View) -> AuditStatusOut:
    """Sealing, anchoring and the latest verifications (the integrity panel and the banner)."""
    del subject
    settings = request.app.state.settings
    found = await queries.integrity_status(
        session,
        anchoring_configured=signer_from(settings) is not None,
        unsealed_limit=_seconds(settings.audit_unsealed_alert_seconds),
    )
    return AuditStatusOut(
        sealed_entries=found.sealed_entries,
        pending_seal=found.pending_seal,
        pending_overdue=found.pending_overdue,
        anchoring_configured=found.anchoring_configured,
        last_anchor_at=found.last_anchor_at,
        last_anchor_seq=found.last_anchor_seq,
        last_daily=_run(found.last_daily),
        last_weekly=_run(found.last_weekly),
        last_on_demand=_run(found.last_on_demand),
        alert=found.alert,
    )


@router.get("/verification-runs", summary="Verification runs")
async def list_runs(session: TenantSession, subject: View) -> list[AuditRunOut]:
    """The latest 20 runs, newest first."""
    del subject
    from app.modules.audit.service.integrity import latest_runs  # noqa: PLC0415

    return [r for r in (_run(run) for run in await latest_runs(session)) if r is not None]


@router.post(
    "/verification-runs",
    summary="Verify a range now",
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    body: AuditRunIn,
    session: TenantSession,
    subject: Verify,
    note: Annotated[
        AuditNote, audited("audit.verification_requested", object_type="audit_verification_run")
    ],
) -> AuditRunOut:
    """Starts a background verification; follow it in the run list or the status."""
    del subject
    if body.range_from and body.range_to and body.range_to <= body.range_from:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.range_to",
                    code="range_end_before_start",
                    message_key="errors.field.range_end_before_start",
                )
            ]
        )
    context = session.info["supportx.tenant"]
    run = AuditVerificationRun(
        id=new_id(),
        tenant_id=context.tenant_id,
        kind="on_demand",
        status="running",
        range_from=body.range_from,
        range_to=body.range_to,
        requested_by=context.user_id,
        started_at=system_clock.now(),
    )
    session.add(run)
    await session.flush()
    await record_event(session, AuditVerificationRequested(run_id=run.id), aggregate_id=run.id)
    note.object_id = str(run.id)
    note.details = {"range_from": body.range_from, "range_to": body.range_to}
    out = _run(run)
    assert out is not None  # noqa: S101 - just created
    return out


@router.get(
    "/entries/{entry_id}",
    summary="One audit entry",
    dependencies=[
        audit_read(ReadCategory.AUDIT_LOG, object_type="audit_entry", object_param="entry_id")
    ],
)
async def get_entry(
    entry_id: uuid.UUID, session: TenantSession, subject: View
) -> AuditEntryDetailOut:
    """An entry with its chain position, hashes and personal values (IP address, client)."""
    del subject
    detail = await queries.get_entry(session, entry_id)
    names = await _names(session, [*_people(detail.view.entry), *_mentioned(detail.view.entry)])
    base = _entry(detail.view, names).model_dump()
    return AuditEntryDetailOut(
        **base,
        entry_hash=detail.view.entry.entry_hash.hex(),
        prev_hash=detail.prev_hash.hex() if detail.prev_hash else None,
        chain_hash=detail.chain_hash.hex() if detail.chain_hash else None,
        sealed_at=detail.sealed_at,
        personal=[
            AuditPersonalOut(subject_id=uuid.UUID(subject_id), **data)
            for subject_id, data in sorted(detail.personal.items())
        ],
        names=names,
    )


@router.get("/settings", summary="Audit settings")
async def get_settings(
    response: Response, session: TenantSession, subject: View
) -> AuditSettingsOut:
    """Retention, the read window, the probing alert and which reads are logged."""
    del subject
    current = await load_settings(session)
    set_etag(response, current.version)
    return _settings(current)


@router.put("/settings", summary="Change audit settings")
async def put_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    request: Request,
    body: AuditSettingsIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
    note: Annotated[AuditNote, audited("audit.settings_changed", object_type="audit_settings")],
) -> AuditSettingsOut:
    """Change settings within the platform limits (If-Match; "0" before the first change)."""
    del subject
    changes: dict[str, object] = body.model_dump(exclude_none=True)
    if "read_categories" in changes:
        changes["read_categories"] = [c.value for c in body.read_categories or []]
    before, after = await update_settings(
        session, expected_version=version, changes=changes, source=source_of(request)
    )
    old, new = before.values(), after.values()
    changed = {name: {"old": old[name], "new": new[name]} for name in new if old[name] != new[name]}
    note.skip = not changed
    note.details = {"changes": changed}
    set_etag(response, after.version)
    return _settings(after)


def _seconds(value: int) -> Any:  # noqa: ANN401 - timedelta
    from datetime import timedelta  # noqa: PLC0415

    return timedelta(seconds=value)


# --- exports (REQ-AUD-009) -------------------------------------------------------------------


@router.post("/exports", summary="Export the audit log", status_code=status.HTTP_202_ACCEPTED)
async def start_export(
    request: Request,
    body: AuditExportIn,
    session: TenantSession,
    subject: Export,
    note: Annotated[AuditNote, audited("audit.export_requested", object_type="audit_export")],
) -> AuditExportOut:
    """Built in the background; follow it in the export list. 503 if storage is missing."""
    del subject
    if body.range_from and body.range_to and body.range_to <= body.range_from:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.range_to",
                    code="range_end_before_start",
                    message_key="errors.field.range_end_before_start",
                )
            ]
        )
    row = await exports.request_export(
        session,
        exports.ExportRequest(
            format=body.format,
            range_from=body.range_from,
            range_to=body.range_to,
            filters={k.value: v for k, v in body.filters.items()},
        ),
        storage_ready=storage_or_none(request.app.state.settings) is not None,
    )
    note.object_id = str(row.id)
    note.details = {"format": body.format, "filtered": bool(body.filters)}
    return AuditExportOut.model_validate(row, from_attributes=True)


@router.get("/exports", summary="Audit exports")
async def list_exports(session: TenantSession, subject: Export) -> list[AuditExportOut]:
    """The latest 20, newest first."""
    del subject
    return [
        AuditExportOut.model_validate(row, from_attributes=True)
        for row in await exports.list_exports(session)
    ]


@router.get(
    "/exports/{export_id}/download",
    summary="Download an export",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}, 409: {"model": ProblemDetail}},
)
async def download_export(
    request: Request,
    export_id: uuid.UUID,
    session: TenantSession,
    subject: Export,
    note: Annotated[
        AuditNote,
        audited("audit.export_downloaded", object_type="audit_export", object_param="export_id"),
    ],
) -> Response:
    """The zip (manifest, signature, data, verifier). Downloading is audited."""
    del subject
    storage = storage_or_none(request.app.state.settings)
    if storage is None:
        raise StorageNotConfigured
    row, data = await exports.download(session, storage, export_id)
    note.details = {"sha256": row.sha256}
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="supportx-audit-{row.id}.zip"',
            "X-Content-SHA256": row.sha256 or "",
        },
    )


# --- archives and restores (retention, D-075 item 10) ------------------------------------------


class AuditArchiveOut(BaseModel):
    """A month past retention, archived to object storage (or why that failed)."""

    id: uuid.UUID
    range_from: datetime
    range_to: datetime
    status: str = Field(description="ready | failed")
    entries: int
    first_seq: int | None
    last_seq: int | None
    sha256: str | None
    problem: str | None = Field(description="Why it failed; labels: `errors.<code>`.")
    created_at: datetime
    restore_status: str | None = Field(description="running | ready | failed, or null")
    restore_problem: str | None = Field(description="Why the restore failed: `errors.<code>`.")
    restored_until: datetime | None


class AuditRestoredPage(BaseModel):
    """A page of a restored archive, in chain order (`seq` is the position in the chain)."""

    items: list[AuditEntryOut]
    next_cursor: str | None
    has_more: bool


@router.get("/archives", summary="Audit archives")
async def list_archives(session: TenantSession, subject: View) -> list[AuditArchiveOut]:
    """Months archived past retention, newest first (failed attempts too)."""
    del subject
    return [
        AuditArchiveOut.model_validate(row, from_attributes=True)
        for row in await retention.list_archives(session)
    ]


@router.post(
    "/archives/{archive_id}/restore",
    summary="Restore an archive for an investigation",
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: {"model": ProblemDetail}, 503: {"model": ProblemDetail}},
)
async def restore_archive(
    request: Request,
    archive_id: uuid.UUID,
    session: TenantSession,
    subject: Export,
    note: Annotated[
        AuditNote,
        audited(
            "audit.archive_restore_requested",
            object_type="audit_archive",
            object_param="archive_id",
        ),
    ],
) -> AuditArchiveOut:
    """Read back, verified again, and browsable for 7 days; the live log is not changed."""
    del subject
    row = await retention.request_restore(
        session,
        archive_id,
        storage_ready=storage_or_none(request.app.state.settings) is not None,
    )
    note.details = {"range_from": row.range_from, "range_to": row.range_to}
    return AuditArchiveOut.model_validate(row, from_attributes=True)


@router.get(
    "/archives/{archive_id}/entries",
    summary="Entries of a restored archive",
    dependencies=[
        audit_read(ReadCategory.AUDIT_LOG, object_type="audit_archive", object_param="archive_id")
    ],
    responses={409: {"model": ProblemDetail}},
)
async def list_restored(
    archive_id: uuid.UUID,
    session: TenantSession,
    subject: View,
    cursor: str | None = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> AuditRestoredPage:
    """In chain order; `cursor` is the last position of the previous page."""
    del subject
    after = int(cursor) if cursor is not None and cursor.isdigit() else 0
    _, rows = await retention.restored_entries(
        session, archive_id, after_seq=after, limit=limit + 1
    )
    page = rows[:limit]
    contents = [{**row.entry, "seq": row.seq} for row in page]
    names = await _names(
        session, [_as_uuid(c.get("actor_id")) for c in contents if c.get("actor_id")]
    )
    items = [
        AuditEntryOut.model_validate(
            {
                **c,
                "actor_name": names.get(str(c.get("actor_id"))),
                "object_name": None,
            }
        )
        for c in contents
    ]
    has_more = len(rows) > limit
    return AuditRestoredPage(
        items=items,
        next_cursor=str(page[-1].seq) if has_more and page else None,
        has_more=has_more,
    )


# --- saved searches (REQ-AUD-007) ------------------------------------------------------------


@router.get("/saved-searches", summary="Your saved audit searches")
async def list_saved(session: TenantSession, subject: View) -> list[AuditSavedSearchOut]:
    """Only your own."""
    rows = await saved.list_saved(session, subject.user_id)
    return [AuditSavedSearchOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/saved-searches", summary="Save an audit search", status_code=status.HTTP_201_CREATED)
async def create_saved(
    body: AuditSavedSearchIn, session: TenantSession, subject: View
) -> AuditSavedSearchOut:
    """Keep the current filters under a name (at most 50 per person)."""
    row = await saved.create_saved(session, subject.user_id, body.name, body.query)
    return AuditSavedSearchOut.model_validate(row, from_attributes=True)


@router.delete(
    "/saved-searches/{search_id}",
    summary="Delete a saved audit search",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_saved(search_id: uuid.UUID, session: TenantSession, subject: View) -> Response:
    """Only your own; someone else's is 404."""
    await saved.delete_saved(session, subject.user_id, search_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
