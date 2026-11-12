"""Bulk edit, assign, take, resolve and close (WP-020d; REQ-INC-119, 120; architecture.md §10).

A bulk job freezes its records when it is asked for: the rows the user picked, or every record
of the list as the user sees it ("select all N": the list's own view, filter and tag, resolved
to IDs at once, so records arriving later are not swept in). It then runs in the consumers
worker, in batches of BULK_BATCH records per transaction, **as the requester**: each record goes
through the same service call a single change would (permissions, scope, transitions, closure
rules, open-work checks), and a record that refuses is skipped with the reason, never forced.

Each record's history names the job (`field_changes.batch_id`). Its events carry the job in
their correlation ID, so the realtime router updates the record's own channel but leaves the
lists alone; the job's progress event refreshes the lists once per batch (REQ-INC-120: screens do
not flood). Progress goes to the requester's personal channel; the job stays readable afterwards
(AC3).
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, tzinfo
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import AppError, Conflict, NotFound, PermissionDenied
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access import Subject, subject_for, worker_policy
from app.modules.work_items.domain.lifecycle import StatusCategory, WorkItemAction
from app.modules.work_items.domain.lists import (
    BULK_BATCH,
    MAX_BULK,
    BulkAction,
    BulkOutcome,
    BulkStatus,
)
from app.modules.work_items.domain.stages import StageModel
from app.modules.work_items.domain.types import INCIDENT, TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.events import WorkItemBulkJobProgressed
from app.modules.work_items.infra.models import WorkItem, WorkItemBulkJob
from app.modules.work_items.service import change_close, closing
from app.modules.work_items.service import problems as problem_links
from app.modules.work_items.service import stages as stage_service
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.realtime import BULK_PREFIX
from app.modules.work_items.service.work_items import StageOffer
from app.shared.api.listing import ListQuery, order_by
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, in_batch, record_changes

log = get_logger(__name__)
BATCH_PREFIX = BULK_PREFIX  # correlation ID of a job's events: "bulk:<job id>"
# Every action needs this permission to be asked for at all; each record checks again.
_PERMISSION = {
    BulkAction.EDIT: "edit",
    BulkAction.ASSIGN: "assign",
    BulkAction.TAKE: "take",
    BulkAction.RESOLVE: "view",
    BulkAction.CLOSE: "view",
    BulkAction.LINK_PROBLEM: "edit",
    BulkAction.UNLINK_PROBLEM: "edit",
    BulkAction.CANCEL: "cancel",
    BulkAction.DELETE: "delete",
    # A release role's holders: the record's edit right, checked again on each one (set_role).
    BulkAction.ASSIGN_ROLE: "edit",
}
_KEYS = {
    BulkAction.EDIT: None,  # any field the edit form has; the update checks each one
    BulkAction.ASSIGN: {"group_id", "technician_id", "confirm_lose_access"},
    BulkAction.TAKE: set(),
    # follow_up_of: a problem's display id, named in each incident's history (REQ-PRB-055 AC4).
    BulkAction.RESOLVE: {"resolution", "confirm_open_work", "follow_up_of"},
    BulkAction.CLOSE: {"closure_code", "confirm_open_work"},
    BulkAction.LINK_PROBLEM: {"problem_id", "move"},
    BulkAction.UNLINK_PROBLEM: {"problem_id"},
    BulkAction.CANCEL: {"reason_text"},
    BulkAction.DELETE: set(),
    BulkAction.ASSIGN_ROLE: {"role", "user_ids", "group_ids"},
}
# The staged lists' own actions (REQ-CHG-101, REQ-REL-057): other types cancel through their
# life cycle, and only a type with record roles has role holders to set.
STAGED_ONLY = frozenset({BulkAction.CANCEL, BulkAction.DELETE})
ROLES_ONLY = frozenset({BulkAction.ASSIGN_ROLE})


class JobRepository(Repository[WorkItemBulkJob]):
    """Bulk jobs of the session's tenant."""

    model = WorkItemBulkJob


