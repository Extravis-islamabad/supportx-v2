"""CI downtimes (WP-053 S5b; REQ-CMDB-020; migration 0198).

Three ways a CI gets a downtime, and the coordinator's conditions on each:

- **From work_items** (a change's or release's planned and actual downtimes, REQ-CHG-063/064,
  and an incident's unplanned one, lane A's S5 PR): `on_downtime_changed` consumes
  `work_items.downtime.changed`. The consumer is transactional and claims the event in
  `processed_events` first, so one event never applies twice; an event whose version is at or
  below the one stored (`source_version`) changes nothing (replayed, or out of order). A CI the
  event names that is no CI of the tenant is skipped. "From an incident" is lane A's incident
  downtime, never a CMDB row (condition 3).
- **By hand on the CI** (`manual`, the right `cmdb.record_downtime`): the only kind edited here,
  with If-Match on the downtime's own version, history and an event.
- **The sweep** (`run_downtime_states`, every minute): moves a stored state as time passes, so a
  CI shows "active" at the start without a refresh (AC1). Claim-once and idempotent (condition
  2): rows are taken `FOR UPDATE SKIP LOCKED`, so two workers never move one row, and a state is
  only moved when time says so, so a re-run moves nothing.

A synced row is read-only here: it is changed at its source record. Events carry IDs and codes
only (§8.2).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import Conflict, NotFound
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.cmdb.domain import downtimes as domain
from app.modules.cmdb.domain.downtimes import CiDowntimeSource, CiDowntimeState
from app.modules.cmdb.domain.types import Problem
from app.modules.cmdb.events import DowntimeChanged
from app.modules.cmdb.infra.models import Ci, CiDowntime
from app.modules.cmdb.service import cis
from app.modules.cmdb.service.catalogue import RECORD_DOWNTIME, invalid, tenant_of
from app.modules.identity_access import Subject
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.ids import new_id

log = get_logger(__name__)

RECORD_TYPE = "ci_downtime"
CONSUMED = "work_items.downtime.changed"
SWEEP_BATCH = 500  # rows a sweep moves per tenant per minute; the rest the next minute
LIST_MAX = 200


# What happened to a downtime, as its event says (`change`).
ADDED, UPDATED, REMOVED, STATE = "added", "updated", "removed", "state"


def _now() -> datetime:
    return datetime.now(UTC)


async def _emit(
    session: AsyncSession, row: CiDowntime, change: str, previous: str | None = None
) -> None:
    """`previous`: the state before this write (None for an added row)."""
    await record_event(
        session,
        DowntimeChanged(
            ci_id=row.ci_id,
            downtime_id=row.id,
            change=change,
            state=row.state,
            source=row.source,
            version=row.version,
            previous_state=previous,
        ),
        aggregate_id=row.ci_id,
        aggregate_version=row.version,
    )


# --- reading --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DowntimeCounts:
    """A CI's live downtimes by state."""

    scheduled: int = 0
    active: int = 0
    completed: int = 0


async def list_for_ci(
    session: AsyncSession, subject: Subject, ci_id: uuid.UUID
) -> list[CiDowntime]:
    """A CI's live downtimes, newest start first (404 for a CI the reader may not see)."""
    await cis.get_ci(session, subject, ci_id)  # the CI's own read check, narrowing included
    return list(
        await session.scalars(
            select(CiDowntime)
            .where(CiDowntime.ci_id == ci_id, CiDowntime.deleted_at.is_(None))
            .order_by(CiDowntime.starts_at.desc(), CiDowntime.id.desc())
            .limit(LIST_MAX)
        )
    )


def counts_of(rows: Sequence[CiDowntime]) -> DowntimeCounts:
    """The counts the CI shows, from its listed downtimes."""
    by = dict.fromkeys(CiDowntimeState, 0)
    for row in rows:
        by[CiDowntimeState(row.state)] += 1
    return DowntimeCounts(
        scheduled=by[CiDowntimeState.SCHEDULED],
        active=by[CiDowntimeState.ACTIVE],
        completed=by[CiDowntimeState.COMPLETED],
    )


