"""Retention of the audit log (D-076 items 4 and 10; ADR-027).

Mixed approach:

1. Whole months past the tenant's retention (3 years by default) are written to object storage
   as an archive (`audit/archive/<tenant>/<yyyy-mm>.zip`, the export format with the offline
   verifier), read back and verified. Only then
2. `audit_advance_cutoff()` moves the tenant's cut-off: RLS hides the entries before it from
   every app query, and their personal rows are deleted (archives hold no personal data: it is
   not kept past retention, REQ-AUD-013).
3. `audit_drop_expired_partitions()` drops a monthly partition once every tenant's cut-off is
   past it.

An archive covers a contiguous run of chain positions, from the end of the previous archive to
the last position of an entry inside the month, so archives and the live chain together stay
one verifiable chain. Positions follow sealing order, which trails occurrence by seconds, so an
archive can also hold a few entries from just after the month: they stay visible until the next
month is archived and are verified inside the archive. A range that runs more than a day past
the month fails (`audit_archive_out_of_order`) instead of archiving live entries.

Never silent: missing or failing storage, unsealed entries or an archive that does not verify
after reading it back leave a `failed` archive row, an audit entry, an alert (banner,
`audit.alert.raised`), a metric and an error log; nothing is hidden then.

Restore for investigation: an archive can be copied back into `audit_restored` (verified again
on the way), browsable for 7 days, outside the live log and its chain.
"""

import hashlib
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from opentelemetry import metrics
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound
from app.core.logging import get_logger
from app.modules.audit.domain.catalogue import AuditActorType
from app.modules.audit.events import (
    AuditAlertRaised,
    AuditArchiveRestoreRequested,
    AuditArchiveUpdated,
)
from app.modules.audit.infra.models import (
    AuditArchive,
    AuditChainLink,
    AuditQueueItem,
    AuditRestored,
)
from app.modules.audit.infra.signing import AnchorSigner
from app.modules.audit.service.exports import Contents, bundle, chain_records
from app.modules.audit.service.recording import WORKER, record
from app.modules.audit.service.settings import load_settings
from app.modules.audit.tools.verify_export import Broken, records
from app.modules.audit.tools.verify_export import verify as verify_zip
from app.shared.clock import Clock, system_clock
from app.shared.events import record_event
from app.shared.ids import new_id
from app.shared.storage import ObjectStorage, StorageNotConfigured, StorageUnavailable

if TYPE_CHECKING:
    from app.core.tenancy import TenantContext

log = get_logger(__name__)
PREFIX = "audit/archive"
RESTORE_DAYS = 7
RESTORE_BATCH = 5000
SEAL_ORDER_SLACK = timedelta(days=1)

_meter = metrics.get_meter("supportx.audit")
_archive_failures = _meter.create_counter(
    "supportx_audit_archive_failures", description="Audit archives that could not be written"
)


def _tenant(session: AsyncSession) -> uuid.UUID:
    context: TenantContext = session.info[SESSION_TENANT_KEY]
    return context.tenant_id


def month_start(moment: datetime) -> datetime:
    """The first instant of `moment`'s month (UTC)."""
    moment = moment.astimezone(UTC)
    return datetime(moment.year, moment.month, 1, tzinfo=UTC)