def _check_changes(action: BulkAction, changes: dict[str, Any]) -> dict[str, Any]:
    keys = _KEYS[action]
    problems: list[tuple[str, str]] = []
    if keys is not None and set(changes) - keys:
        problems.append(("changes", "invalid_choice"))
    if action == BulkAction.EDIT and not changes:
        problems.append(("changes", "required"))  # AC2: only what the user changed, and something
    if action == BulkAction.LINK_PROBLEM and not changes.get("problem_id"):
        problems.append(("changes", "required"))
    if action == BulkAction.CANCEL and not str(changes.get("reason_text") or "").strip():
        problems.append(("changes", "required"))  # a cancel says why, for every change
    if action == BulkAction.ASSIGN_ROLE and (
        not isinstance(changes.get("role"), str)
        or not (changes.get("user_ids") or changes.get("group_ids"))
    ):
        problems.append(("changes", "required"))  # a role, and someone to hold it
    if action == BulkAction.ASSIGN and not (
        changes.get("group_id") or changes.get("technician_id")
    ):
        problems.append(("changes", "required"))
    if problems:
        raise items.field_errors(problems)
    return dict(changes)


async def matching_ids(  # noqa: PLR0913 - the list's query, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    query: ListQuery,
    *,
    view: str | None,
    tag: str | None,
    zone: tzinfo,
) -> list[uuid.UUID]:
    """Every record the list shows for this query ("select all N"), in its order; ≤ MAX_BULK."""
    statement = await items.narrowed(
        session, subject, items.staff_rows(subject, wtype), view=view, zone=zone, tag=tag
    )
    rows = await session.scalars(
        statement.where(query.where)
        .with_only_columns(WorkItem.id)
        .order_by(*order_by(query.sort))
        .limit(MAX_BULK + 1)
    )
    found = list(rows)
    if len(found) > MAX_BULK:
        raise items.field_errors([("records", "too_many_records")], max=MAX_BULK)
    return found


async def start(  # noqa: PLR0913 - the job's inputs, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    *,
    action: BulkAction,
    changes: dict[str, Any],
    record_ids: Sequence[uuid.UUID],
    source: Source,
) -> WorkItemBulkJob:
    """Queue a job for the frozen `record_ids` (each once, in the given order)."""
    permission = wtype.permission(_PERMISSION[action])
    if not subject.holds(permission):
        raise PermissionDenied(params={"permission": permission, "reason": "no_permission"})
    if (
        action in {BulkAction.LINK_PROBLEM, BulkAction.UNLINK_PROBLEM}
        and wtype.code is not WorkItemTypeCode.INCIDENT
    ):
        raise items.field_errors([("action", "invalid_choice")])  # only incidents have a cause
    if action in STAGED_ONLY and wtype.stages is None:
        raise items.field_errors([("action", "invalid_choice")])  # the staged lists' (CHG-101)
    if action in ROLES_ONLY and not wtype.roles:
        raise items.field_errors([("action", "invalid_choice")])  # REQ-REL-057
    clean = _check_changes(action, changes)
    ids = list(dict.fromkeys(record_ids))
    if not ids:
        raise items.field_errors([("records", "required")])
    if len(ids) > MAX_BULK:
        raise items.field_errors([("records", "too_many_records")], max=MAX_BULK)
    job = await JobRepository(session).add(
        WorkItemBulkJob(
            type=wtype.code,
            action=action.value,
            changes=clean,
            source=source,
            record_ids=ids,
            status=BulkStatus.QUEUED.value,
            total=len(ids),
            processed=0,
            done_count=0,
            skipped_count=0,
            results=[],
        )
    )
    await _progress(session, job)
    return job


async def start_problem_links(  # noqa: PLR0913 - the problem, the incidents and the move, explicit
    session: AsyncSession,
    subject: Subject,
    problem_id: uuid.UUID,
    incident_ids: Sequence[uuid.UUID],
    *,
    moving: set[uuid.UUID],
    source: Source,
) -> list[WorkItemBulkJob]:
    """Link incidents to a new problem (REQ-PRB-012): one job to link, one to move (AC2).

    Those not in `moving` that turn out to have a problem by the time the job runs are left
    there (skipped with the reason), never moved without the person's say.
    """
    jobs: list[WorkItemBulkJob] = []
    for move in (False, True):
        ids = [i for i in incident_ids if (i in moving) is move]
        if ids:
            jobs.append(
                await start(
                    session,
                    subject,
                    INCIDENT,
                    action=BulkAction.LINK_PROBLEM,
                    changes={"problem_id": str(problem_id), "move": move},
                    record_ids=ids,
                    source=source,
                )
            )
    return jobs


