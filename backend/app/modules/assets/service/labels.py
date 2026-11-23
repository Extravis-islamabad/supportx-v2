"""Asset labels: QR codes and Code 128 barcodes, printed as one PDF (REQ-AST-039; D-141).

1. The API checks the request and records it: every asset on it must be one the person may see
   (`assets.view`, scoped: 404 otherwise, never a hint), or the vendor codes typed. At most 500
   labels per job. It writes the job, the print row (append-only, AC3: who, when, what, layout,
   job) and `assets.label.requested` in one transaction (503 without object storage).
2. The consumers worker rebuilds the person's permissions, drops nothing silently (an asset they
   can no longer see fails the job), renders the PDF with the shared renderer (worker image
   only, D-100 D8), stores it and marks the job ready, or failed with a problem code.
   `assets.label.printed` tells the person live.
3. The person who asked downloads it, signed in, for a week. A reprint is a new job and a new
   print row naming the job it repeats.

A QR code holds only the console link to the asset (domain/labels.py, AC2).
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, Conflict, NotFound
from app.core.logging import get_logger
from app.modules.assets.domain.catalogue import Problem
from app.modules.assets.domain.labels import (
    LABELS_MAX,
    LINK_DAYS,
    Label,
    LabelJobStatus,
    LabelLayout,
    LabelTarget,
    Symbology,
    asset_label,
    clean_codes,
    vendor_label,
)
from app.modules.assets.events import LabelPrinted, LabelRequested
from app.modules.assets.infra.models import Asset, AssetLabelJob, AssetLabelPrint
from app.modules.assets.service.assets import ASSETS, VIEW, _refuse, _require, _tenant
from app.modules.identity_access import Subject, scope_filter, subject_for
from app.modules.organization import email_branding
from app.shared.events import EventEnvelope, record_event
from app.shared.ids import new_id
from app.shared.pdf import PdfTooLarge
from app.shared.storage import (
    ObjectStorage,
    StorageNotConfigured,
    StorageUnavailable,
    storage_from,
)

log = get_logger(__name__)
CONTENT_TYPE = "application/pdf"
LANGUAGES = ("en", "ar", "ur")
JOBS_LISTED = 20
PRINTS_LISTED = 100
# Renders the labels' PDF; only the worker image has one (D-100 D8). Tests set their own.
LabelRenderer = Callable[..., bytes]
_state: dict[str, Any] = {}


def set_label_renderer(renderer: LabelRenderer | None) -> None:
    """The label renderer of this process (worker image only), or None."""
    _state["render"] = renderer


def label_renderer() -> LabelRenderer | None:
    """The renderer, found once: the shared PDF renderer where WeasyPrint loads."""
    if "render" not in _state:
        from app.modules.assets.infra import labels as pdf_labels  # noqa: PLC0415 - first job
        from app.shared import pdf  # noqa: PLC0415

        _state["render"] = pdf_labels.render_labels if pdf.available() else None
    found: LabelRenderer | None = _state["render"]
    return found


@dataclass(frozen=True, slots=True)
class LabelRequest:
    """What the person asked to print."""

    target: LabelTarget
    layout: LabelLayout
    symbology: Symbology
    language: str
    asset_ids: Sequence[uuid.UUID] = ()
    codes: Sequence[str] = ()


async def _visible_ids(
    session: AsyncSession, subject: Subject, asset_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    found = await session.scalars(
        select(Asset.id).where(
            Asset.id.in_(asset_ids),
            Asset.deleted_at.is_(None),
            scope_filter(subject, VIEW, ASSETS),
        )
    )
    return set(found)


async def _checked(
    session: AsyncSession, subject: Subject, request: LabelRequest
) -> tuple[list[uuid.UUID], list[str]]:
    """The assets (each one the person may see) or the vendor codes to print."""
    if request.language not in LANGUAGES:
        _refuse([Problem("language", "invalid_choice")])
    if request.target is LabelTarget.VENDOR_CODE:
        codes, code = clean_codes(list(request.codes))
        if code is not None:
            params = (("max", LABELS_MAX),) if code == "too_many" else ()
            _refuse([Problem("codes", code, params)])
        return [], codes
    ids = list(dict.fromkeys(request.asset_ids))
    if not ids:
        _refuse([Problem("asset_ids", "required")])
    if len(ids) > LABELS_MAX:
        _refuse([Problem("asset_ids", "too_many", (("max", LABELS_MAX),))])
    if len(await _visible_ids(session, subject, ids)) != len(ids):
        # One the person may not see (or that is gone): the whole job is refused, naming none.
        raise NotFound(code="asset_not_found")
    return ids, []


async def _new_job(  # noqa: PLR0913 - the request, what it prints, and whether it repeats one
    session: AsyncSession,
    subject: Subject,
    request: LabelRequest,
    asset_ids: list[uuid.UUID],
    codes: list[str],
    *,
    reprint_of: uuid.UUID | None,
) -> AssetLabelJob:
    tenant = _tenant(session)
    count = len(asset_ids) or len(codes)
    job = AssetLabelJob(
        id=new_id(),
        tenant_id=tenant,
        created_by=subject.user_id,
        requested_by=subject.user_id,
        target=request.target.value,
        layout=request.layout.value,
        symbology=request.symbology.value,
        language=request.language,
        asset_ids=asset_ids,
        codes=codes,
        item_count=count,
        reprint_of=reprint_of,
    )
    session.add(job)
    await session.flush()
    session.add(
        AssetLabelPrint(
            id=new_id(),
            tenant_id=tenant,
            created_by=subject.user_id,
            job_id=job.id,
            target=job.target,
            layout=job.layout,
            symbology=job.symbology,
            asset_ids=asset_ids,
            codes=codes,
            item_count=count,
            reprint=reprint_of is not None,
        )
    )
    await session.flush()
    await record_event(
        session,
        LabelRequested(job_id=job.id, requested_by=subject.user_id),
        aggregate_id=job.id,
        aggregate_version=job.version,
    )
    return job


async def request_labels(
    session: AsyncSession, subject: Subject, request: LabelRequest, *, storage_ready: bool
) -> AssetLabelJob:
    """Record the request (job, print row, event); the worker builds the PDF."""
    _require(subject, VIEW)
    if not storage_ready:
        raise StorageNotConfigured
    asset_ids, codes = await _checked(session, subject, request)
    return await _new_job(session, subject, request, asset_ids, codes, reprint_of=None)


async def _own_job(session: AsyncSession, subject: Subject, job_id: uuid.UUID) -> AssetLabelJob:
    job = await session.scalar(
        select(AssetLabelJob).where(
            AssetLabelJob.id == job_id, AssetLabelJob.requested_by == subject.user_id
        )
    )
    if job is None:
        raise NotFound(code="asset_label_job_not_found")
    return job


async def reprint(
    session: AsyncSession, subject: Subject, print_id: uuid.UUID, *, storage_ready: bool
) -> AssetLabelJob:
    """The same labels again (AC3): a new job and print row, checked as a new request."""
    _require(subject, VIEW)
    if not storage_ready:
        raise StorageNotConfigured
    row = await session.get(AssetLabelPrint, print_id)
    if row is None:
        raise NotFound(code="asset_label_print_not_found")
    job = await session.get(AssetLabelJob, row.job_id)
    assert job is not None  # noqa: S101 - a foreign key holds it
    request = LabelRequest(
        target=LabelTarget(row.target),
        layout=LabelLayout(row.layout),
        symbology=Symbology(row.symbology),
        language=job.language,
        asset_ids=list(row.asset_ids),
        codes=list(row.codes),
    )
    asset_ids, codes = await _checked(session, subject, request)
    return await _new_job(session, subject, request, asset_ids, codes, reprint_of=job.id)


async def my_jobs(session: AsyncSession, subject: Subject) -> list[AssetLabelJob]:
    """The person's recent label jobs, newest first."""
    _require(subject, VIEW)
    return list(
        await session.scalars(
            select(AssetLabelJob)
            .where(AssetLabelJob.requested_by == subject.user_id)
            .order_by(AssetLabelJob.created_at.desc())
            .limit(JOBS_LISTED)
        )
    )


