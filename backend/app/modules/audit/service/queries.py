"""Reading the audit log: the list, one entry, and the integrity status (REQ-AUD-003, 007, 010).

Reads go through RLS (tenant) and the route's `audit.view` permission. Names of people are
looked up when read, never stored in entries: an erased person's entries keep their ID and show
no name (REQ-AUD-013).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.audit.domain.catalogue import (
    ACTIONS,
    AuditActorType,
    AuditCategory,
    AuditClient,
    AuditOutcome,
)
from app.modules.audit.infra.models import (
    AuditAnchor,
    AuditArchive,
    AuditChainLink,
    AuditEntry,
    AuditPersonal,
    AuditQueueItem,
    AuditVerificationRun,
)
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.listing import ListQuery, PageResult, paginate
from app.shared.clock import Clock, system_clock

ENTRY_FIELDS = ResourceFields(
    name="audit_entries",
    fields={
        "id": FilterField(AuditEntry.id, FieldType.UUID),
        "occurred_at": FilterField(
            AuditEntry.occurred_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        "action": FilterField(AuditEntry.action, FieldType.ENUM, values=frozenset(ACTIONS)),
        "category": FilterField(
            AuditEntry.category, FieldType.ENUM, values=frozenset(c.value for c in AuditCategory)
        ),
        "module": FilterField(AuditEntry.module, FieldType.STRING),
        "outcome": FilterField(
            AuditEntry.outcome, FieldType.ENUM, values=frozenset(o.value for o in AuditOutcome)
        ),
        "actor_type": FilterField(
            AuditEntry.actor_type,
            FieldType.ENUM,
            values=frozenset(a.value for a in AuditActorType),
        ),
        "actor_id": FilterField(AuditEntry.actor_id, FieldType.UUID),
        "object_type": FilterField(AuditEntry.object_type, FieldType.STRING),
        "object_id": FilterField(AuditEntry.object_id, FieldType.STRING),
        "client": FilterField(
            AuditEntry.client, FieldType.ENUM, values=frozenset(c.value for c in AuditClient)
        ),
        "request_id": FilterField(AuditEntry.request_id, FieldType.STRING),
        "change_id": FilterField(AuditEntry.change_id, FieldType.UUID),
    },
    id_column=AuditEntry.id,
    default_sort=("-occurred_at",),
)


@dataclass(frozen=True)
class EntryView:
    """One entry as the API shows it."""

    entry: AuditEntry
    seq: int | None  # None while it waits to be sealed ("pending seal")


@dataclass(frozen=True)
class EntryDetail:
    """One entry with its integrity data and personal values."""

    view: EntryView
    chain_hash: bytes | None
    prev_hash: bytes | None
    sealed_at: datetime | None
    personal: dict[str, dict[str, Any]]  # subject id -> data (erased subjects are absent)


async def _views(session: AsyncSession, entries: Sequence[AuditEntry]) -> list[EntryView]:
    ids = [e.id for e in entries]
    seqs: dict[uuid.UUID, int] = {}
    if ids:
        rows = await session.execute(
            select(AuditChainLink.entry_id, AuditChainLink.seq).where(
                AuditChainLink.entry_id.in_(ids)
            )
        )
        seqs = {row.entry_id: row.seq for row in rows}
    return [EntryView(e, seqs.get(e.id)) for e in entries]


async def list_entries(
    session: AsyncSession, query: ListQuery
) -> tuple[list[EntryView], PageResult[Any]]:
    """One page of the log (filters, sort and cursor from the shared list query)."""
    page = await paginate(session, select(AuditEntry), query)
    return await _views(session, page.rows), page


async def get_entry(session: AsyncSession, entry_id: uuid.UUID) -> EntryDetail:
    """One entry with its chain position and personal values, or 404."""
    entry = await session.scalar(select(AuditEntry).where(AuditEntry.id == entry_id))
    if entry is None:
        raise NotFound(code="audit_entry_not_found")
    link = await session.scalar(select(AuditChainLink).where(AuditChainLink.entry_id == entry_id))
    personal = {
        str(row.subject_id): dict(row.data)
        for row in await session.scalars(
            select(AuditPersonal).where(AuditPersonal.entry_id == entry_id)
        )
    }
    (view,) = await _views(session, [entry])
    return EntryDetail(
        view,
        link.chain_hash if link else None,
        link.prev_hash if link else None,
        link.sealed_at if link else None,
        personal,
    )


@dataclass(frozen=True)
class IntegrityStatus:
    """What the integrity panel and the console banner show (REQ-AUD-010)."""

    sealed_entries: int
    pending_seal: int
    pending_overdue: int
    anchoring_configured: bool
    last_anchor_at: datetime | None
    last_anchor_seq: int | None
    last_daily: AuditVerificationRun | None
    last_weekly: AuditVerificationRun | None
    last_on_demand: AuditVerificationRun | None
    alert: str | None  # an unresolved problem: the banner stays until a later full run passes


async def _last_run(session: AsyncSession, kind: str) -> AuditVerificationRun | None:
    return await session.scalar(
        select(AuditVerificationRun)
        .where(AuditVerificationRun.kind == kind, AuditVerificationRun.status != "running")
        .order_by(AuditVerificationRun.started_at.desc())
        .limit(1)
    )


async def integrity_status(
    session: AsyncSession,
    *,
    anchoring_configured: bool,
    unsealed_limit: timedelta,
    clock: Clock = system_clock,
) -> IntegrityStatus:
    """The current state of the tenant's chain."""
    sealed = await session.scalar(select(func.max(AuditChainLink.seq))) or 0
    pending = await session.scalar(select(func.count()).select_from(AuditQueueItem)) or 0
    overdue = (
        await session.scalar(
            select(func.count())
            .select_from(AuditQueueItem)
            .where(AuditQueueItem.occurred_at < clock.now() - unsealed_limit)
        )
        or 0
    )
    anchor = await session.scalar(select(AuditAnchor).order_by(AuditAnchor.seq.desc()).limit(1))
    daily, weekly, on_demand = (
        await _last_run(session, "daily"),
        await _last_run(session, "weekly"),
        await _last_run(session, "on_demand"),
    )
    # A failure stays visible until a full (weekly or on-demand, unbounded) run passes after it.
    failed = await session.scalar(
        select(AuditVerificationRun)
        .where(AuditVerificationRun.status == "failed")
        .order_by(AuditVerificationRun.started_at.desc())
        .limit(1)
    )
    alert: str | None = "unsealed_overdue" if overdue else None
    if failed is not None:
        cleared = await session.scalar(
            select(func.count())
            .select_from(AuditVerificationRun)
            .where(
                AuditVerificationRun.status == "passed",
                AuditVerificationRun.range_from.is_(None),
                AuditVerificationRun.started_at > failed.started_at,
            )
        )
        if not cleared:
            alert = failed.problem or "verification_failed"
    if alert is None:
        # A failed archive stays visible until a later month archives (the job retries daily).
        archive = await session.scalar(
            select(AuditArchive).order_by(AuditArchive.created_at.desc()).limit(1)
        )
        if archive is not None and archive.status == "failed":
            alert = "archive_failed"
    return IntegrityStatus(
        sealed_entries=int(sealed),
        pending_seal=int(pending),
        pending_overdue=int(overdue),
        anchoring_configured=anchoring_configured,
        last_anchor_at=anchor.created_at if anchor else None,
        last_anchor_seq=anchor.seq if anchor else None,
        last_daily=daily,
        last_weekly=weekly,
        last_on_demand=on_demand,
        alert=alert,
    )


async def entries_for_changes(
    session: AsyncSession, change_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """Change ID → audit entry ID, for the history entries that have an audit entry."""
    if not change_ids:
        return {}
    rows = await session.execute(
        select(AuditEntry.change_id, AuditEntry.id).where(AuditEntry.change_id.in_(change_ids))
    )
    return {row.change_id: row.id for row in rows}