def next_month(start: datetime) -> datetime:
    """The first instant of the following month."""
    return datetime(start.year + start.month // 12, start.month % 12 + 1, 1, tzinfo=UTC)


def archive_key(tenant_id: uuid.UUID, start: datetime) -> str:
    """Where a month's archive lives (one object per month: a retry overwrites it)."""
    return f"{PREFIX}/{tenant_id}/{start:%Y-%m}.zip"


def check_archive(payload: bytes, expected_sha256: str) -> str:
    """Verify an archive's bytes: the stored hash, then the full offline verification."""
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        msg = "the archive differs from what was written"
        raise Broken(msg)
    return verify_zip(io.BytesIO(payload))


async def _next_range(
    session: AsyncSession, horizon: datetime
) -> tuple[datetime, datetime, int] | None:
    """(from, to, last archived position) of the next month to archive, or None."""
    last_ready = await session.scalar(
        select(AuditArchive)
        .where(AuditArchive.status == "ready")
        .order_by(AuditArchive.range_to.desc())
        .limit(1)
    )
    after_seq = int(
        await session.scalar(
            select(func.max(AuditArchive.last_seq)).where(AuditArchive.status == "ready")
        )
        or 0
    )
    if last_ready is not None:
        start = last_ready.range_to
    else:
        oldest = await session.scalar(select(func.min(AuditChainLink.entry_occurred_at)))
        if oldest is None:
            return None
        start = month_start(oldest)
    end = next_month(start)
    return (start, end, after_seq) if end <= horizon else None


async def archive_next(  # noqa: PLR0911 - one return per way it can stop, in order
    session: AsyncSession,
    *,
    storage: ObjectStorage | None,
    signer: AnchorSigner | None,
    trusted_keys: dict[str, bytes],
    clock: Clock = system_clock,
) -> AuditArchive | None:
    """Archive the oldest month past retention, if there is one (one month per call)."""
    settings = await load_settings(session)
    found = await _next_range(session, clock.now() - timedelta(days=settings.retention_days))
    if found is None:
        return None
    start, end, after_seq = found
    tenant_id = _tenant(session)
    row = AuditArchive(
        id=new_id(), tenant_id=tenant_id, range_from=start, range_to=end, created_at=clock.now()
    )
    unsealed = await session.scalar(
        select(func.count()).select_from(AuditQueueItem).where(AuditQueueItem.occurred_at < end)
    )
    if unsealed:
        return await _failed(session, row, "audit_archive_unsealed")
    if storage is None:
        return await _failed(session, row, StorageNotConfigured.code)
    last_in_month = await session.scalar(
        select(func.max(AuditChainLink.seq)).where(
            AuditChainLink.seq > after_seq, AuditChainLink.entry_occurred_at < end
        )
    )
    # Positions follow sealing order, which trails occurrence by seconds. An entry far past the
    # month inside the range means the order is not what retention assumes: stop, visibly.
    latest = await session.scalar(
        select(func.max(AuditChainLink.entry_occurred_at)).where(
            AuditChainLink.seq > after_seq, AuditChainLink.seq <= (last_in_month or 0)
        )
    )
    if latest is not None and latest >= end + SEAL_ORDER_SLACK:
        return await _failed(session, row, "audit_archive_out_of_order")
    key = archive_key(tenant_id, start)
    try:
        items, first, last = await chain_records(
            session,
            select(AuditChainLink).where(
                AuditChainLink.seq > after_seq, AuditChainLink.seq <= (last_in_month or 0)
            ),
            {},
            personal=False,
        )
        payload = await bundle(
            session,
            Contents(
                kind="archive",
                id=row.id,
                format="jsonl",
                range_from=start,
                range_to=end,
                filters={},
                items=items,
                first_seq=first,
                last_seq=last,
            ),
            signer=signer,
            trusted_keys=trusted_keys,
            server_verification=None,
            clock=clock,
        )
        digest = hashlib.sha256(payload).hexdigest()
        await storage.put(key, payload, "application/zip")
        stored = await storage.get(key)
        if stored is None:
            return await _failed(session, row, "audit_archive_unverified")
        check_archive(stored, digest)
    except (StorageUnavailable, Conflict) as exc:
        log.exception("audit_archive_failed", tenant_id=str(tenant_id), month=f"{start:%Y-%m}")
        return await _failed(session, row, exc.instance_code)
    except Broken:
        log.exception("audit_archive_unverified", tenant_id=str(tenant_id), month=f"{start:%Y-%m}")
        return await _failed(session, row, "audit_archive_unverified")
    row.status = "ready"
    row.object_key = key
    row.entries = len(items)
    row.first_seq = first
    row.last_seq = last
    row.sha256 = digest
    session.add(row)
    await session.flush()
    await session.execute(text("SELECT audit_advance_cutoff(:before)"), {"before": end})
    await record(
        session,
        action_code="audit.entries_archived",
        facts=WORKER,
        object_type="audit_archive",
        object_id=row.id,
        details={
            "range_from": start,
            "range_to": end,
            "entries": row.entries,
            "first_seq": first,
            "last_seq": last,
            "sha256": digest,
        },
        actor=(AuditActorType.SYSTEM, None),
    )
    await record_event(
        session, AuditArchiveUpdated(archive_id=row.id, status="ready"), aggregate_id=row.id
    )
    log.info("audit_archived", tenant_id=str(tenant_id), month=f"{start:%Y-%m}", entries=len(items))
    return row


async def _failed(session: AsyncSession, row: AuditArchive, problem: str) -> AuditArchive:
    """Record the failure where people will see it; the entries stay in the live log."""
    row.status = "failed"
    row.problem = problem
    session.add(row)
    await session.flush()
    entry_id = await record(
        session,
        action_code="audit.archive_failed",
        facts=WORKER,
        reason_code=problem,
        object_type="audit_archive",
        object_id=row.id,
        details={"range_from": row.range_from, "range_to": row.range_to},
        actor=(AuditActorType.SYSTEM, None),
    )
    await record_event(
        session,
        AuditArchiveUpdated(archive_id=row.id, status="failed", problem=problem),
        aggregate_id=row.id,
    )
    await record_event(
        session, AuditAlertRaised(alert="archive_failed", entry_id=entry_id), aggregate_id=entry_id
    )
    _archive_failures.add(1, {"problem": problem})
    log.error(
        "audit_archive_failed",
        tenant_id=str(row.tenant_id),
        month=f"{row.range_from:%Y-%m}",
        problem=problem,
    )
    return row


async def drop_expired_partitions(session: AsyncSession) -> int:
    """Drop monthly partitions that every tenant's cut-off has passed (platform session)."""
    return int(await session.scalar(text("SELECT audit_drop_expired_partitions()")) or 0)


# --- reading archives and restoring them --------------------------------------------------------


async def list_archives(session: AsyncSession, limit: int = 120) -> list[AuditArchive]:
    """Newest month first (ten years of months by default)."""
    return list(
        await session.scalars(
            select(AuditArchive)
            .order_by(AuditArchive.range_from.desc(), AuditArchive.created_at.desc())
            .limit(limit)
        )
    )


async def request_restore(
    session: AsyncSession, archive_id: uuid.UUID, *, storage_ready: bool
) -> AuditArchive:
    """Ask the worker to restore an archive (404 unknown, 409 not ready, 503 no storage)."""
    if not storage_ready:
        raise StorageNotConfigured
    row = await session.get(AuditArchive, archive_id, with_for_update=True)
    if row is None:
        raise NotFound(code="audit_archive_not_found")
    if row.status != "ready":
        raise Conflict(code="audit_archive_not_ready", params={"status": row.status})
    if row.restore_status == "running":
        return row
    row.restore_status = "running"
    row.restore_problem = None
    await session.flush()
    await record_event(
        session, AuditArchiveRestoreRequested(archive_id=row.id), aggregate_id=row.id
    )
    return row


async def restore(
    session: AsyncSession,
    archive_id: uuid.UUID,
    storage: ObjectStorage | None,
    clock: Clock = system_clock,
) -> AuditArchive | None:
    """Read the archive back, verify it, and copy its entries into `audit_restored`."""
    row = await session.get(AuditArchive, archive_id, with_for_update=True)
    if row is None or row.restore_status != "running":
        return row
    problem: str | None = None
    payload: bytes | None = None
    if storage is None:
        problem = StorageNotConfigured.code
    else:
        try:
            payload = await storage.get(row.object_key or "")
            if payload is None:
                problem = "audit_archive_missing"
            else:
                check_archive(payload, row.sha256 or "")
        except StorageUnavailable as exc:
            problem = exc.instance_code
        except Broken:
            problem = "audit_archive_unverified"
    if problem is None and payload is not None:
        await _copy_in(session, row, payload, clock.now() + timedelta(days=RESTORE_DAYS))
        row.restore_status = "ready"
        row.restored_until = clock.now() + timedelta(days=RESTORE_DAYS)
    else:
        log.error("audit_restore_failed", archive_id=str(row.id), problem=problem)
        row.restore_status = "failed"
        row.restore_problem = problem
    await session.flush()
    await record_event(
        session,
        AuditArchiveUpdated(
            archive_id=row.id, status=row.status, restore_status=row.restore_status, problem=problem
        ),
        aggregate_id=row.id,
    )
    return row


async def _copy_in(
    session: AsyncSession, row: AuditArchive, payload: bytes, expires_at: datetime
) -> None:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        items = records(archive.read(manifest["data_file"]), manifest["format"])
    await session.execute(delete(AuditRestored).where(AuditRestored.archive_id == row.id))
    for start in range(0, len(items), RESTORE_BATCH):
        await session.execute(
            insert(AuditRestored),
            [
                {
                    "tenant_id": row.tenant_id,
                    "archive_id": row.id,
                    "seq": item["seq"],
                    "entry": item["entry"],
                    "entry_hash": bytes.fromhex(item["entry_hash"]),
                    "prev_hash": bytes.fromhex(item["prev_hash"]),
                    "chain_hash": bytes.fromhex(item["chain_hash"]),
                    "expires_at": expires_at,
                }
                for item in items[start : start + RESTORE_BATCH]
            ],
        )


async def restored_entries(
    session: AsyncSession, archive_id: uuid.UUID, *, after_seq: int, limit: int
) -> tuple[AuditArchive, list[AuditRestored]]:
    """A page of a restored archive in chain order (409 when it is not restored)."""
    row = await session.get(AuditArchive, archive_id)
    if row is None:
        raise NotFound(code="audit_archive_not_found")
    if row.restore_status != "ready":
        raise Conflict(code="audit_archive_not_restored")
    found = list(
        await session.scalars(
            select(AuditRestored)
            .where(AuditRestored.archive_id == archive_id, AuditRestored.seq > after_seq)
            .order_by(AuditRestored.seq)
            .limit(limit)
        )
    )
    return row, found


async def expire_restored(session: AsyncSession, clock: Clock = system_clock) -> int:
    """Remove restored copies past their 7 days; returns how many archives were cleared."""
    now = clock.now()
    await session.execute(delete(AuditRestored).where(AuditRestored.expires_at < now))
    result = await session.execute(
        update(AuditArchive)
        .where(AuditArchive.restore_status == "ready", AuditArchive.restored_until < now)
        .values(restore_status=None, restored_until=None)
    )
    return int(getattr(result, "rowcount", 0) or 0)
