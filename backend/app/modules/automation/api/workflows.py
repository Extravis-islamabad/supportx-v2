"""The workflow API (WP-048b S1): design, publish, switch, start on a record, instances.

`workflows.manage` designs, publishes and switches; `workflows.run` starts a workflow on a record
(REQ-WF-010) and reads instances. Every route sits behind the `workflows` licence feature (rule f).
Drafts answer with their problems, each naming the node or link it is about (REQ-WF-019 AC2).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules.audit import audited
from app.modules.automation.domain.interpreter import InstanceStatus
from app.modules.automation.domain.workflows import Problem
from app.modules.automation.infra.models import (
    Workflow,
    WorkflowInstance,
    WorkflowJob,
    WorkflowStep,
)
from app.modules.automation.service import workflow_admin, workflow_jobs, workflow_runtime
from app.modules.automation.service.registry import record_type as registered
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, list_query, paginate

router = APIRouter(prefix="/automation/workflows", tags=["automation"])
Manage = Annotated[Subject, Depends(require_permission("workflows.manage"))]
Run = Annotated[Subject, Depends(require_permission("workflows.run"))]


class WorkflowIn(BaseModel):
    """A new workflow: its record type and name (it starts as a start-to-end draft)."""

    record_type: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProblemOut(BaseModel):
    """One problem of a draft: what it is about (`node:<id>`, `link:<n>`), a code, its values."""

    where: str
    code: str
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowOut(BaseModel):
    """A workflow with its draft and the draft's problems."""

    id: uuid.UUID
    record_type: str
    name: str
    description: str | None
    draft: dict[str, Any]
    problems: list[ProblemOut] = Field(default_factory=list)
    enabled: bool
    published_version: int | None
    start_templates: list[uuid.UUID] = Field(
        default_factory=list, description="Templates whose new records start it (REQ-WF-010)."
    )
    version: int


class StartTemplatesIn(BaseModel):
    """The templates whose new records start this workflow."""

    template_ids: list[uuid.UUID] = Field(max_length=200)


class DraftIn(BaseModel):
    """The whole draft definition, as the designer holds it."""

    definition: dict[str, Any]


class EnabledIn(BaseModel):
    """On or off."""

    enabled: bool


class StartIn(BaseModel):
    """Start a workflow on one record (REQ-WF-010: by hand, with permission)."""

    record_id: uuid.UUID


class StopIn(BaseModel):
    """Stop a workflow on a record: always with a reason (REQ-WF-026 AC1)."""

    reason: str = Field(min_length=1, max_length=workflow_runtime.STOP_REASON_MAX)


class RestartIn(BaseModel):
    """Run it again: from the start, or from a chosen node (REQ-WF-026 AC2)."""

    node: str | None = Field(default=None, min_length=1, max_length=40)


class InstanceOut(BaseModel):
    """One run: where it is, and why it stopped if it did (REQ-WF-023, -024)."""

    id: uuid.UUID
    workflow_id: uuid.UUID
    version_number: int
    record_type: str
    record_id: uuid.UUID
    status: Literal["running", "waiting", "failed", "finished", "cancelled"]
    failure: dict[str, Any] | None
    wake_at: datetime | None
    started_how: str
    started_at: datetime
    finished_at: datetime | None
    stopped_reason: str | None = None  # why it was stopped: the person's words, or a code
    version: int


class StepOut(BaseModel):
    """One line of an instance's log (REQ-WF-023 AC2)."""

    seq: int
    node: str
    node_type: str
    result: str
    at: datetime
    detail: dict[str, Any] | None


def _problems(found: list[Problem]) -> list[ProblemOut]:
    return [ProblemOut(where=w, code=c, params=dict(p)) for w, c, p in found]


def _out(workflow: Workflow, problems: list[Problem] | None = None) -> WorkflowOut:
    return WorkflowOut(
        id=workflow.id,
        record_type=workflow.record_type,
        name=workflow.name,
        description=workflow.description,
        draft=dict(workflow.draft),
        problems=_problems(problems or []),
        enabled=workflow.enabled,
        published_version=workflow.published_version,
        start_templates=list(workflow.start_templates or []),
        version=workflow.version,
    )


