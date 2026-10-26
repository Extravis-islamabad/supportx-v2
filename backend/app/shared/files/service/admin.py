"""Administering files: the tenant's rules, usage, and whether scanning works (D-081 D3, D7).

The scanning status is never silent: no scanner installed, scanner unreachable and signatures
older than the limit (7 days by default) each show as a warning to administrators, together with
how many files are waiting, could not be checked or were not scanned.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.shared.events import record_event
from app.shared.files.domain.states import FileState
from app.shared.files.domain.types import normalise_blocked
from app.shared.files.events import FileSettingsUpdated
from app.shared.files.infra.models import FileSettings, StoredFile
from app.shared.files.infra.scanner import ScannerUnavailableError
from app.shared.files.ports import storage_limit
from app.shared.files.service.core import (
    DEFAULT_RULES,
    FileServices,
    Rules,
    now,
    rules,
    tenant_of,
    usage,
)


async def update_rules(
    session: AsyncSession,
    *,
    max_file_mb: int,
    max_batch: int,
    blocked: list[str],
    expected_version: int,
) -> Rules:
    """Save the tenant's rules (If-Match: `expected_version`; 0 before the first save)."""
    current = await rules(session)
    if current.version != expected_version:
        raise Conflict(params={"current_version": current.version})
    clean = normalise_blocked(blocked)
    if current.version == 0:
        await session.execute(
            insert(FileSettings).values(
                tenant_id=tenant_of(session),
                version=1,
                max_file_mb=max_file_mb,
                max_batch=max_batch,
                blocked_extensions=clean,
            )
        )
    else:
        row = await session.scalar(select(FileSettings).with_for_update())
        assert row is not None  # noqa: S101 - version > 0 means the row exists
        row.max_file_mb, row.max_batch = max_file_mb, max_batch
        row.blocked_extensions = clean
        row.version += 1
    saved = await rules(session)
    await record_event(
        session, FileSettingsUpdated(version=saved.version), aggregate_id=tenant_of(session)
    )
    return saved


@dataclass(frozen=True)
class ScanningStatus:
    """Whether files are being checked, and what administrators must know."""

    scanner_installed: bool
    scanner_reachable: bool
    scan_required: bool
    signature_date: datetime | None
    signatures_stale: bool
    waiting: int
    failed: int
    not_scanned: int
    warnings: list[str]


async def scanning_status(session: AsyncSession, services: FileServices) -> ScanningStatus:
    """The scanner's state and the tenant's files that are not (yet) checked."""
    # A result has .keys(), so dict() would read it as a mapping: hand it a list of rows.
    counts: dict[str, int] = dict(
        list(
            await session.execute(
                select(StoredFile.state, func.count())
                .where(
                    StoredFile.state.in_(
                        [
                            FileState.SCANNING.value,
                            FileState.SCAN_FAILED.value,
                            FileState.NOT_SCANNED.value,
                        ]
                    )
                )
                .group_by(StoredFile.state)
            )
        )
    )
    installed = services.scanner.available
    reachable, date = False, None
    if installed:
        try:
            date = (await services.scanner.version()).signature_date
            reachable = True
        except ScannerUnavailableError:
            reachable = False
    stale = date is not None and now() - date > services.signature_max_age
    warnings = []
    if not installed:
        warnings.append("scanner_not_installed")
    elif not reachable:
        warnings.append("scanner_unreachable")
    if stale:
        warnings.append("signatures_stale")
    if counts.get(FileState.NOT_SCANNED.value):
        warnings.append("files_not_scanned")
    if counts.get(FileState.SCAN_FAILED.value):
        warnings.append("files_scan_failed")
    return ScanningStatus(
        scanner_installed=installed,
        scanner_reachable=reachable,
        scan_required=services.scan_required,
        signature_date=date,
        signatures_stale=stale,
        waiting=counts.get(FileState.SCANNING.value, 0),
        failed=counts.get(FileState.SCAN_FAILED.value, 0),
        not_scanned=counts.get(FileState.NOT_SCANNED.value, 0),
        warnings=warnings,
    )


@dataclass(frozen=True)
class Usage:
    """Stored bytes and files, and the tenant's limit (None = unlimited)."""

    bytes_used: int
    files: int
    limit_bytes: int | None


async def storage_usage(session: AsyncSession) -> Usage:
    """The tenant's storage use against its `storage_gb` limit."""
    used, files = await usage(session)
    return Usage(bytes_used=used, files=files, limit_bytes=await storage_limit(session))


__all__ = ["DEFAULT_RULES", "ScanningStatus", "Usage", "scanning_status", "storage_usage"]
