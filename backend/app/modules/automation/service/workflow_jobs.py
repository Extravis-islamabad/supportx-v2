"""Bulk retry and cancel of a workflow's instances, as jobs (WP-048b S3b; REQ-WF-025 AC2).

An admin with `workflows.manage` picks up to 1,000 instances of one workflow (ADR-043 §10). The
worker runs the job in batches, as that admin, each instance in its own savepoint so one refusal
never stops the others, and keeps each instance's result. Progress reaches the overview live
(the `workflows` list channel; IDs and counts only).

Migration (REQ-WF-021, S3c) is the third kind: onto `options.to_version` through
`options.mapping`, or as a dry run that only says what would move (`would_move`).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import AppError, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.automation.events import WorkflowJobProgressed
from app.modules.automation.infra.models import (
    Workflow,
    WorkflowInstance,
    WorkflowJob,
    WorkflowVersion,
)
from app.modules.automation.service import workflow_runtime
from app.shared.events import record_event

log = get_logger(__name__)

MAX_INSTANCES = 1000  # a job's ceiling (§10: bulk at most 1,000 items as background jobs)
BATCH = 50  # instances a transaction


class JobKind(StrEnum):
    """What a job does to each instance."""

    RETRY = "retry"
    CANCEL = "cancel"
    MIGRATE = "migrate"  # onto another version (REQ-WF-021)


class JobStatus(StrEnum):
    """Where a job is."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


async def create(  # noqa: PLR0913 - the job and its choices, explicit
    session: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    kind: JobKind,
    instance_ids: Sequence[uuid.UUID],
    options: dict[str, Any],
    dry_run: bool = False,
) -> WorkflowJob:
    """Queue a job over the chosen instances of one workflow; the worker runs it."""
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None or workflow.deleted_at is not None:
        raise NotFound(code="workflow_not_found")
    if kind is JobKind.MIGRATE:
        await _check_target(session, workflow, options)
    chosen = list(dict.fromkeys(instance_ids))
    if not 1 <= len(chosen) <= MAX_INSTANCES:
        raise ValidationFailed(code="job_size", params={"max": MAX_INSTANCES})
    theirs = await session.scalar(
        select(func.count())
        .select_from(WorkflowInstance)
        .where(WorkflowInstance.id.in_(chosen), WorkflowInstance.workflow_id == workflow_id)
    )
    if theirs != len(chosen):  # another workflow's run, or one not visible in this tenant
        raise ValidationFailed(
            code="instances_not_in_workflow", params={"count": len(chosen) - int(theirs or 0)}
        )
    job = WorkflowJob(
        tenant_id=workflow.tenant_id,
        workflow_id=workflow_id,
        kind=kind.value,
        instance_ids=chosen,
        options=options,
        status=JobStatus.QUEUED.value,
        total=len(chosen),
        dry_run=dry_run,
    )
    session.add(job)
    await session.flush()
    await _progress(session, job)
    return job


async def _check_target(session: AsyncSession, workflow: Workflow, options: dict[str, Any]) -> None:
    """A migration names a published version of the same workflow."""
    found = await session.get(
        WorkflowVersion, (workflow.tenant_id, workflow.id, int(options["to_version"]))
    )
    if found is None:
        raise NotFound(code="workflow_version_not_found")


async def _progress(session: AsyncSession, job: WorkflowJob) -> None:
    await record_event(
        session,
        WorkflowJobProgressed(
            job_id=job.id,
            workflow_id=job.workflow_id,
            kind=job.kind,  # type: ignore[arg-type]  # checked by the table's kind_code
            status=job.status,  # type: ignore[arg-type]  # checked by the table's status_code
            processed=job.processed,
            total=job.total,
        ),
        aggregate_id=job.id,
    )


# --- the worker -----------------------------------------------------------------------------------


