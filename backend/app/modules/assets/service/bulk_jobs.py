"""Bulk edit, move, assign and delete of assets as background jobs (WP-049b S4b; REQ-AST-051).

The pattern of work items' bulk jobs (WP-020d, work_items/service/bulk.py): a job freezes the
assets it is asked for (at most MAX_BULK; more is a 422 `asset_bulk_too_many` with the cap),
then runs in the consumers worker in batches of BULK_BATCH assets per transaction, **as the
requester**. Each asset goes through the same service call one change would make (scope,
life cycle, disposed read-only, D-157 money, licence slot, If-Match on the version read now),
in its own savepoint: an asset that refuses is skipped with the reason code, never forced and
never silently left out. Delete is the trash (soft delete); nothing here deletes a row.

Each asset's history names the job (`field_changes.batch_id`). Progress goes to the requester's
personal channel after every batch; the job and its per-asset results stay readable after.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import AppError, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.assets.domain.batch import (
    BULK_BATCH,
    BULK_TOO_MANY,
    MAX_BULK,
    AssetBulkAction,
    AssetBulkOutcome,
    AssetBulkStatus,
    bulk_change_problems,
)
from app.modules.assets.domain.catalogue import Problem
from app.modules.assets.events import AssetBulkJobProgressed
from app.modules.assets.infra.models import Asset, AssetBulkJob
from app.modules.assets.service import assets as records
from app.modules.assets.service import moves, ownership
from app.modules.assets.service.assets import MANAGE, _refuse, _require
from app.modules.identity_access import Subject, subject_for
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Source, in_batch

log = get_logger(__name__)


class JobRepository(Repository[AssetBulkJob]):
    """Asset bulk jobs of the session's tenant."""

    model = AssetBulkJob


def _clean_changes(action: AssetBulkAction, changes: Mapping[str, Any]) -> dict[str, Any]:
    _refuse(bulk_change_problems(action, changes))
    # JSON as stored: IDs and dates as text, as the single-asset calls are given them.
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in changes.items()}


async def start(  # noqa: PLR0913 - the job's inputs, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    action: AssetBulkAction,
    changes: Mapping[str, Any],
    asset_ids: Sequence[uuid.UUID],
    source: Source,
) -> AssetBulkJob:
    """Queue a job for the frozen `asset_ids` (each once, in the given order).

    `assets.manage` to ask at all; each asset is checked again when it runs (scope, life cycle).
    Money is never set in bulk (D-157: the edit fields leave it out).
    """
    _require(subject, MANAGE)
    ids = list(dict.fromkeys(asset_ids))
    if not ids:
        _refuse([Problem("asset_ids", "required")])
    if len(ids) > MAX_BULK:
        raise ValidationFailed(code=BULK_TOO_MANY, params={"max": MAX_BULK})
    clean = _clean_changes(action, changes)
    job = await JobRepository(session).add(
        AssetBulkJob(
            action=action.value,
            changes=clean,
            source=source,
            asset_ids=ids,
            status=AssetBulkStatus.QUEUED.value,
            total=len(ids),
            processed=0,
            done_count=0,
            skipped_count=0,
            results=[],
        )
    )
    await _progress(session, job)
    return job