# --- by hand --------------------------------------------------------------------------------------


def _checked(starts_at: datetime, ends_at: datetime | None, description: str | None) -> None:
    problems = domain.check_manual(starts_at, ends_at, description)
    if problems:
        raise invalid([Problem(p.field, p.code) for p in problems])


async def _writable_ci(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> Ci:
    """404 for a CI the person may not see, 403 if they may not record its downtimes.

    The right itself, never `cmdb.manage` standing in for it (`cis.writer`'s fallback): vendor
    support holds `cmdb.manage` on a change grant, and a downtime by hand is `never` for it
    (D-173; lane C's S5b check found the fallback).
    """
    if not subject.holds(RECORD_DOWNTIME):
        raise cis._denied(RECORD_DOWNTIME)  # noqa: SLF001 - the CI service's own refusal
    return await cis._writable(session, subject, RECORD_DOWNTIME, ci_id)  # noqa: SLF001


def _snapshot(row: CiDowntime) -> dict[str, Any]:
    return {
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat() if row.ends_at else None,
        "kind": row.kind,
        # Free text is history as "changed" only; its words stay in the record (rule d).
        "description": bool(row.description),
    }


async def record_manual(  # noqa: PLR0913 - the CI, the times, the words and the source
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    starts_at: datetime,
    ends_at: datetime | None,
    kind: str | None,
    description: str | None,
    source: Source,
) -> CiDowntime:
    """A downtime recorded on the CI by hand (`cmdb.record_downtime`)."""
    record = await _writable_ci(session, subject, ci_id)
    _checked(starts_at, ends_at, description)
    row = CiDowntime(
        id=new_id(),
        tenant_id=record.tenant_id,
        ci_id=ci_id,
        source=CiDowntimeSource.MANUAL.value,
        phase=domain.CiDowntimePhase.ACTUAL.value
        if starts_at <= _now()
        else domain.CiDowntimePhase.PLANNED.value,
        kind=kind,
        starts_at=starts_at,
        ends_at=ends_at,
        description=description,
        state=domain.state_at(starts_at, ends_at, _now()).value,
        created_by=subject.user_id,
        updated_by=subject.user_id,
    )
    session.add(row)
    await session.flush()
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="created",
        changes=[Change(k, None, v) for k, v in _snapshot(row).items() if v],
        source=source,
    )
    await _emit(session, row, ADDED)
    return row