async def download(session: AsyncSession, subject: Subject, job_id: uuid.UUID) -> AssetLabelJob:
    """The person's ready job (404 not theirs, 409 not ready or expired)."""
    _require(subject, VIEW)
    job = await _own_job(session, subject, job_id)
    expired = job.expires_at is not None and job.expires_at < datetime.now(UTC)
    if job.status != LabelJobStatus.READY or job.object_key is None or expired:
        status = "expired" if expired else job.status
        raise Conflict(code="asset_label_job_not_ready", params={"status": status})
    return job


@dataclass(frozen=True, slots=True)
class PrintView:
    """One print row as the history shows it: only the assets the reader may see."""

    row: AssetLabelPrint
    asset_ids: list[uuid.UUID]


async def prints(
    session: AsyncSession, subject: Subject, *, asset_id: uuid.UUID | None = None
) -> list[PrintView]:
    """The label history, newest first; for one asset when `asset_id` is given (AC3)."""
    _require(subject, VIEW)
    statement = select(AssetLabelPrint)
    if asset_id is not None:
        if not await _visible_ids(session, subject, [asset_id]):
            raise NotFound(code="asset_not_found")
        statement = statement.where(AssetLabelPrint.asset_ids.contains([asset_id]))
    rows = list(
        await session.scalars(
            statement.order_by(AssetLabelPrint.created_at.desc(), AssetLabelPrint.id.desc()).limit(
                PRINTS_LISTED
            )
        )
    )
    every = sorted({a for r in rows for a in r.asset_ids})
    visible = await _visible_ids(session, subject, every) if every else set()
    return [PrintView(r, [a for a in r.asset_ids if a in visible]) for r in rows]


# --- the worker -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelWorker:
    """What the consumers worker gives every job."""

    storage: ObjectStorage | None
    render: LabelRenderer | None
    settings: Settings


