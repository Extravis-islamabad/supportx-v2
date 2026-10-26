"""Files API (WP-022, REQ-INC-079; ADR-028). Mounted by the system module (platform service).

- `POST /files` takes the raw file body (no multipart): the browser sends a `File` as it is, and
  the API streams it into encrypted storage. Owner, name and inline flag are query parameters;
  `Content-Length` lets a too-large file be refused before any byte is read (AC2). An
  `Idempotency-Key` makes a retried upload return the same file.
- Who may see or attach is answered by the owner's module; private notes' files stay with staff.
- `POST /files/{id}/link` gives a link that lives minutes (AC3); the content route checks it and the
  user's access again, and streams ranges (PDF previews, AC4). Only `clean` files open (AC1).
- `GET /files/{id}/inline` and `/thumbnail`: images for the editor and the attachment list.
- Admin (`files.manage`): rules, usage, scanning status (never silent about missing scanning).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.core.errors import ProblemDetail, ValidationFailed
from app.modules.audit import AuditNote, audited
from app.modules.system.service.files import api_services
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.files.domain.states import FileState, openable
from app.shared.files.domain.tokens import Disposition
from app.shared.files.domain.types import Kind, Sniffed, inline_allowed
from app.shared.files.infra.models import FileLink, StoredFile
from app.shared.files.ports import Action, Actor, OwnerType
from app.shared.files.service import access, admin, scanning, uploads
from app.shared.files.service.core import FileServices, rules

MANAGE = "files.manage"
SignedIn = Annotated[Any, Depends(require_signed_in())]
Manage = Annotated[Any, Depends(require_permission(MANAGE))]
Files = Annotated[FileServices, Depends(api_services)]

router = APIRouter(
    prefix="/files",
    tags=["files"],
    dependencies=[Depends(rate_limit("files"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Not allowed, or over the storage limit."},
        404: {"model": ProblemDetail, "description": "No such file (or not visible to you)."},
    },
)


class FileOut(BaseModel):
    """A file and where it is attached. The scan state decides whether it opens."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    size: int
    content_type: str
    kind: Kind
    state: FileState
    openable: bool
    previewable: bool
    has_thumbnail: bool
    owner_type: OwnerType
    owner_id: uuid.UUID
    record_type: str | None
    record_id: uuid.UUID | None
    inline: bool
    uploaded_by: uuid.UUID | None
    created_at: datetime
    version: int


def _out(stored: StoredFile, link: FileLink, files: FileServices) -> FileOut:
    state = FileState(stored.state)
    sniffed = Sniffed(stored.content_type, Kind(stored.kind), active_markup=stored.active_markup)
    usable = openable(state, scan_required=files.scan_required)
    return FileOut(
        id=stored.id,
        name=stored.name,
        size=stored.size,
        content_type=stored.content_type,
        kind=Kind(stored.kind),
        state=state,
        openable=usable,
        previewable=usable and inline_allowed(sniffed),
        has_thumbnail=usable and stored.thumb_key is not None,
        owner_type=OwnerType(link.owner_type),
        owner_id=link.owner_id,
        record_type=link.record_type,
        record_id=link.record_id,
        inline=link.inline,
        uploaded_by=stored.created_by,
        created_at=stored.created_at,
        version=stored.version,
    )


class UploadTarget(BaseModel):
    """What an upload is for (also the Idempotency-Key fingerprint)."""

    owner_type: OwnerType
    owner_id: uuid.UUID
    name: str
    size: int | None
    inline: bool


async def _body(request: Request) -> Any:  # noqa: ANN401 - an async iterator of bytes
    async for piece in request.stream():
        if piece:
            yield piece


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=FileOut,
    responses={
        413: {"model": ProblemDetail},
        422: {"model": ProblemDetail, "description": "Too large or type blocked."},
        503: {"model": ProblemDetail, "description": "Storage or file keys not configured."},
    },
)
async def upload_file(  # noqa: PLR0913 - the upload's facts, explicit
    *,
    request: Request,
    session: TenantSession,
    subject: SignedIn,
    files: Files,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("file.uploaded", object_type="file")],
    owner_type: Annotated[OwnerType, Query()],
    owner_id: Annotated[uuid.UUID, Query()],
    name: Annotated[str, Query(min_length=1, max_length=1000)],
    inline: Annotated[bool, Query()] = False,
) -> Response:
    """Upload one file (raw body). Several files: one request each, in parallel."""
    length = request.headers.get("content-length")
    target = UploadTarget(
        owner_type=owner_type,
        owner_id=owner_id,
        name=name,
        size=int(length) if length and length.isdigit() else None,
        inline=inline,
    )

    async def run() -> Created:
        stored, link = await uploads.upload(
            session,
            files,
            subject,
            uploads.Target(owner_type, owner_id, inline=inline),
            name=name,
            declared_size=target.size,
            body=_body(request),
        )
        note.object_id = str(stored.id)
        note.details = {"owner_type": owner_type.value, "size": stored.size}
        return Created(_out(stored, link, files))

    return await idempotency.run(target, run, status_code=201)


