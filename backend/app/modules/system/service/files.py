"""The files platform service in the running system (WP-022, ADR-028 item 5).

Shared code (`app/shared/files`) cannot reach modules, so the `system` module plugs it in:

- the scan consumer and the schedules (scan sweep, purge, scanner check) for the worker;
- the storage quota from the entitlement interface (`storage_gb`, D-082 D6);
- audit entries for what the worker does (a blocked file, a purge);
- realtime: a file change reaches the record's channel (or, for an editor draft, the uploader's
  personal channel) with the file ID only; screens refetch through the API.
"""

import uuid
from datetime import UTC, datetime

from fastapi import Request
from opentelemetry import metrics
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit import WORKER, record
from app.modules.licensing import LimitKey, check_limit
from app.shared.events import EventEnvelope
from app.shared.files.domain.states import FileState
from app.shared.files.events import FileChanged, FileUploaded
from app.shared.files.infra.models import TenantStorageUsage
from app.shared.files.infra.scanner import ScannerUnavailableError
from app.shared.files.ports import record_channel_kind
from app.shared.files.service import cleanup, scanning
from app.shared.files.service.core import GB, FileServices
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, personal
from app.shared.realtime import record as record_channel

log = get_logger(__name__)
_meter = metrics.get_meter("supportx.files")
_scanner_problems = _meter.create_counter(
    "supportx_files_scanner_problems",
    description="Scanner checks that found no scanner, an unreachable one or stale signatures",
)
_blocked = _meter.create_counter("supportx_files_blocked", description="Files blocked as malware")

RECORD_KIND = "wi"  # fallback: the work item record channel (work_items owns it)
FILES_CHANGED = "files.changed"


FILES_STATE = "files"
_worker_services: list[FileServices] = []


def services() -> FileServices:
    """The worker's file services, from settings (once per process; tests may replace them)."""
    if not _worker_services:
        _worker_services.append(FileServices.from_settings(get_settings()))
    return _worker_services[0]


def use_services(replacement: FileServices | None) -> None:
    """Replace the worker's file services (tests), or go back to the settings (None)."""
    _worker_services[:] = [] if replacement is None else [replacement]


def api_services(request: Request) -> FileServices:
    """The API process's file services (set at startup; tests swap `app.state.files`)."""
    found: FileServices | None = getattr(request.app.state, FILES_STATE, None)
    if found is None:
        found = FileServices.from_settings(request.app.state.settings)
        setattr(request.app.state, FILES_STATE, found)
    return found


# --- quota ---------------------------------------------------------------------------------------


async def storage_limit_bytes(session: AsyncSession) -> int | None:
    """The tenant's `storage_gb` limit in bytes (None = unlimited)."""
    check = await check_limit(session, LimitKey.STORAGE_GB, adding=0)
    return None if check.limit is None else check.limit * GB


async def storage_gb_used(session: AsyncSession) -> int:
    """Usage counter for the licence summary: whole GB stored, rounded up."""
    used = await session.scalar(select(func.coalesce(func.max(TenantStorageUsage.bytes_used), 0)))
    return -(-int(used or 0) // GB)


# --- worker --------------------------------------------------------------------------------------


async def on_file_uploaded(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: scan a new file (and write the audit entry when it is blocked)."""
    assert session is not None  # noqa: S101 - transactional consumer
    file_id = uuid.UUID(str(envelope.payload["file_id"]))
    outcome = await scanning.scan(session, services(), file_id)
    if outcome.state == FileState.INFECTED:
        _blocked.add(1)
        await record(
            session,
            action_code="file.blocked",
            facts=WORKER,
            object_type="file",
            object_id=file_id,
            details={"signature": outcome.signature or "unknown"},
        )


async def _tenant_ids(database: Database) -> list[uuid.UUID]:
    # Every tenant; the audit migration's definer function lists them for platform jobs.
    async with database.platform_session() as session:
        return list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())


async def scan_sweep(database: Database, settings: Settings) -> None:
    """Schedule: scan files still waiting (scanner was down, or installed after the upload)."""
    del settings
    for tenant in await _tenant_ids(database):
        async with database.tenant_session(TenantContext(tenant)) as session:
            waiting = await scanning.waiting(session)
        for file_id in waiting:
            try:
                await _scan_one(database, tenant, file_id)
            except Exception:  # one broken file must not stop the others; it is logged
                log.exception("file_scan_sweep_error", file_id=str(file_id))


async def _scan_one(database: Database, tenant: uuid.UUID, file_id: uuid.UUID) -> None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        outcome = await scanning.scan(session, services(), file_id)
        if outcome.state == FileState.INFECTED:
            _blocked.add(1)
            await record(
                session,
                action_code="file.blocked",
                facts=WORKER,
                object_type="file",
                object_id=file_id,
                details={"signature": outcome.signature or "unknown"},
            )


async def purge(database: Database, settings: Settings) -> None:
    """Schedule: remove deleted files after their grace period, and unsaved editor drafts."""
    del settings
    for tenant in await _tenant_ids(database):
        async with database.tenant_session(TenantContext(tenant)) as session:
            result = await cleanup.purge_due(session, services())
            if result.files:
                await record(
                    session,
                    action_code="file.purged",
                    facts=WORKER,
                    object_type="file",
                    details={"files": result.files, "bytes": result.bytes},
                )


async def check_scanner(database: Database, settings: Settings) -> None:
    """Schedule: no scanner, unreachable, or signatures too old: log an error and count it.

    Administrators see the same facts in Admin > Files; operations get the metric alert.
    """
    del database
    found = services()
    if not found.scanner.available:
        if settings.files_scan_required:
            _scanner_problems.add(1, {"problem": "not_installed"})
            log.error("files_scanner_not_installed", scan_required=True)
        return
    try:
        version = await found.scanner.version()
    except ScannerUnavailableError:
        _scanner_problems.add(1, {"problem": "unreachable"})
        log.error("files_scanner_unreachable")  # noqa: TRY400 - the outage, not a trace
        return
    date = version.signature_date
    if date is not None and datetime.now(UTC) - date > found.signature_max_age:
        _scanner_problems.add(1, {"problem": "stale"})
        log.error("files_signatures_stale", signature_date=date.isoformat())


# --- realtime ------------------------------------------------------------------------------------


async def _file_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    payload = envelope.payload
    file_id = str(payload["file_id"])
    record_id = payload.get("record_id")
    if record_id is not None:
        # The record's own channel (an article's, an incident's); events from before record
        # types were declared, and channel-less records, keep the work item channel.
        kind = record_channel_kind(payload.get("record_type")) or RECORD_KIND
        channel = record_channel(envelope.tenant_id, kind, uuid.UUID(str(record_id)))
    else:  # an editor draft: only its uploader's screens care
        channel = personal(envelope.tenant_id, uuid.UUID(str(payload["owner_id"])))
    return RealtimeEffects(publications=[Publication(channel, FILES_CHANGED, ids=(file_id,))])


REALTIME = [RealtimeRoute((FileUploaded.event_type, FileChanged.event_type), _file_changed)]
