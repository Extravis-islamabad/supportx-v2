"""Sealing, anchoring and verifying the chain (REQ-AUD-001, REQ-AUD-010; ADR-027).

* `seal`: asks the database to seal the tenant's queued entries (`audit_seal()` computes the
  chain hashes itself; the app cannot write chain rows).
* `anchor`: signs the newest chain position with the installation key (`audit_anchors`).
* `verify`: recomputes entry hashes, chain links, personal-data commitments and anchors for a
  range, records the run, and on a problem writes an audit entry and raises an alert (banner in
  the console, `audit.alert.raised` for the notification engine, a metric for operations).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from opentelemetry import metrics
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.logging import get_logger
from app.modules.audit.domain.catalogue import AuditActorType, AuditOutcome
from app.modules.audit.domain.integrity import (
    ChainCheck,
    ChainLink,
    Finding,
    Problem,
    anchor_message,
    check_anchor,
    personal_rows,
)
from app.modules.audit.events import (
    AuditAlertRaised,
    AuditEntriesSealed,
    AuditVerificationCompleted,
)
from app.modules.audit.infra.models import (
    AuditAnchor,
    AuditChainLink,
    AuditEntry,
    AuditPersonal,
    AuditQueueItem,
    AuditVerificationRun,
)
from app.modules.audit.infra.signing import AnchorSigner, signature_valid
from app.modules.audit.service.recording import WORKER, record
from app.shared.clock import Clock, system_clock
from app.shared.events import record_event
from app.shared.ids import new_id

log = get_logger(__name__)
BATCH = 2000
DEFAULT_PARTITION = "audit_entries_default"

_meter = metrics.get_meter("supportx.audit")
_failures = _meter.create_counter(
    "supportx_audit_verification_failures", description="Audit chain verifications that failed"
)
_overdue = _meter.create_counter(
    "supportx_audit_unsealed_overdue", description="Audit entries found unsealed past the limit"
)

if TYPE_CHECKING:
    from app.core.tenancy import TenantContext


def _tenant(session: AsyncSession) -> uuid.UUID:
    context: TenantContext = session.info[SESSION_TENANT_KEY]
    return context.tenant_id


# --- sealing ------------------------------------------------------------------------------------


async def seal(session: AsyncSession, batch_size: int) -> int:
    """Seal every queued entry of the session's tenant (in batches). Returns how many."""
    before = await session.scalar(select(func.max(AuditChainLink.seq)))
    total = 0
    while True:
        sealed = int(await session.scalar(text("SELECT audit_seal(:n)"), {"n": batch_size}) or 0)
        total += sealed
        if sealed < batch_size:
            break
    if total:
        first = (before or 0) + 1
        await record_event(
            session,
            AuditEntriesSealed(from_seq=first, to_seq=first + total - 1),
            aggregate_id=_tenant(session),
        )
    return total


async def unsealed_overdue(session: AsyncSession, older_than: timedelta, clock: Clock) -> int:
    """Entries still waiting to be sealed after `older_than` (the sealer is down or stuck)."""
    cutoff = clock.now() - older_than
    count = await session.scalar(
        select(func.count()).select_from(AuditQueueItem).where(AuditQueueItem.occurred_at < cutoff)
    )
    return int(count or 0)


# --- anchoring ----------------------------------------------------------------------------------


async def anchor(
    session: AsyncSession, signer: AnchorSigner, *, every: timedelta, clock: Clock = system_clock
) -> AuditAnchor | None:
    """Sign the newest chain position if it moved and the last anchor is older than `every`."""
    newest = await session.scalar(
        select(AuditChainLink).order_by(AuditChainLink.seq.desc()).limit(1)
    )
    if newest is None:
        return None
    last = await session.scalar(select(AuditAnchor).order_by(AuditAnchor.seq.desc()).limit(1))
    now = clock.now()
    if last is not None and (last.seq >= newest.seq or now - last.created_at < every):
        return None
    tenant_id = _tenant(session)
    row = AuditAnchor(
        tenant_id=tenant_id,
        seq=newest.seq,
        chain_hash=newest.chain_hash,
        created_at=now,
        key_id=signer.key_id,
        public_key=signer.public_key,
        signature=signer.sign(anchor_message(tenant_id, newest.seq, newest.chain_hash, now)),
    )
    session.add(row)
    await session.flush()
    return row