class AttachIn(BaseModel):
    """Editor drafts to move onto the entry or record that was just saved."""

    owner_type: OwnerType
    owner_id: uuid.UUID
    file_ids: list[uuid.UUID] = Field(max_length=50)


@router.post("/attach")
async def attach_drafts(
    body: AttachIn, session: TenantSession, subject: SignedIn
) -> list[uuid.UUID]:
    """Attach your editor drafts (pasted images) to what they were pasted into."""
    if body.owner_type == OwnerType.DRAFT:
        raise ValidationFailed(code="file_owner_not_allowed")
    links = await uploads.attach_drafts(
        session, subject, body.file_ids, uploads.Target(body.owner_type, body.owner_id)
    )
    return [link.file_id for link in links]


@router.get("/records/{record_type}/{record_id}")
async def record_files(
    record_type: str, record_id: uuid.UUID, session: TenantSession, subject: SignedIn, files: Files
) -> list[FileOut]:
    """Every file on a record, its replies and notes that you may see."""
    found = await access.for_record(session, subject, record_type, record_id)
    return [_out(item.file, item.link, files) for item in found]


@router.get("/{file_id}")
async def get_file(
    file_id: uuid.UUID, response: Response, session: TenantSession, subject: SignedIn, files: Files
) -> FileOut:
    """One file (its scan state, for the screen that is waiting on it)."""
    found = await access.authorize(session, subject, file_id, Action.VIEW)
    set_etag(response, found.file.version)
    return _out(found.file, found.link, files)


class LinkIn(BaseModel):
    """Open in the browser (images and PDFs) or download."""

    disposition: Disposition = Disposition.ATTACHMENT


class LinkOut(BaseModel):
    """A link that works for a few minutes, for you only."""

    url: str
    expires_at: datetime


@router.post("/{file_id}/link")
async def create_link(
    file_id: uuid.UUID, body: LinkIn, session: TenantSession, subject: SignedIn, files: Files
) -> LinkOut:
    """A fresh short-lived link (409 `file_not_ready` while it is being checked or blocked)."""
    token, expires_at = await access.issue_link(session, files, subject, file_id, body.disposition)
    return LinkOut(url=f"/api/v1/files/content/{token}", expires_at=expires_at)


def _content_disposition(disposition: Disposition, name: str) -> str:
    ascii_name = name.encode("ascii", "replace").decode().replace('"', "")
    return f"{disposition.value}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def _policy(content: access.Content) -> str:
    """The file runs nothing: no scripts, plugins or forms, whatever it claims to be.

    `sandbox` everywhere except a PDF shown inline: browsers refuse to open their PDF viewer in a
    sandboxed document, and the viewer itself does not run the file's scripts.
    """
    if content.disposition == Disposition.INLINE and content.content_type == "application/pdf":
        return "default-src 'none'; object-src 'self'; style-src 'unsafe-inline'"
    return "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"


def _stream(content: access.Content, *, cache: str) -> StreamingResponse:
    headers = {
        "Content-Disposition": _content_disposition(content.disposition, content.name),
        "Content-Length": str(content.end - content.start + 1 if content.size else 0),
        "Accept-Ranges": "bytes",
        "Cache-Control": cache,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": _policy(content),
    }
    if content.partial:
        headers["Content-Range"] = f"bytes {content.start}-{content.end}/{content.size}"
    return StreamingResponse(
        content.body,
        status_code=status.HTTP_206_PARTIAL_CONTENT if content.partial else status.HTTP_200_OK,
        media_type=content.content_type,
        headers=headers,
    )


@router.get(
    "/content/{token}",
    response_class=StreamingResponse,
    responses={410: {"model": ProblemDetail, "description": "The link expired."}},
)
async def file_content(  # noqa: PLR0913 - the link, the reader and the audit note
    *,
    token: str,
    request: Request,
    session: TenantSession,
    subject: SignedIn,
    files: Files,
    note: Annotated[AuditNote, audited("file.downloaded", object_type="file")],
) -> StreamingResponse:
    """The file behind a link (checked again against your access); supports Range."""
    content = await access.open_by_link(
        session, files, subject, token, range_header=request.headers.get("range")
    )
    # Reads are audited for private-note files only (D-081 D7); public ones would be noise.
    note.skip = not content.private
    note.object_id = str(content.file_id)
    return _stream(content, cache="private, no-store")


async def _image(
    session: TenantSession,
    files: FileServices,
    subject: Actor,
    file_id: uuid.UUID,
    *,
    thumbnail: bool,
) -> StreamingResponse:
    content = await access.open_image(session, files, subject, file_id, thumbnail=thumbnail)
    return _stream(content, cache="private, max-age=300")