def _instance(row: WorkflowInstance) -> InstanceOut:
    return InstanceOut.model_validate(row, from_attributes=True)


@router.get("", summary="Workflows of a record type")
async def list_workflows(
    session: TenantSession,
    subject: Manage,
    record_type: Annotated[str, Query(min_length=1, max_length=20)],
) -> list[WorkflowOut]:
    """Drafts, disabled and enabled ones, by name."""
    del subject
    rows = await session.scalars(
        select(Workflow)
        .where(Workflow.record_type == record_type, Workflow.deleted_at.is_(None))
        .order_by(Workflow.name)
    )
    return [_out(w) for w in rows]


@router.post("", summary="Add a workflow", status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: WorkflowIn, session: TenantSession, subject: Manage, idempotency: Idempotency
) -> Response:
    """It starts as a draft from start to end, disabled and not yet published."""
    del subject

    async def operation() -> Created:
        made = await workflow_admin.create_workflow(
            session, record_type=body.record_type, name=body.name, description=body.description
        )
        return Created(_out(made), {"ETag": f'"{made.version}"'})

    return await idempotency.run(body, operation)


INSTANCE_FIELDS = ResourceFields(
    name="workflow_instances",
    fields={
        "workflow_id": FilterField(WorkflowInstance.workflow_id, FieldType.UUID),
        "status": FilterField(
            WorkflowInstance.status,
            FieldType.ENUM,
            values=frozenset(s.value for s in InstanceStatus),
        ),
        "record_type": FilterField(WorkflowInstance.record_type, FieldType.STRING),
        "started_at": FilterField(
            WorkflowInstance.started_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        # "Waiting longer than": the last time it moved (REQ-WF-025 AC3).
        "updated_at": FilterField(
            WorkflowInstance.updated_at, FieldType.DATETIME, sortable=True, simple=False
        ),
    },
    id_column=WorkflowInstance.id,
    default_sort=("-started_at",),
)
InstancesQuery = Annotated[
    ListQuery, Depends(list_query(INSTANCE_FIELDS, extra_parameters=frozenset({"node"})))
]


@router.get("/instances", summary="Every workflow run: the overview")
async def overview(
    session: TenantSession,
    query: InstancesQuery,
    subject: Manage,
    node: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
) -> Page[InstanceOut]:
    """Runs by workflow, state and age, failed ones with their node and error (REQ-WF-025).

    `node=` keeps the runs that have a step there now (a waiting or failed token).
    """
    del subject
    statement = select(WorkflowInstance)
    if node is not None:
        statement = statement.where(WorkflowInstance.state["tokens"].contains([{"node": node}]))
    page = await paginate(session, statement, query)
    return Page[InstanceOut](
        items=[_instance(row) for row in page.rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


@router.get("/{workflow_id}", summary="One workflow, with its draft's problems")
async def get_workflow(
    workflow_id: uuid.UUID, response: Response, session: TenantSession, subject: Manage
) -> WorkflowOut:
    """The draft as last saved and every problem it has now."""
    del subject
    found = await session.get(Workflow, workflow_id)
    if found is None or found.deleted_at is not None:
        raise NotFound(code="workflow_not_found")
    set_etag(response, found.version)
    problems = await workflow_admin.problems_of(session, found.record_type, found.draft, found.id)
    return _out(found, problems)


@router.put("/{workflow_id}/draft", summary="Save the draft (problems and all)")
async def save_draft(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    workflow_id: uuid.UUID,
    body: DraftIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
) -> WorkflowOut:
    """Saved whatever its problems; they come back for the canvas to mark (REQ-WF-019)."""
    del subject
    saved, problems = await workflow_admin.save_draft(
        session, workflow_id, expected_version=version, definition=body.definition
    )
    set_etag(response, saved.version)
    return _out(saved, problems)


@router.post("/{workflow_id}/publish", summary="Publish the draft as the next version")
async def publish(
    workflow_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Manage
) -> WorkflowOut:
    """Refused while the draft has problems (422 workflow_has_problems)."""
    del subject
    await workflow_admin.publish(session, workflow_id, expected_version=version)
    found = await session.get(Workflow, workflow_id)
    assert found is not None  # just published  # noqa: S101
    return _out(found)


@router.put("/{workflow_id}/start-templates", summary="Templates that start the workflow")
async def set_start_templates(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    workflow_id: uuid.UUID,
    body: StartTemplatesIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
) -> WorkflowOut:
    """A record made from one of them starts the workflow, when it is on (REQ-WF-010 AC1)."""
    del subject
    changed = await workflow_admin.set_start_templates(
        session, workflow_id, expected_version=version, template_ids=body.template_ids
    )
    set_etag(response, changed.version)
    return _out(changed)


@router.put("/{workflow_id}/enabled", summary="Switch a workflow on or off")
async def set_enabled(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    workflow_id: uuid.UUID,
    body: EnabledIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
) -> WorkflowOut:
    """Off: no new instances; running ones keep going (REQ-WF-010 AC3)."""
    del subject
    changed = await workflow_admin.set_enabled(
        session, workflow_id, expected_version=version, enabled=body.enabled
    )
    set_etag(response, changed.version)
    return _out(changed)


@router.post("/{workflow_id}/instances", summary="Start a workflow on a record", status_code=201)
async def start(
    workflow_id: uuid.UUID,
    body: StartIn,
    session: TenantSession,
    subject: Run,
    idempotency: Idempotency,
) -> Response:
    """409 workflow_already_running while one runs on the record (REQ-WF-010 AC2).

    The person must be able to edit the record too (ADR-043 §10).
    """
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None or workflow.deleted_at is not None:
        raise NotFound(code="workflow_not_found")
    await _editable(session, subject, workflow.record_type, body.record_id)

    async def operation() -> Created:
        made = await workflow_runtime.start(
            session,
            workflow_id=workflow_id,
            record_type=workflow.record_type,
            record_id=body.record_id,
            how="manual",
        )
        return Created(_instance(made), {"ETag": f'"{made.version}"'})

    return await idempotency.run(body, operation)


@router.get("/{workflow_id}/instances", summary="A workflow's instances")
async def list_instances(
    workflow_id: uuid.UUID, session: TenantSession, subject: Run
) -> list[InstanceOut]:
    """Newest first (the overview screen comes with session 3)."""
    del subject
    rows = await session.scalars(
        select(WorkflowInstance)
        .where(WorkflowInstance.workflow_id == workflow_id)
        .order_by(WorkflowInstance.started_at.desc())
        .limit(200)
    )
    return [_instance(r) for r in rows]


@router.get("/instances/{instance_id}/steps", summary="An instance's log")
async def steps(instance_id: uuid.UUID, session: TenantSession, subject: Run) -> list[StepOut]:
    """Every node run with its result and time (REQ-WF-023 AC2)."""
    del subject
    rows = await session.scalars(
        select(WorkflowStep)
        .where(WorkflowStep.instance_id == instance_id)
        .order_by(WorkflowStep.seq)
    )
    return [StepOut.model_validate(r, from_attributes=True) for r in rows]


async def _editable(
    session: TenantSession, subject: Subject, record_type: str, record_id: uuid.UUID
) -> None:
    """Running, stopping or restarting a workflow on a record needs the right to edit it too."""
    kind = registered(record_type)
    if (
        kind is None
        or kind.may_edit is None
        or not await kind.may_edit(session, subject, record_id)
    ):
        raise PermissionDenied(code="record_not_editable")


async def _instance_to_act_on(
    session: TenantSession, subject: Subject, instance_id: uuid.UUID
) -> WorkflowInstance:
    instance = await session.get(WorkflowInstance, instance_id)
    if instance is None:
        raise NotFound(code="workflow_instance_not_found")
    await _editable(session, subject, instance.record_type, instance.record_id)
    return instance


@router.post(
    "/instances/{instance_id}/stop",
    summary="Stop a workflow on a record, with a reason",
    dependencies=[
        audited(
            "automation.workflow_stopped",
            object_type="workflow_instance",
            object_param="instance_id",
        )
    ],
)
async def stop_instance(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    instance_id: uuid.UUID,
    body: StopIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Run,
) -> InstanceOut:
    """Its log stays readable; the record goes on through its life cycle (REQ-WF-026)."""
    await _instance_to_act_on(session, subject, instance_id)
    stopped = await workflow_runtime.stop(
        session, instance_id, reason=body.reason.strip(), expected_version=version
    )
    set_etag(response, stopped.version)
    return _instance(stopped)


@router.post(
    "/instances/{instance_id}/restart",
    summary="Run a workflow on a record again, from the start or a chosen node",
    dependencies=[
        audited(
            "automation.workflow_restarted",
            object_type="workflow_instance",
            object_param="instance_id",
        )
    ],
)
async def restart_instance(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    instance_id: uuid.UUID,
    body: RestartIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Run,
) -> InstanceOut:
    """A stopped, failed or finished run, on its own version; history records it."""
    await _instance_to_act_on(session, subject, instance_id)
    again = await workflow_runtime.restart(
        session, instance_id, node=body.node, expected_version=version
    )
    set_etag(response, again.version)
    return _instance(again)


@router.post(
    "/instances/{instance_id}/retry",
    summary="Run a failed workflow's failed step again",
    dependencies=[
        audited(
            "automation.workflow_retried",
            object_type="workflow_instance",
            object_param="instance_id",
        )
    ],
)
async def retry_instance(
    instance_id: uuid.UUID,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Run,
) -> InstanceOut:
    """REQ-WF-025 AC2, one at a time (the overview's bulk retry is a background job)."""
    await _instance_to_act_on(session, subject, instance_id)
    again = await workflow_runtime.retry(session, instance_id, expected_version=version)
    set_etag(response, again.version)
    return _instance(again)


# --- the overview and bulk jobs (WP-048b S3b; REQ-WF-025) -------------------------------------


class JobIn(BaseModel):
    """A bulk retry or cancel over chosen runs of one workflow (REQ-WF-025 AC2)."""

    kind: Literal["retry", "cancel"]
    instance_ids: list[uuid.UUID] = Field(min_length=1, max_length=workflow_jobs.MAX_INSTANCES)
    # Cancelling asks for a reason, as stopping one run does (REQ-WF-026 AC1).
    reason: str | None = Field(
        default=None, min_length=1, max_length=workflow_runtime.STOP_REASON_MAX
    )


class JobOut(BaseModel):
    """A job's progress, and each run's result once it is done."""

    id: uuid.UUID
    workflow_id: uuid.UUID
    kind: Literal["retry", "cancel", "migrate"]
    status: Literal["queued", "running", "done", "failed"]
    total: int
    processed: int
    done_count: int
    skipped_count: int
    results: list[dict[str, Any]]
    created_at: datetime
    finished_at: datetime | None
    version: int


def _job(row: WorkflowJob) -> JobOut:
    return JobOut.model_validate(row, from_attributes=True)


@router.post(
    "/{workflow_id}/jobs",
    summary="Retry or cancel many runs, as a background job",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        audited(
            "automation.workflow_job_queued", object_type="workflow", object_param="workflow_id"
        )
    ],
)
async def queue_job(
    workflow_id: uuid.UUID,
    body: JobIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
) -> Response:
    """The worker runs it in batches; its progress reaches the overview live."""
    del subject
    if body.kind == "cancel" and not (body.reason or "").strip():
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.reason", code="required", message_key="errors.field.required"
                )
            ]
        )

    async def operation() -> Created:
        job = await workflow_jobs.create(
            session,
            workflow_id=workflow_id,
            kind=workflow_jobs.JobKind(body.kind),
            instance_ids=body.instance_ids,
            options={"reason": body.reason.strip()} if body.reason else {},
        )
        return Created(_job(job), {"ETag": f'"{job.version}"'})

    return await idempotency.run(body, operation, status_code=status.HTTP_202_ACCEPTED)


@router.get("/jobs/{job_id}", summary="A job's progress and results")
async def get_job(job_id: uuid.UUID, session: TenantSession, subject: Manage) -> JobOut:
    """Each run's outcome: done, or skipped with the code why (the overview lists them)."""
    del subject
    job = await session.get(WorkflowJob, job_id)
    if job is None:
        raise NotFound(code="workflow_job_not_found")
    return _job(job)