async def run_jobs(database: Database, settings: Settings) -> None:
    """Schedule: every tenant's queued jobs (and any a stopped run left running), oldest first."""
    del settings
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        while (ref := await _next(database, tenant)) is not None:
            try:
                await _run(database, tenant, ref)
            except Exception:  # one broken job must not stop the others; it is logged
                log.exception("workflow_job_failed", job_id=str(ref[0]))
                await _finish(database, tenant, ref, failed=True)


async def _next(database: Database, tenant: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        row = (
            await session.execute(
                select(WorkflowJob.id, WorkflowJob.created_by)
                .where(WorkflowJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)))
                .order_by(WorkflowJob.created_at, WorkflowJob.id)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        if row.created_by is None:  # pragma: no cover - jobs are only asked for by people
            found = await session.get(WorkflowJob, row.id)
            if found is not None:
                found.status = JobStatus.FAILED.value
            return None
    return row.id, row.created_by


async def _run(database: Database, tenant: uuid.UUID, ref: tuple[uuid.UUID, uuid.UUID]) -> None:
    job_id, admin = ref
    context = TenantContext(tenant, admin)  # each instance is the admin's own action
    async with database.tenant_session(context) as session:
        found = await session.get(WorkflowJob, job_id)
        if found is None:  # pragma: no cover - jobs are never deleted
            return
        remaining = found.instance_ids[found.processed :]
        if found.status != JobStatus.RUNNING:
            found.status, found.started_at = JobStatus.RUNNING.value, datetime.now(UTC)
            await _progress(session, found)
    for offset in range(0, len(remaining), BATCH):
        async with database.tenant_session(context) as session:
            await _batch(session, job_id, remaining[offset : offset + BATCH])
    await _finish(database, tenant, ref)


async def _batch(session: AsyncSession, job_id: uuid.UUID, instance_ids: list[uuid.UUID]) -> None:
    job = await session.get(WorkflowJob, job_id, with_for_update=True)
    if job is None:  # pragma: no cover - jobs are never deleted
        return
    results = list(job.results)
    for instance_id in instance_ids:
        outcome = await _one(
            session, JobKind(job.kind), instance_id, job.options, dry_run=job.dry_run
        )
        results.append({"instance_id": str(instance_id), **outcome})
        job.processed += 1
        if outcome["outcome"] == "done":
            job.done_count += 1
        else:
            job.skipped_count += 1
    job.results = results
    job.version += 1
    await _progress(session, job)


async def _one(
    session: AsyncSession,
    kind: JobKind,
    instance_id: uuid.UUID,
    options: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """One instance, in a savepoint: its outcome and, when skipped, the stable code why."""
    try:
        async with session.begin_nested():
            if kind is JobKind.RETRY:
                await workflow_runtime.retry(session, instance_id, expected_version=None)
            elif kind is JobKind.CANCEL:
                reason = str(options.get("reason") or "")
                await workflow_runtime.stop(
                    session, instance_id, reason=reason, expected_version=None
                )
            else:
                await workflow_runtime.migrate(
                    session,
                    instance_id,
                    to_version=int(options["to_version"]),
                    mapping=dict(options.get("mapping") or {}),
                    dry_run=dry_run,
                )
                if dry_run:
                    return {"outcome": "would_move"}
    except AppError as refused:  # the instance's own state said no: the job goes on
        return {"outcome": "skipped", "code": refused.instance_code}
    return {"outcome": "done"}


async def _finish(
    database: Database, tenant: uuid.UUID, ref: tuple[uuid.UUID, uuid.UUID], *, failed: bool = False
) -> None:
    async with database.tenant_session(TenantContext(tenant, ref[1])) as session:
        found = await session.get(WorkflowJob, ref[0], with_for_update=True)
        if found is None or found.status in {JobStatus.DONE, JobStatus.FAILED}:
            return
        found.status = (JobStatus.FAILED if failed else JobStatus.DONE).value
        found.finished_at = datetime.now(UTC)
        found.version += 1
        await _progress(session, found)