@router.get("/{file_id}/inline", response_class=StreamingResponse)
async def inline_image(
    file_id: uuid.UUID, session: TenantSession, subject: SignedIn, files: Files
) -> StreamingResponse:
    """An image shown inside a reply or note (signed-in users who may see it; clean only)."""
    return await _image(session, files, subject, file_id, thumbnail=False)


@router.get("/{file_id}/thumbnail", response_class=StreamingResponse)
async def thumbnail(
    file_id: uuid.UUID, session: TenantSession, subject: SignedIn, files: Files
) -> StreamingResponse:
    """The 320 px preview of an image."""
    return await _image(session, files, subject, file_id, thumbnail=True)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: uuid.UUID,
    session: TenantSession,
    subject: SignedIn,
    note: Annotated[AuditNote, audited("file.deleted", object_type="file", object_param="file_id")],
) -> Response:
    """Remove an attachment (its bytes are deleted after 24 hours)."""
    found = await access.remove(session, subject, file_id)
    note.details = {"owner_type": found.link.owner_type}
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{file_id}/rescan")
async def rescan(
    file_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    files: Files,
    note: Annotated[
        AuditNote, audited("file.rescan_requested", object_type="file", object_param="file_id")
    ],
) -> FileOut:
    """Check again a file that could not be checked (or was not scanned)."""
    del note
    found = await access.authorize(session, subject, file_id, Action.VIEW)
    if not await scanning.rescan(session, file_id):
        raise ValidationFailed(code="file_not_rescannable", params={"state": found.file.state})
    return _out(found.file, found.link, files)


# --- rules, usage, scanning status -----------------------------------------------------------


class RulesOut(BaseModel):
    """The tenant's file rules (everyone needs them before uploading)."""

    max_file_mb: int
    max_batch: int
    blocked_extensions: list[str]
    version: int


@router.get("/settings/rules")
async def get_rules(response: Response, session: TenantSession, subject: SignedIn) -> RulesOut:
    """Size limit, batch size and blocked types (the upload screen refuses early, AC2)."""
    del subject
    found = await rules(session)
    set_etag(response, found.version)
    return RulesOut(
        max_file_mb=found.max_file_mb,
        max_batch=found.max_batch,
        blocked_extensions=found.blocked,
        version=found.version,
    )


class RulesIn(BaseModel):
    """New rules (D-081 D7: up to 100 MB per file)."""

    max_file_mb: int = Field(ge=1, le=100)
    max_batch: int = Field(ge=1, le=50)
    blocked_extensions: list[str] = Field(max_length=200)


@router.put("/settings/rules")
async def put_rules(  # noqa: PLR0913 - the change, its version and the audit note
    *,
    body: RulesIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
    note: Annotated[AuditNote, audited("file_settings.changed", object_type="file_settings")],
) -> RulesOut:
    """Change the rules (If-Match; "0" before the first change). Audited with what changed."""
    del subject
    before = await rules(session)
    saved = await admin.update_rules(
        session,
        max_file_mb=body.max_file_mb,
        max_batch=body.max_batch,
        blocked=body.blocked_extensions,
        expected_version=version,
    )
    note.details = {
        "max_file_mb": {"old": before.max_file_mb, "new": saved.max_file_mb},
        "max_batch": {"old": before.max_batch, "new": saved.max_batch},
        "blocked_added": sorted(set(saved.blocked) - set(before.blocked)),
        "blocked_removed": sorted(set(before.blocked) - set(saved.blocked)),
    }
    set_etag(response, saved.version)
    return RulesOut(
        max_file_mb=saved.max_file_mb,
        max_batch=saved.max_batch,
        blocked_extensions=saved.blocked,
        version=saved.version,
    )


class UsageOut(BaseModel):
    """Stored bytes and files against the plan's limit (None = unlimited)."""

    bytes_used: int
    files: int
    limit_bytes: int | None


@router.get("/settings/usage")
async def get_usage(session: TenantSession, subject: Manage) -> UsageOut:
    """How much of the storage limit is used."""
    del subject
    found = await admin.storage_usage(session)
    return UsageOut(bytes_used=found.bytes_used, files=found.files, limit_bytes=found.limit_bytes)


class StatusOut(BaseModel):
    """Whether files are being checked for malware, and what needs an administrator."""

    scanner_installed: bool
    scanner_reachable: bool
    scan_required: bool
    signature_date: datetime | None
    signatures_stale: bool
    waiting: int
    failed: int
    not_scanned: int
    warnings: list[
        Literal[
            "scanner_not_installed",
            "scanner_unreachable",
            "signatures_stale",
            "files_not_scanned",
            "files_scan_failed",
        ]
    ]


@router.get("/settings/status")
async def get_status(session: TenantSession, subject: Manage, files: Files) -> StatusOut:
    """Scanning status for Admin > Files and the administrators' banner."""
    del subject
    found = await admin.scanning_status(session, files)
    return StatusOut.model_validate(found, from_attributes=True)