async def _manual_row(
    session: AsyncSession, subject: Subject, ci_id: uuid.UUID, downtime_id: uuid.UUID
) -> CiDowntime:
    await _writable_ci(session, subject, ci_id)
    row = await session.scalar(
        select(CiDowntime)
        .where(
            CiDowntime.id == downtime_id,
            CiDowntime.ci_id == ci_id,
            CiDowntime.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise NotFound(code="cmdb_downtime_not_found")
    if row.source != CiDowntimeSource.MANUAL.value:
        # Changed at its source record (a change, a release, an incident), never here.
        raise Conflict(code="cmdb_downtime_synced", params={"source": row.source})
    return row


def _fresh(row: CiDowntime, expected_version: int) -> None:
    if row.version != expected_version:
        raise Conflict(
            code="version_conflict",
            params={"current_version": row.version, "expected_version": expected_version},
        )


async def update_manual(  # noqa: PLR0913 - the downtime, its version, the values and the source
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    downtime_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> CiDowntime:
    """Change a hand-recorded downtime (If-Match on its version)."""
    row = await _manual_row(session, subject, ci_id, downtime_id)
    _fresh(row, expected_version)
    before = _snapshot(row)
    starts_at = values.get("starts_at", row.starts_at)
    ends_at = values.get("ends_at", row.ends_at)
    description = values.get("description", row.description)
    _checked(starts_at, ends_at, description)
    row.starts_at, row.ends_at, row.description = starts_at, ends_at, description
    if "kind" in values:
        row.kind = values["kind"]
    previous = row.state
    row.state = domain.state_at(row.starts_at, row.ends_at, _now()).value
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    after = _snapshot(row)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="updated",
        changes=[Change(k, before[k], after[k]) for k in after if before[k] != after[k]],
        source=source,
    )
    await _emit(session, row, UPDATED, previous)
    return row


async def remove_manual(  # noqa: PLR0913 - the downtime, its version and the source
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    downtime_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a hand-recorded downtime (soft delete; If-Match on its version)."""
    row = await _manual_row(session, subject, ci_id, downtime_id)
    _fresh(row, expected_version)
    row.deleted_at = _now()
    row.version += 1
    row.updated_by = subject.user_id
    await session.flush()
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await _emit(session, row, REMOVED, row.state)


# --- from work_items ------------------------------------------------------------------------------


def _ids(values: Any) -> list[uuid.UUID]:  # noqa: ANN401 - JSON
    found: list[uuid.UUID] = []
    for value in values or ():
        try:
            found.append(uuid.UUID(str(value)))
        except ValueError:
            continue
    return found


def _time(value: Any) -> datetime | None:  # noqa: ANN401 - JSON
    return datetime.fromisoformat(str(value)) if value else None


def _marker(  # noqa: PLR0913 - the downtime's keys and when, explicit
    session: AsyncSession,
    *,
    ci_id: uuid.UUID,
    downtime_id: uuid.UUID,
    version: int,
    payload: Mapping[str, Any],
    now: datetime,
) -> CiDowntime:
    """A row born removed: it only remembers the version, for the stale check."""
    source = domain.SOURCE_OF_TYPE[str(payload.get("type"))]
    starts_at = _time(payload.get("starts_at")) or now
    return CiDowntime(
        id=new_id(),
        tenant_id=tenant_of(session),
        ci_id=ci_id,
        source=source.value,
        source_downtime_id=downtime_id,
        source_version=version,
        phase=str(payload.get("phase") or domain.CiDowntimePhase.PLANNED.value),
        starts_at=starts_at,
        ends_at=None,
        state=domain.state_at(starts_at, None, now).value,
        deleted_at=now,
    )


async def _remember_removal(
    session: AsyncSession,
    named: Sequence[uuid.UUID],
    downtime_id: uuid.UUID,
    version: int,
    payload: Mapping[str, Any],
) -> None:
    """Remember a removal that arrived before any save (lane A's #608 review).

    A removed marker per named CI keeps the version, so the older save, if it arrives later, is
    stale and creates nothing.
    """
    if not named:
        return
    now = _now()
    for ci_id in set(await session.scalars(select(Ci.id).where(Ci.id.in_(named)))):
        session.add(
            _marker(
                session,
                ci_id=ci_id,
                downtime_id=downtime_id,
                version=version,
                payload=payload,
                now=now,
            )
        )
    await session.flush()


async def _drop_unnamed(
    session: AsyncSession,
    existing: Mapping[uuid.UUID, CiDowntime],
    wanted: set[uuid.UUID],
    version: int,
) -> None:
    """Remove the rows of CIs the downtime no longer names (or all, when it was removed)."""
    now = _now()
    for ci_id, row in existing.items():
        if ci_id in wanted:
            continue
        row.deleted_at = now
        row.version += 1
        row.source_version = version
        await session.flush()
        await _emit(session, row, REMOVED, row.state)


async def on_downtime_changed(envelope: Any, session: AsyncSession | None) -> None:  # noqa: ANN401 - the event envelope
    """Mirror one work_items downtime onto each CI (and business service) it names.

    Transactional: the framework claims the event in `processed_events` in this transaction,
    so a redelivered event is never applied twice; `source_version` drops an older one.
    """
    assert session is not None  # noqa: S101 - transactional consumer
    payload = envelope.payload
    source = domain.SOURCE_OF_TYPE.get(str(payload.get("type")))
    if source is None:
        return  # a record type that sends no CI downtimes
    downtime_id = uuid.UUID(str(payload["downtime_id"]))
    version = int(payload["version"])
    every = list(
        await session.scalars(
            select(CiDowntime).where(CiDowntime.source_downtime_id == downtime_id).with_for_update()
        )
    )
    # The newest version applied, over every row of this downtime, removed ones included: a
    # removal that arrives before an older save leaves only removed rows to compare with (lane A).
    applied = max((r.source_version for r in every if r.source_version is not None), default=None)
    if domain.is_stale(applied, version):
        return  # this downtime is already at that version or newer
    existing = {row.ci_id: row for row in every if row.deleted_at is None}
    named = _ids(payload.get("ci_ids")) + _ids(payload.get("service_ids"))
    wanted: set[uuid.UUID] = set()
    if not payload.get("deleted") and named:
        wanted = set(
            await session.scalars(select(Ci.id).where(Ci.id.in_(named), Ci.deleted_at.is_(None)))
        )
    starts_at = _time(payload.get("starts_at"))
    ends_at = _time(payload.get("ends_at"))
    now = _now()
    await _drop_unnamed(session, existing, wanted if starts_at is not None else set(), version)
    if payload.get("deleted") and not every:
        await _remember_removal(session, named, downtime_id, version, payload)
        return
    if starts_at is None:
        return
    state = domain.state_at(starts_at, ends_at, now).value
    work_item_id = _ids([payload.get("work_item_id")])
    fields = {
        "source": source.value,
        "source_work_item_id": work_item_id[0] if work_item_id else None,
        "phase": str(payload.get("phase") or domain.CiDowntimePhase.PLANNED.value),
        "kind": payload.get("kind"),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "state": state,
        "source_version": version,
    }
    for ci_id in sorted(wanted):
        current = existing.get(ci_id)
        if current is None:
            row = CiDowntime(
                id=new_id(),
                tenant_id=tenant_of(session),
                ci_id=ci_id,
                source_downtime_id=downtime_id,
                **fields,
            )
            session.add(row)
            await session.flush()
            await _emit(session, row, ADDED)
            continue
        previous = current.state
        for name, value in fields.items():
            setattr(current, name, value)
        current.version += 1
        await session.flush()
        await _emit(session, current, UPDATED, previous)


# --- the sweep ------------------------------------------------------------------------------------


async def sweep_tenant(session: AsyncSession, now: datetime | None = None) -> int:
    """Move every due downtime of the session's tenant to the state its times say; how many.

    Claim-once (condition 2): `FOR UPDATE SKIP LOCKED` leaves a row another worker holds to it,
    and a row is moved only when time says so, so a second run at the same moment moves none.
    """
    at = now or _now()
    rows = list(
        await session.scalars(
            select(CiDowntime)
            .where(
                CiDowntime.deleted_at.is_(None),
                CiDowntime.state != CiDowntimeState.COMPLETED.value,
                CiDowntime.starts_at <= at,
            )
            .order_by(CiDowntime.starts_at)
            .limit(SWEEP_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    moved = 0
    for row in rows:
        state = domain.state_at(row.starts_at, row.ends_at, at).value
        if state == row.state:
            continue
        previous, row.state = row.state, state
        row.version += 1
        await session.flush()
        await _emit(session, row, STATE, previous)
        moved += 1
    return moved


async def run_downtime_states(database: Database, settings: Settings) -> None:
    """Schedule: every tenant's due downtimes move state (REQ-CMDB-020 AC1)."""
    del settings
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        try:
            async with database.tenant_session(TenantContext(tenant)) as session:
                await sweep_tenant(session)
        except Exception:  # pragma: no cover - one tenant's failure must not stop the others
            log.exception("cmdb_downtime_sweep_failed", tenant_id=str(tenant))