async def _labels(
    session: AsyncSession, job: AssetLabelJob, subject: Subject, settings: Settings
) -> list[Label] | str:
    if job.target == LabelTarget.VENDOR_CODE:
        return [vendor_label(code) for code in job.codes]
    visible = await _visible_ids(session, subject, job.asset_ids)
    if len(visible) != len(job.asset_ids):
        return "asset_not_found"  # the person can no longer see one of them
    rows = {
        r.id: r for r in await session.scalars(select(Asset).where(Asset.id.in_(job.asset_ids)))
    }
    brand = await email_branding(session, settings, job.tenant_id, job.language)
    symbology = Symbology(job.symbology)
    return [
        asset_label(brand.console_url, a, tag=rows[a].tag, name=rows[a].name, symbology=symbology)
        for a in job.asset_ids
    ]


async def _finish(session: AsyncSession, job: AssetLabelJob, problem: str | None) -> None:
    if problem is not None:
        job.status = LabelJobStatus.FAILED
        job.problem = problem
        job.finished_at = datetime.now(UTC)
    job.version += 1
    await session.flush()
    await record_event(
        session,
        LabelPrinted(
            job_id=job.id,
            requested_by=job.requested_by,
            status="failed" if job.status == LabelJobStatus.FAILED else "ready",
            problem=job.problem,
        ),
        aggregate_id=job.id,
        aggregate_version=job.version,
    )


async def _render(
    session: AsyncSession, job: AssetLabelJob, worker: LabelWorker
) -> tuple[bytes, int] | str:
    """The PDF and its label count, or the problem code that stops the job."""
    if worker.render is None:
        return "pdf_not_available"
    try:
        subject = await subject_for(session, job.tenant_id, job.requested_by)
    except AppError as error:
        log.error("asset_label_subject_unavailable", code=error.code)  # noqa: TRY400 - code only
        return "asset_labels_failed"
    if not subject.holds(VIEW):
        return "asset_not_found"
    labels = await _labels(session, job, subject, worker.settings)
    if isinstance(labels, str):
        return labels
    try:
        data = worker.render(
            labels,
            layout=LabelLayout(job.layout),
            symbology=Symbology(job.symbology),
            language=job.language,
        )
    except PdfTooLarge:
        return "asset_labels_too_large"
    return data, len(labels)


async def build_labels(session: AsyncSession, job_id: uuid.UUID, worker: LabelWorker) -> None:
    """Render, store and mark the job ready, or failed with a reason (never silent)."""
    job = await session.get(AssetLabelJob, job_id, with_for_update=True)
    if job is None or job.status != LabelJobStatus.RUNNING:
        return
    if worker.storage is None:
        await _finish(session, job, "storage_not_configured")
        return
    rendered = await _render(session, job, worker)
    if isinstance(rendered, str):
        await _finish(session, job, rendered)
        return
    data, count = rendered
    key = f"assets/labels/{job.tenant_id}/{job.id}.pdf"
    try:
        await worker.storage.put(key, data, CONTENT_TYPE)
    except StorageUnavailable:
        log.exception("asset_label_storage_failed", job_id=str(job.id))
        await _finish(session, job, "storage_unavailable")
        return
    job.status = LabelJobStatus.READY
    job.object_key = key
    job.size_bytes = len(data)
    job.pages = count  # one label per page
    job.done = count
    job.finished_at = datetime.now(UTC)
    job.expires_at = job.finished_at + timedelta(days=LINK_DAYS)
    await _finish(session, job, None)


async def fail_stalled(session: AsyncSession, older_than: datetime) -> int:
    """Jobs still running since before `older_than` failed: their worker crashed or gave up."""
    rows = list(
        await session.scalars(
            select(AssetLabelJob)
            .where(
                AssetLabelJob.status == LabelJobStatus.RUNNING,
                AssetLabelJob.created_at < older_than,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        await _finish(session, row, "asset_labels_failed")
    return len(rows)


def _storage(settings: Settings) -> ObjectStorage | None:
    if "storage" in _state:  # tests put a store in memory here
        injected: ObjectStorage | None = _state["storage"]
        return injected
    try:
        return storage_from(settings)
    except StorageNotConfigured:
        return None


def set_label_storage(storage: ObjectStorage | None) -> None:
    """The object store the worker and downloads use (tests: one in memory); None: configured."""
    if storage is None:
        _state.pop("storage", None)
    else:
        _state["storage"] = storage


def label_storage(settings: Settings) -> ObjectStorage | None:
    """The object store for label files, or None (requests then refuse with 503)."""
    return _storage(settings)


async def on_label_requested(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: build one requested label PDF."""
    assert session is not None  # noqa: S101 - transactional consumer
    from app.core.config import get_settings  # noqa: PLC0415 - the worker's own settings

    settings = get_settings()
    worker = LabelWorker(storage=_storage(settings), render=label_renderer(), settings=settings)
    await build_labels(session, uuid.UUID(str(envelope.payload["job_id"])), worker)