# --- verification -------------------------------------------------------------------------------


@dataclass(frozen=True)
class VerificationResult:
    """The outcome of one run."""

    run_id: uuid.UUID
    status: str  # passed | failed
    entries_checked: int
    finding: Finding | None
    unsealed_overdue: int
    first_seq: int | None
    last_seq: int | None


async def _seq_bounds(
    session: AsyncSession, range_from: datetime | None, range_to: datetime | None
) -> tuple[int | None, int | None]:
    query = select(func.min(AuditChainLink.seq), func.max(AuditChainLink.seq))
    if range_from is not None:
        query = query.where(AuditChainLink.entry_occurred_at >= range_from)
    if range_to is not None:
        query = query.where(AuditChainLink.entry_occurred_at < range_to)
    low, high = (await session.execute(query)).one()
    return low, high


async def _links(
    session: AsyncSession, start: int, end: int
) -> list[tuple[AuditChainLink, dict[str, Any] | None, dict[str, tuple[bytes, Any]]]]:
    chain = list(
        await session.scalars(
            select(AuditChainLink)
            .where(AuditChainLink.seq >= start, AuditChainLink.seq <= end)
            .order_by(AuditChainLink.seq)
        )
    )
    ids = [link.entry_id for link in chain]
    entries: dict[uuid.UUID, dict[str, Any]] = {}
    if ids:
        columns = AuditEntry.__table__.columns
        for row in (
            await session.execute(select(*columns).where(AuditEntry.id.in_(ids)))
        ).mappings():
            entries[row["id"]] = dict(row)
    personal: dict[uuid.UUID, list[tuple[uuid.UUID, bytes, Any]]] = {}
    if ids:
        for p in await session.scalars(
            select(AuditPersonal).where(AuditPersonal.entry_id.in_(ids))
        ):
            personal.setdefault(p.entry_id, []).append((p.subject_id, p.salt, p.data))
    return [
        (link, entries.get(link.entry_id), personal_rows(personal.get(link.entry_id, [])))
        for link in chain
    ]


async def _anchor_problem(
    session: AsyncSession,
    hashes: Mapping[int, bytes],
    first: int,
    last_seq: int,
    trusted: Mapping[str, bytes],
) -> tuple[AuditAnchor, Problem] | None:
    tenant_id = _tenant(session)
    for row in await session.scalars(
        select(AuditAnchor).where(AuditAnchor.seq >= first).order_by(AuditAnchor.seq)
    ):
        public = trusted.get(row.key_id)
        message = anchor_message(tenant_id, row.seq, row.chain_hash, row.created_at)
        if (
            public is None
            or public != row.public_key
            or not signature_valid(public, message, row.signature)
        ):
            return row, Problem.ANCHOR_SIGNATURE
        problem = check_anchor(hashes, row.seq, row.chain_hash, last_seq)
        if problem is not None:
            return row, problem
    return None


async def _walk(
    session: AsyncSession, tenant_id: uuid.UUID, first: int | None, last: int | None
) -> tuple[Finding | None, int, dict[int, bytes]]:
    """Check links `first`..`last` in batches; (first finding, links checked, seq → hash)."""
    hashes: dict[int, bytes] = {}
    if first is None or last is None:
        return None, 0, hashes
    check = ChainCheck.from_start(tenant_id)
    if first > 1:
        previous = await session.scalar(
            select(AuditChainLink.chain_hash).where(AuditChainLink.seq == first - 1)
        )
        if previous is None:
            return Finding(first - 1, None, Problem.SEQUENCE_GAP), 0, hashes
        check = ChainCheck(tenant_id, first, previous)
    start = first
    while start <= last:
        batch = await _links(session, start, min(start + BATCH - 1, last))
        if not batch:
            return Finding(start, None, Problem.SEQUENCE_GAP), check.checked, hashes
        for link, entry, personal in batch:
            hashes[link.seq] = link.chain_hash
            link_view = ChainLink(
                link.seq,
                link.entry_id,
                link.entry_hash,
                link.prev_hash,
                link.chain_hash,
                entry,
                personal,
            )
            if not check.feed(link_view):
                return check.finding, check.checked, hashes
        start = batch[-1][0].seq + 1
    if check.expected_seq <= last:
        return Finding(check.expected_seq, None, Problem.SEQUENCE_GAP), check.checked, hashes
    return None, check.checked, hashes