async def job(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, job_id: uuid.UUID
) -> WorkItemBulkJob:
    """One of the subject's own jobs (anyone else's is not found)."""
    found: WorkItemBulkJob | None = await session.scalar(
        select(WorkItemBulkJob).where(
            WorkItemBulkJob.id == job_id,
            WorkItemBulkJob.type == wtype.code,
            WorkItemBulkJob.created_by == subject.user_id,
            WorkItemBulkJob.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="bulk_job_not_found")
    return found


async def jobs(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, *, limit: int = 20
) -> list[WorkItemBulkJob]:
    """The subject's latest jobs, newest first (the result stays findable, AC3)."""
    rows = await session.scalars(
        select(WorkItemBulkJob)
        .where(
            WorkItemBulkJob.type == wtype.code,
            WorkItemBulkJob.created_by == subject.user_id,
            WorkItemBulkJob.deleted_at.is_(None),
        )
        .order_by(WorkItemBulkJob.created_at.desc(), WorkItemBulkJob.id.desc())
        .limit(limit)
    )
    return list(rows)


async def _progress(session: AsyncSession, job: WorkItemBulkJob) -> None:
    await record_event(
        session,
        WorkItemBulkJobProgressed(
            job_id=job.id,
            type=job.type,
            requested_by=job.created_by,
            status=job.status,
            processed=job.processed,
            total=job.total,
        ),
        aggregate_id=job.id,
    )


# --- the worker -----------------------------------------------------------------------------------


async def run_bulk_jobs(database: Database, settings: Settings) -> None:
    """Schedule: every tenant's queued jobs (and any a stopped run left running), oldest first."""
    del settings
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        while (ref := await _next(database, tenant)) is not None:
            try:
                await _run(database, tenant, ref)
            except Exception:  # one broken job must not stop the others; it is logged
                log.exception("bulk_job_failed", job_id=str(ref[0]))
                await _finish(database, tenant, ref, failed=True)


async def _next(database: Database, tenant: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        row = (
            await session.execute(
                select(WorkItemBulkJob.id, WorkItemBulkJob.created_by)
                .where(
                    WorkItemBulkJob.status.in_((BulkStatus.QUEUED, BulkStatus.RUNNING)),
                    WorkItemBulkJob.deleted_at.is_(None),
                )
                .order_by(WorkItemBulkJob.created_at, WorkItemBulkJob.id)
                .limit(1)
            )
        ).one_or_none()
    if row is None:
        return None
    if row.created_by is None:  # pragma: no cover - jobs are only asked for by people
        async with database.tenant_session(TenantContext(tenant)) as session:
            found = await session.get(WorkItemBulkJob, row.id)
            if found is not None:
                found.status = BulkStatus.FAILED.value
        return None
    return row.id, row.created_by


async def _run(database: Database, tenant: uuid.UUID, ref: tuple[uuid.UUID, uuid.UUID]) -> None:
    job_id, requester = ref
    context = TenantContext(tenant, requester)  # each record is the requester's own change
    async with database.tenant_session(context) as session:
        found = await session.get(WorkItemBulkJob, job_id)
        if found is None:
            return
        remaining = found.record_ids[found.processed :]
        if found.status != BulkStatus.RUNNING:
            found.status, found.started_at = BulkStatus.RUNNING.value, datetime.now(UTC)
            await _progress(session, found)
    for offset in range(0, len(remaining), BULK_BATCH):
        async with database.tenant_session(context) as session:
            await _batch(session, tenant, job_id, remaining[offset : offset + BULK_BATCH])
    await _finish(database, tenant, ref)


async def _batch(
    session: AsyncSession, tenant: uuid.UUID, job_id: uuid.UUID, record_ids: list[uuid.UUID]
) -> None:
    found = await session.get(WorkItemBulkJob, job_id, with_for_update=True)
    if found is None:  # pragma: no cover - jobs are never hard-deleted
        return
    if found.created_by is None:  # pragma: no cover - see _next
        return
    subject = await subject_for(session, tenant, found.created_by)
    wtype = TYPES[WorkItemTypeCode(found.type)]
    results = list(found.results)
    in_batch(session, found.id)
    structlog.contextvars.bind_contextvars(request_id=f"{BATCH_PREFIX}{found.id}")
    try:
        for record_id in record_ids:
            display_id = await session.scalar(
                select(WorkItem.display_id).where(WorkItem.id == record_id)
            )
            try:
                async with session.begin_nested():
                    await _apply(session, subject, wtype, found, record_id)
            except AppError as refused:
                found.skipped_count += 1
                results.append(_skipped(record_id, display_id, refused))
            else:
                found.done_count += 1
                results.append(
                    {"id": str(record_id), "display_id": display_id, "outcome": BulkOutcome.DONE}
                )
            found.processed += 1
    finally:
        in_batch(session, None)
        structlog.contextvars.unbind_contextvars("request_id")
    found.results = results
    await _progress(session, found)


def _skipped(record_id: uuid.UUID, display_id: str | None, refused: AppError) -> dict[str, Any]:
    """The reason in codes the screen words: the first field problem, else the error itself."""
    first = refused.errors[0] if refused.errors else None
    return {
        "id": str(record_id),
        "display_id": display_id,
        "outcome": BulkOutcome.SKIPPED,
        "code": first.code if first is not None else refused.instance_code,
        "field": first.field.removeprefix("body.") if first is not None else None,
        "params": dict(first.params) if first is not None else refused.params,
    }


async def _apply(  # noqa: C901 - one case per bulk action, flat
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    found: WorkItemBulkJob,
    record_id: uuid.UUID,
) -> None:
    """One record, through the same call a single change makes; its version is read now."""
    version = await session.scalar(
        select(WorkItem.version).where(WorkItem.id == record_id, WorkItem.deleted_at.is_(None))
    )
    if version is None:
        raise NotFound(code="work_item_not_found")
    changes = found.changes
    source: Source = found.source  # type: ignore[assignment]  # stored from Source
    holders = worker_policy()
    match BulkAction(found.action):
        case BulkAction.EDIT:
            await items.update(
                session,
                subject,
                wtype,
                record_id,
                expected_version=version,
                values=changes,
                source=source,
            )
        case BulkAction.ASSIGN:
            await items.assign(
                session,
                subject,
                wtype,
                record_id,
                expected_version=version,
                group_id=_uuid(changes.get("group_id")),
                technician_id=_uuid(changes.get("technician_id")),
                reason_code=None,
                reason_text=None,
                confirm_lose_access=bool(changes.get("confirm_lose_access")),
                source=source,
                holders=holders,
            )
        case BulkAction.TAKE:
            await items.take(
                session,
                subject,
                wtype,
                record_id,
                expected_version=version,
                group_id=None,
                source=source,
                holders=holders,
            )
        case BulkAction.LINK_PROBLEM:
            await problem_links.link_cause(
                session,
                subject,
                record_id,
                uuid.UUID(str(changes["problem_id"])),
                move=bool(changes.get("move")),
                source=source,
            )
        case BulkAction.UNLINK_PROBLEM:
            given = changes.get("problem_id")
            await problem_links.unlink_cause(
                session,
                subject,
                record_id,
                uuid.UUID(str(given)) if given else None,
                source=source,
            )
        case BulkAction.CANCEL:
            await _cancel_staged(session, subject, wtype, record_id, version, changes, source)
        case BulkAction.DELETE:
            await items.remove(
                session, subject, wtype, record_id, expected_version=version, source=source
            )
        case BulkAction.ASSIGN_ROLE:
            await items.set_role(
                session,
                subject,
                wtype,
                record_id,
                str(changes["role"]),
                user_ids=[uuid.UUID(str(u)) for u in changes.get("user_ids") or []],
                group_ids=[uuid.UUID(str(g)) for g in changes.get("group_ids") or []],
                expected_version=version,
                source=source,
                holders=holders,
            )
        case BulkAction.CLOSE if wtype.stages is not None:
            await _close_staged(session, subject, wtype, record_id, version, changes, source)
        case BulkAction.RESOLVE | BulkAction.CLOSE as action:
            await items.transition(
                session,
                subject,
                wtype,
                record_id,
                WorkItemAction.RESOLVE if action == BulkAction.RESOLVE else WorkItemAction.CLOSE,
                expected_version=version,
                reason_code=None,
                reason_text=None,
                source=source,
                holders=holders,
                closing_input=closing.MoveInput(
                    resolution=changes.get("resolution"),
                    closure_code=changes.get("closure_code"),
                    confirm_open_work=bool(changes.get("confirm_open_work")),
                ),
            )
            if changes.get("follow_up_of"):
                await _note_follow_up(session, record_id, str(changes["follow_up_of"]), source)


async def _close_staged(  # noqa: PLR0913, PLR0917 - the record and the bulk's values, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    version: int,
    changes: Mapping[str, Any],
    source: Source,
) -> None:
    """Close a staged record by its own listed move that lands in closed (REQ-CHG-101, REL-057).

    Its life cycle, closure rules and children decide, as for one change: the move the record
    page would offer, with the code; none from where it is is a skip that says so. A change
    closes through `change_close`, the one close every flow shares (lane C's REQ-REL-052 too).
    """
    if wtype.code is WorkItemTypeCode.CHANGE:
        await change_close.close_change(
            session,
            subject,
            record_id,
            expected_version=version,
            closure_code=changes.get("closure_code"),
            resolution=changes.get("resolution"),
            confirm_open_work=bool(changes.get("confirm_open_work")),
            source=source,
        )
        return
    panel = await items.stage_panel(session, subject, wtype, record_id)
    # Closed by the type's own model (a release and a change each), never one type's constant.
    model = await stage_service.load_model(session, wtype, panel.record.lifecycle_version)
    closing_move = next(
        (
            m
            for m in panel.moves
            if m.allowed
            and model.status(m.lands_in or m.transition.to_status).category is StatusCategory.CLOSED
        ),
        None,
    )
    if closing_move is None:
        raise Conflict(code="not_closable_from_here")
    await items.move_status(
        session,
        subject,
        wtype,
        record_id,
        target=closing_move.transition.to_status,
        expected_version=version,
        reason_code=None,
        reason_text=None,
        source=source,
        closing_input=closing.MoveInput(
            resolution=changes.get("resolution"),
            closure_code=changes.get("closure_code"),
            confirm_open_work=bool(changes.get("confirm_open_work")),
        ),
    )


CANCEL_PERMISSION = "cancel"  # the lifecycle transitions' cancel right (domain models)


def cancel_move(moves: Sequence[StageOffer], model: StageModel) -> StageOffer | None:
    """The bulk cancel's move: the allowed cancel transition, else any allowed move into canceled.

    Never by the order the moves come in (see _cancel_staged).
    """
    into_canceled = [
        m
        for m in moves
        if m.allowed
        and model.status(m.lands_in or m.transition.to_status).category is StatusCategory.CANCELED
    ]
    return next(
        (m for m in into_canceled if m.transition.permission == CANCEL_PERMISSION),
        into_canceled[0] if into_canceled else None,
    )


async def _cancel_staged(  # noqa: PLR0913, PLR0917 - the record and the bulk's values, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    version: int,
    changes: Mapping[str, Any],
    source: Source,
) -> None:
    """Cancel a change by its own listed move into canceled, with the reason (REQ-CHG-101).

    The same move the record page offers, with its permission and stage rules; a change past the
    point a cancel is offered (implementation in progress or later) is a skip that says so.
    """
    panel = await items.stage_panel(session, subject, wtype, record_id)
    # Canceled by the type's own model (lane A's #438 review), as the close does. A type may
    # have more than one canceled status (a release's submission can also be REJECTED, which is
    # canceled too): the bulk cancel is the cancel transition itself (permission "cancel"), and
    # only a type without one falls back to any move into canceled. Never the order the moves
    # come in (the flake lane B saw in a merge group: a rejection taken for the cancel).
    model = await stage_service.load_model(session, wtype, panel.record.lifecycle_version)
    cancel = cancel_move(panel.moves, model)
    if cancel is None:
        raise Conflict(code="not_cancelable_from_here")
    await items.move_status(
        session,
        subject,
        wtype,
        record_id,
        target=cancel.transition.to_status,
        expected_version=version,
        reason_code=None,
        reason_text=str(changes["reason_text"]).strip(),
        source=source,
    )


async def _note_follow_up(
    session: AsyncSession, record_id: uuid.UUID, problem: str, source: Source
) -> None:
    """The incident's history says the move came from the problem (REQ-PRB-055 AC4)."""
    record = await session.get(WorkItem, record_id, populate_existing=True)
    if record is None:  # pragma: no cover - just moved
        return
    await record_changes(
        session,
        record_type=items.RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="updated",
        changes=[Change("follow_up_of", None, problem)],
        source=source,
    )


def _uuid(value: object) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


async def _finish(
    database: Database,
    tenant: uuid.UUID,
    ref: tuple[uuid.UUID, uuid.UUID],
    *,
    failed: bool = False,
) -> None:
    async with database.tenant_session(TenantContext(tenant, ref[1])) as session:
        found = await session.get(WorkItemBulkJob, ref[0], with_for_update=True)
        if found is None or found.status in {BulkStatus.DONE, BulkStatus.FAILED}:
            return
        found.status = (BulkStatus.FAILED if failed else BulkStatus.DONE).value
        found.finished_at = datetime.now(UTC)
        await _progress(session, found)