async def job(session: AsyncSession, subject: Subject, job_id: uuid.UUID) -> AssetBulkJob:
    """One of the subject's own jobs (anyone else's is not found)."""
    found: AssetBulkJob | None = await session.scalar(
        select(AssetBulkJob).where(
            AssetBulkJob.id == job_id,
            AssetBulkJob.created_by == subject.user_id,
            AssetBulkJob.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="asset_bulk_job_not_found")
    return found


async def jobs(session: AsyncSession, subject: Subject, *, limit: int = 20) -> list[AssetBulkJob]:
    """The subject's latest jobs, newest first."""
    rows = await session.scalars(
        select(AssetBulkJob)
        .where(AssetBulkJob.created_by == subject.user_id, AssetBulkJob.deleted_at.is_(None))
        .order_by(AssetBulkJob.created_at.desc(), AssetBulkJob.id.desc())
        .limit(limit)
    )
    return list(rows)


async def _progress(session: AsyncSession, found: AssetBulkJob) -> None:
    if found.created_by is None:  # pragma: no cover - jobs are only asked for by people
        return
    await record_event(
        session,
        AssetBulkJobProgressed(
            job_id=found.id,
            requested_by=found.created_by,
            status=found.status,  # type: ignore[arg-type]  # CHECK constraint: a status code
            processed=found.processed,
            total=found.total,
        ),
        aggregate_id=found.id,
    )


# --- the worker -----------------------------------------------------------------------------------


async def run_asset_bulk_jobs(database: Database, settings: Settings) -> None:
    """Schedule: every tenant's queued jobs (and any a stopped run left running), oldest first."""
    del settings
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        while (ref := await _next(database, tenant)) is not None:
            try:
                await _run(database, tenant, ref)
            except Exception:  # one broken job must not stop the others; it is logged
                log.exception("asset_bulk_job_failed", job_id=str(ref[0]))
                await _finish(database, tenant, ref, failed=True)


async def _next(database: Database, tenant: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        row = (
            await session.execute(
                select(AssetBulkJob.id, AssetBulkJob.created_by)
                .where(
                    AssetBulkJob.status.in_((AssetBulkStatus.QUEUED, AssetBulkStatus.RUNNING)),
                    AssetBulkJob.deleted_at.is_(None),
                )
                .order_by(AssetBulkJob.created_at, AssetBulkJob.id)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        if row.created_by is None:  # pragma: no cover - jobs are only asked for by people
            found = await session.get(AssetBulkJob, row.id)
            if found is not None:
                found.status = AssetBulkStatus.FAILED.value
            return None
    return row.id, row.created_by


async def _run(database: Database, tenant: uuid.UUID, ref: tuple[uuid.UUID, uuid.UUID]) -> None:
    job_id, requester = ref
    context = TenantContext(tenant, requester)  # each asset is the requester's own change
    async with database.tenant_session(context) as session:
        found = await session.get(AssetBulkJob, job_id)
        if found is None:
            return
        remaining = list(found.asset_ids[found.processed :])
        if found.status != AssetBulkStatus.RUNNING:
            found.status, found.started_at = AssetBulkStatus.RUNNING.value, datetime.now(UTC)
            await _progress(session, found)
    for offset in range(0, len(remaining), BULK_BATCH):
        async with database.tenant_session(context) as session:
            await _batch(session, tenant, job_id, remaining[offset : offset + BULK_BATCH])
    await _finish(database, tenant, ref)


async def _batch(
    session: AsyncSession, tenant: uuid.UUID, job_id: uuid.UUID, asset_ids: list[uuid.UUID]
) -> None:
    found = await session.get(AssetBulkJob, job_id, with_for_update=True)
    if found is None or found.created_by is None:  # pragma: no cover - never hard-deleted
        return
    # Read now, not when asked: a permission taken away meanwhile is honoured (each asset).
    subject = await subject_for(session, tenant, found.created_by)
    results = list(found.results)
    in_batch(session, found.id)
    try:
        for asset_id in asset_ids:
            tag = await session.scalar(select(Asset.tag).where(Asset.id == asset_id))
            try:
                async with session.begin_nested():
                    await _apply(session, subject, found, asset_id)
            except AppError as refused:
                found.skipped_count += 1
                results.append(_skipped(asset_id, tag, refused))
            else:
                found.done_count += 1
                results.append({"id": str(asset_id), "tag": tag, "outcome": AssetBulkOutcome.DONE})
            found.processed += 1
    finally:
        in_batch(session, None)
    found.results = results
    found.version += 1
    await _progress(session, found)


def _skipped(asset_id: uuid.UUID, tag: str | None, refused: AppError) -> dict[str, Any]:
    """The reason in codes the screen words: the first field problem, else the error itself."""
    first = refused.errors[0] if refused.errors else None
    return {
        "id": str(asset_id),
        "tag": tag,
        "outcome": AssetBulkOutcome.SKIPPED,
        "code": first.code if first is not None else refused.instance_code,
        "field": first.field.removeprefix("body.") if first is not None else None,
        "params": dict(first.params) if first is not None else dict(refused.params),
    }


async def _apply(
    session: AsyncSession, subject: Subject, found: AssetBulkJob, asset_id: uuid.UUID
) -> None:
    """One asset, through the call a single change makes; its version is read now."""
    version = await session.scalar(
        select(Asset.version).where(Asset.id == asset_id, Asset.deleted_at.is_(None))
    )
    if version is None:
        raise NotFound(code="asset_not_found")
    changes = found.changes
    source: Source = found.source  # type: ignore[assignment]  # stored from Source
    match AssetBulkAction(found.action):
        case AssetBulkAction.EDIT:
            await records.update_asset(
                session, subject, asset_id, _values(changes), expected_version=version,
                source=source,
            )  # fmt: skip
        case AssetBulkAction.MOVE:
            await moves.move_asset(
                session,
                subject,
                asset_id,
                to_state_id=uuid.UUID(str(changes["to_state_id"])),
                reason=changes.get("reason"),
                expected_version=version,
                source=source,
            )
        case AssetBulkAction.ASSIGN:
            kind, holder = changes.get("holder_kind"), changes.get("holder_id")
            await ownership.set_holder(
                session,
                subject,
                asset_id,
                None if kind is None else ownership.Holder(str(kind), uuid.UUID(str(holder))),
                expected_version=version,
                source=source,
            )
        case AssetBulkAction.DELETE:
            await records.delete_asset(
                session, subject, asset_id, expected_version=version, source=source
            )


_ID_FIELDS = frozenset({"product_id", "vendor_id", "site_id"})
_DATE_FIELDS = frozenset({"acquired_on", "warranty_expires_on", "expires_on"})


def _values(changes: Mapping[str, Any]) -> dict[str, Any]:
    """The stored JSON back as the update takes it: IDs and dates typed."""
    values: dict[str, Any] = {}
    for name, value in changes.items():
        if value is not None and name in _ID_FIELDS:
            values[name] = uuid.UUID(str(value))
        elif value is not None and name in _DATE_FIELDS:
            values[name] = date.fromisoformat(str(value))
        else:
            values[name] = value
    return values


async def _finish(
    database: Database,
    tenant: uuid.UUID,
    ref: tuple[uuid.UUID, uuid.UUID],
    *,
    failed: bool = False,
) -> None:
    async with database.tenant_session(TenantContext(tenant, ref[1])) as session:
        found = await session.get(AssetBulkJob, ref[0], with_for_update=True)
        if found is None or found.status in {AssetBulkStatus.DONE, AssetBulkStatus.FAILED}:
            return
        found.status = (AssetBulkStatus.FAILED if failed else AssetBulkStatus.DONE).value
        found.finished_at = datetime.now(UTC)
        found.version += 1
        await _progress(session, found)