async def verify(  # noqa: PLR0913 - keyword-only run options
    session: AsyncSession,
    *,
    kind: str,
    trusted_keys: Mapping[str, bytes],
    range_from: datetime | None = None,
    range_to: datetime | None = None,
    requested_by: uuid.UUID | None = None,
    unsealed_limit: timedelta = timedelta(minutes=5),
    run_id: uuid.UUID | None = None,
    clock: Clock = system_clock,
) -> VerificationResult:
    """Verify the chain over a time range (None = everything) and record the run.

    `run_id` continues a run that was requested through the API (status `running`).
    """
    tenant_id = _tenant(session)
    run = (
        await session.get(AuditVerificationRun, run_id, with_for_update=True)
        if run_id is not None
        else None
    )
    if run is None:
        run = AuditVerificationRun(
            id=run_id or new_id(),
            tenant_id=tenant_id,
            kind=kind,
            status="running",
            range_from=range_from,
            range_to=range_to,
            requested_by=requested_by,
            started_at=clock.now(),
        )
        session.add(run)
        await session.flush()
    elif run.status != "running":
        return VerificationResult(run.id, run.status, run.entries_checked, None, 0, None, None)
    else:
        range_from, range_to = run.range_from, run.range_to

    first, last = await _seq_bounds(session, range_from, range_to)
    chain_end = await session.scalar(select(func.max(AuditChainLink.seq))) or 0
    finding, checked, hashes = await _walk(session, tenant_id, first, last)
    if finding is None:
        anchored = await _anchor_problem(session, hashes, first or 1, chain_end, trusted_keys)
        if anchored is not None:
            finding = Finding(anchored[0].seq, None, anchored[1])
    overdue = await unsealed_overdue(session, unsealed_limit, clock)
    stray = await session.scalar(
        select(func.count())
        .select_from(AuditEntry)
        .where(text(f"tableoid = '{DEFAULT_PARTITION}'::regclass"))
    )

    status = "failed" if finding is not None or overdue or stray else "passed"
    run.status = status
    run.entries_checked = checked
    run.unsealed_overdue = overdue
    run.first_broken_seq = finding.seq if finding else None
    run.first_broken_entry_id = finding.entry_id if finding else None
    run.problem = (
        finding.problem.value
        if finding
        else ("unsealed_overdue" if overdue else ("outside_partitions" if stray else None))
    )
    run.finished_at = clock.now()
    await session.flush()
    await record_event(
        session,
        AuditVerificationCompleted(run_id=run.id, status=status, problem=run.problem),
        aggregate_id=run.id,
    )
    if status == "failed":
        await _alert(session, run)
    return VerificationResult(run.id, status, checked, finding, overdue, first, last)


async def _alert(session: AsyncSession, run: AuditVerificationRun) -> None:
    alert = "unsealed_overdue" if run.problem == "unsealed_overdue" else "verification_failed"
    entry_id = await record(
        session,
        action_code="audit.verification_failed",
        facts=WORKER,
        outcome=AuditOutcome.DONE,
        reason_code=run.problem,
        object_type="audit_verification_run",
        object_id=run.id,
        details={
            "kind": run.kind,
            "first_broken_seq": run.first_broken_seq,
            "entries_checked": run.entries_checked,
            "unsealed_overdue": run.unsealed_overdue,
        },
        actor=(AuditActorType.SYSTEM, None),
    )
    await record_event(
        session, AuditAlertRaised(alert=alert, entry_id=entry_id), aggregate_id=entry_id
    )
    if alert == "unsealed_overdue":
        _overdue.add(run.unsealed_overdue)
    else:
        _failures.add(1, {"problem": run.problem or ""})
    log.error(
        "audit_verification_failed",
        run_id=str(run.id),
        problem=run.problem,
        first_broken_seq=run.first_broken_seq,
    )


async def latest_runs(session: AsyncSession, limit: int = 20) -> Sequence[AuditVerificationRun]:
    """Newest verification runs first."""
    return list(
        await session.scalars(
            select(AuditVerificationRun)
            .order_by(AuditVerificationRun.started_at.desc())
            .limit(limit)
        )
    )
