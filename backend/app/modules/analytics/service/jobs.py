"""Worker side of report exports (consumers worker; WP-035, D-100).

The consumer builds one export per `analytics.report_export.requested` event. What it needs from
the process is wired here once: the reporting pool, object storage, the subject loader
(identity_access.subject_for, so the worker applies exactly the API's permissions) and, in the
worker image only, the PDF renderer (D-100 D8: WeasyPrint never in the API image).
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.modules.analytics.service.exports import (
    PdfRenderer,
    SubjectLoader,
    Worker,
    build_export,
    expire_exports,
)
from app.modules.analytics.service.settings import limits_of, tenant_settings
from app.shared.events import EventEnvelope
from app.shared.storage import ObjectStorage, StorageNotConfigured, storage_from

_state: dict[str, Any] = {}


def set_subject_loader(loader: SubjectLoader | None) -> None:
    """The function that rebuilds a user's permissions in the worker (set at module import)."""
    _state["subject_loader"] = loader


def set_pdf_renderer(renderer: PdfRenderer | None) -> None:
    """The PDF renderer of this process (worker image only), or None."""
    _state["pdf"] = renderer


def _pdf_renderer() -> PdfRenderer | None:
    if "pdf" not in _state:
        # Only the worker image installs the `pdf` dependency group (D-100 D8).
        from app.modules.analytics.infra import pdf  # noqa: PLC0415 - loaded once, on first export

        _state["pdf"] = pdf.render_pdf if pdf.available() else None
    renderer: PdfRenderer | None = _state["pdf"]
    return renderer


def _reporting(settings: Settings) -> Database | None:
    if "reporting" not in _state:
        _state["reporting"] = Database.reporting_from_settings(settings)
    database: Database | None = _state["reporting"]
    return database


def storage_or_none(settings: Settings) -> ObjectStorage | None:
    """The configured object store, or None (exports then fail visibly)."""
    try:
        return storage_from(settings)
    except StorageNotConfigured:
        return None


async def on_export_requested(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: build one requested export."""
    assert session is not None  # noqa: S101 - transactional consumer
    from app.core.config import get_settings  # noqa: PLC0415 - the worker's own settings

    settings = get_settings()
    reporting = _reporting(settings)
    loader: SubjectLoader | None = _state.get("subject_loader")
    if reporting is None or loader is None:  # pragma: no cover - a misconfigured worker
        msg = "report exports need the reporting database and the subject loader"
        raise RuntimeError(msg)
    limits = limits_of(await tenant_settings(session), settings)
    storage = storage_or_none(settings)
    # Housekeeping rides along: each export first removes the tenant's expired files. Downloads
    # refuse anything past its expiry anyway, so a file left over is never served.
    await expire_exports(session, storage)
    await build_export(
        session,
        uuid.UUID(str(envelope.payload["export_id"])),
        Worker(
            reporting=reporting,
            storage=storage,
            load_subject=loader,
            render_pdf=_pdf_renderer(),
            timeout_seconds=settings.report_background_timeout_seconds,
            max_rows=limits.max_export_rows,
            link_days=limits.export_link_days,
            week_start=limits.week_start,
        ),
    )
