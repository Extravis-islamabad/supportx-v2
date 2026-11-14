"""The workflow API (WP-048b S1): design, publish, switch, start on a record, instances.

`workflows.manage` designs, publishes and switches; `workflows.run` starts a workflow on a record
(REQ-WF-010) and reads instances. Every route sits behind the `workflows` licence feature (rule f).
Drafts answer with their problems, each naming the node or link it is about (REQ-WF-019 AC2).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from app.core.authorization import require_permission
from app.core.body_limit import body_limit
from app.core.database import TenantSession
from app.core.errors import FieldError, NotFound, PermissionDenied, ValidationFailed
from app.core.recent_auth import RecentAuth
from app.modules.audit import AuditNote, audited
from app.modules.automation.domain.interpreter import InstanceStatus
from app.modules.automation.domain.workflows import (
    Category,
    NodeType,
    Problem,
    WaitEvent,
    masked,
    ports_of,
)
from app.modules.automation.infra.models import (
    Workflow,
    WorkflowInstance,
    WorkflowJob,
    WorkflowStep,
    WorkflowTestRun,
    WorkflowVersion,
)
from app.modules.automation.service import (
    workflow_admin,
    workflow_jobs,
    workflow_runtime,
    workflow_tests,
)
from app.modules.automation.service.registry import record_type as registered
from app.modules.identity_access import (
    PolicyService,
    ServiceRolesOut,
    Subject,
    get_policy,
    service_roles_out,
)
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, list_query, paginate
from app.shared.api.ratelimit import rate_limit

# Every workflow route counts against its own budget (audit #14; architecture.md §10).
router = APIRouter(
    prefix="/automation/workflows",
    tags=["automation"],
    dependencies=[Depends(rate_limit("workflows"))],
)
Manage = Annotated[Subject, Depends(require_permission("workflows.manage"))]
Run = Annotated[Subject, Depends(require_permission("workflows.run"))]
Policy = Annotated[PolicyService, Depends(get_policy)]


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
    running: int = Field(default=0, description="Live runs (REQ-WF-027: the list shows it).")
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


class RecordLabelOut(BaseModel):
    """A run's record as people name it; only for a record the viewer may see (WP-048b S5a)."""

    display_id: str
    subject: str


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
    # The runs overview fills these (WP-048b S5a); added as optional, the contract stays.
    record: RecordLabelOut | None = Field(
        default=None, description="None: not given here, or the viewer may not see the record."
    )
    workflow_name: str | None = None
    current_nodes: list[str] | None = Field(default=None, description="Where it is now.")


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
        draft=masked(workflow.draft),  # header values are write-only (#406)
        problems=_problems(problems or []),
        enabled=workflow.enabled,
        published_version=workflow.published_version,
        start_templates=list(workflow.start_templates or []),
        version=workflow.version,
    )


def _instance(row: WorkflowInstance) -> InstanceOut:
    return InstanceOut.model_validate(row, from_attributes=True)


class NodeTypeOut(BaseModel):
    """One palette entry (REQ-WF-009 AC3): shown in its group by name, never only an icon."""

    type: NodeType
    category: Category = Field(description="The palette group (REQ-WF-028).")
    available: bool = Field(description="False: offered for the type, not usable now.")
    why_not: str | None = Field(description="Why not, as a problem code with its label.")
    outputs: list[str] = Field(description="Its outputs with an empty config.")
    optional: list[str] = Field(description="Outputs it may leave unlinked.")
    roles: list[str] = Field(
        default_factory=list,
        description="An approval's choice of the record's roles (empty for other types).",
    )


@router.get("/node-types", summary="The designer's palette for a record type")
async def node_types(
    session: TenantSession,
    subject: Manage,
    record_type: Annotated[str, Query(min_length=1, max_length=20)],
) -> list[NodeTypeOut]:
    """Every node type the record type offers, with whether it can be used now (WP-048b S4)."""
    del subject
    return [
        NodeTypeOut(
            type=o.type,
            category=o.category,
            available=o.available,
            why_not=o.why_not,
            outputs=list(o.outputs),
            optional=sorted(o.optional),
            roles=list(o.roles),
        )
        for o in await workflow_admin.node_types(session, record_type)
    ]


NODE_PORTS_MAX = 200  # a workflow's node limit (Appendix A)


class NodeConfigIn(BaseModel):
    """A node as the designer holds it: its type and config, not yet saved."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=30)
    config: dict[str, Any] = Field(default_factory=dict)


class NodePortsIn(BaseModel):
    """The nodes whose outputs the canvas needs, in order."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[NodeConfigIn] = Field(max_length=NODE_PORTS_MAX)


class NodePortsOut(BaseModel):
    """One node's outputs, as validation sees them (a switch's cases, a wait's timeout)."""

    outputs: list[str]
    optional: list[str]


@router.post("/node-ports", summary="The outputs of nodes being designed")
async def node_ports(body: NodePortsIn, subject: Manage) -> list[NodePortsOut]:
    """Changes nothing: the same registry as validation, so the canvas offers what saves."""
    del subject
    found = [ports_of(n.type, n.config) for n in body.nodes]
    return [NodePortsOut(outputs=list(o), optional=sorted(opt)) for o, opt in found]


@router.get("", summary="Workflows of a record type")
async def list_workflows(
    session: TenantSession,
    subject: Manage,
    record_type: Annotated[str, Query(min_length=1, max_length=20)],
) -> list[WorkflowOut]:
    """Drafts, disabled and enabled ones, by name."""
    del subject
    rows = list(
        await session.scalars(
            select(Workflow)
            .where(Workflow.record_type == record_type, Workflow.deleted_at.is_(None))
            .order_by(Workflow.name)
        )
    )
    grouped = await session.execute(
        select(WorkflowInstance.workflow_id, func.count())
        .where(
            WorkflowInstance.workflow_id.in_([w.id for w in rows]),
            WorkflowInstance.status.in_(
                (InstanceStatus.RUNNING.value, InstanceStatus.WAITING.value)
            ),
        )
        .group_by(WorkflowInstance.workflow_id)
    )
    running = {flow: int(count) for flow, count in grouped.all()}
    return [_out(w).model_copy(update={"running": running.get(w.id, 0)}) for w in rows]


@router.post(
    "",
    summary="Add a workflow",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowOut,
)
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


IMPORT_MAX_BYTES = 1_000_000  # a workflow file's ceiling (the parser's size cap)


class WorkflowFileIn(BaseModel):
    """A workflow file exported here (REQ-WF-027 AC2): checked before anything is read."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["supportx.workflow"]
    format_version: Literal[1]
    tenant_id: uuid.UUID
    record_type: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=workflow_admin.NAME_MAX)
    description: str | None = Field(default=None, max_length=2000)
    definition: dict[str, Any]
    start_templates: list[uuid.UUID] = Field(default_factory=list, max_length=200)


def _too_large() -> ValidationFailed:
    return ValidationFailed(code="workflow_file_too_large", params={"max": IMPORT_MAX_BYTES})


async def _workflow_file(request: Request) -> WorkflowFileIn:
    """The file, size-capped before a byte of it is parsed (lane B's review of #374).

    The declared length is refused first; the body is then read in chunks and stops at the cap,
    whatever the header said. Only then is it parsed against the closed schema.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > IMPORT_MAX_BYTES:
        raise _too_large()
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > IMPORT_MAX_BYTES:
            raise _too_large()
    try:
        return WorkflowFileIn.model_validate_json(bytes(raw))
    except PydanticValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False)) from exc


@router.post(
    "/import",
    summary="Import a workflow file as a new draft",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowOut,
    # Room past its own 1 MB check, so an oversized file gets its own 422, not the cap's 413.
    dependencies=[
        Depends(body_limit(2 * 1024 * 1024)),
        audited("automation.workflow_imported", object_type="workflow"),
    ],
    # The body is read by `_workflow_file` (capped before parsing); its schema stays documented.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": WorkflowFileIn.model_json_schema()}},
        }
    },
)
async def import_workflow(
    subject: Manage,  # first: nobody else's file is ever read
    session: TenantSession,
    idempotency: Idempotency,
    body: Annotated[WorkflowFileIn, Depends(_workflow_file)],
) -> Response:
    """Same tenant only; it arrives disabled, with its problems to fix (REQ-WF-019)."""
    del subject

    async def operation() -> Created:
        made, problems = await workflow_admin.import_workflow(
            session,
            tenant_id=body.tenant_id,
            record_type=body.record_type,
            name=body.name,
            description=body.description,
            definition=body.definition,
            start_templates=body.start_templates,
        )
        return Created(_out(made, problems), {"ETag": f'"{made.version}"'})

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
        # The runs still on one version: what a migration moves (WP-048b S5c).
        "version_number": FilterField(WorkflowInstance.version_number, FieldType.INTEGER),
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
    ListQuery,
    Depends(
        list_query(INSTANCE_FIELDS, extra_parameters=frozenset({"node", "waiting_over_hours"}))
    ),
]
WAITING_OVER_MAX = 24 * 366  # a year, in hours


@router.get("/instances", summary="Every workflow run: the overview")
async def overview(
    session: TenantSession,
    query: InstancesQuery,
    subject: Manage,
    node: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    waiting_over_hours: Annotated[int | None, Query(ge=1, le=WAITING_OVER_MAX)] = None,
) -> Page[InstanceOut]:
    """Runs by workflow, state and age, failed ones with their node and error (REQ-WF-025).

    `node=` keeps the runs that have a step there now (a waiting or failed token).
    `waiting_over_hours=` keeps the live runs that have not moved for that long (AC3): their
    latest step is older. The latest step is read on the steps' primary key (tenant_id,
    instance_id, seq) backwards, one row per run, so no index is added.
    """
    statement = select(WorkflowInstance)
    if node is not None:
        statement = statement.where(WorkflowInstance.state["tokens"].contains([{"node": node}]))
    if waiting_over_hours is not None:
        latest = (
            select(WorkflowStep.at)
            .where(
                WorkflowStep.tenant_id == WorkflowInstance.tenant_id,
                WorkflowStep.instance_id == WorkflowInstance.id,
            )
            .order_by(WorkflowStep.seq.desc())
            .limit(1)
            .correlate(WorkflowInstance)
            .scalar_subquery()
        )
        cutoff = datetime.now(UTC) - timedelta(hours=waiting_over_hours)
        statement = statement.where(
            WorkflowInstance.status.in_(
                (InstanceStatus.RUNNING.value, InstanceStatus.WAITING.value)
            ),
            latest < cutoff,
        )
    page = await paginate(session, statement, query)
    return Page[InstanceOut](
        items=await _named(session, subject, list(page.rows)),
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


async def _named(
    session: TenantSession, subject: Subject, rows: list[WorkflowInstance]
) -> list[InstanceOut]:
    """Each run with its record's name, only where the viewer may see the record.

    workflows.manage lists every run of the tenant (ADR-043 §10), but a record's ID and subject
    are the record's own data: they follow the record type's view rule (the coordinator, S5).
    """
    visible: dict[str, set[uuid.UUID]] = {}
    for row in rows:
        kind = registered(row.record_type)
        if (
            kind is not None
            and kind.may_view is not None
            and await kind.may_view(session, subject, row.record_id)
        ):
            visible.setdefault(row.record_type, set()).add(row.record_id)
    names: dict[uuid.UUID, tuple[str, str]] = {}
    for record_type, ids in visible.items():
        kind = registered(record_type)
        if kind is not None and kind.labels is not None:
            names.update(await kind.labels(session, sorted(ids)))
    flows = {
        w.id: w.name
        for w in await session.scalars(
            select(Workflow).where(Workflow.id.in_({r.workflow_id for r in rows}))
        )
    }
    out = []
    for row in rows:
        name = names.get(row.record_id)
        out.append(
            _instance(row).model_copy(
                update={
                    "workflow_name": flows.get(row.workflow_id, ""),
                    "current_nodes": _current(row.state),
                    "record": None
                    if name is None
                    else RecordLabelOut(display_id=name[0], subject=name[1]),
                }
            )
        )
    return out


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
    saved, problems = await workflow_admin.save_draft(
        session, workflow_id, expected_version=version, definition=body.definition, author=subject
    )
    set_etag(response, saved.version)
    return _out(saved, problems)


@router.post("/{workflow_id}/publish", summary="Publish the draft as the next version")
async def publish(
    workflow_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Manage
) -> WorkflowOut:
    """Refused while the draft has problems (422 workflow_has_problems)."""
    await workflow_admin.publish(
        session, workflow_id, expected_version=version, by=subject.user_id, author=subject
    )
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


async def _visible(
    session: TenantSession, subject: Subject, record_type: str, record_id: uuid.UUID
) -> None:
    """A record's workflows are shown only to someone who may see the record (REQ-WF-023 AC3).

    Its type's own view rule decides, as on the record's page; anything else is a 404, so a
    record that cannot be seen is not even confirmed to exist.
    """
    kind = registered(record_type)
    if (
        kind is None
        or kind.may_view is None
        or not await kind.may_view(session, subject, record_id)
    ):
        raise NotFound(code="record_not_found")


STEPS_MAX = 500  # a record panel's log: the latest steps of one run


async def _steps_of(session: TenantSession, instance_id: uuid.UUID) -> list[StepOut]:
    rows = await session.scalars(
        select(WorkflowStep)
        .where(WorkflowStep.instance_id == instance_id)
        .order_by(WorkflowStep.seq.desc())
        .limit(STEPS_MAX)
    )
    return [StepOut.model_validate(r, from_attributes=True) for r in reversed(list(rows))]


@router.get("/instances/{instance_id}/steps", summary="An instance's log")
async def steps(instance_id: uuid.UUID, session: TenantSession, subject: Run) -> list[StepOut]:
    """Every node run with its result and time (REQ-WF-023 AC2), for those who see the record."""
    instance = await session.get(WorkflowInstance, instance_id)
    if instance is None:
        raise NotFound(code="workflow_instance_not_found")
    await _visible(session, subject, instance.record_type, instance.record_id)
    return await _steps_of(session, instance_id)


def _diagram(definition: dict[str, Any]) -> dict[str, Any]:
    """What the record panel draws: steps and links, never their settings (lane B's #379 review).

    A step's settings can hold secrets (a webhook's URL and headers, a function's inputs) that
    only workflows.manage may read; workflows.run holders see the shape of the run alone.
    """
    nodes = definition.get("nodes")
    links = definition.get("links")
    return {
        "format": definition.get("format"),
        "nodes": [
            {"id": n.get("id"), "type": n.get("type"), "config": {}, "position": n.get("position")}
            for n in (nodes if isinstance(nodes, list) else [])
            if isinstance(n, dict)
        ],
        "links": [
            {"from": li.get("from"), "port": li.get("port"), "to": li.get("to")}
            for li in (links if isinstance(links, list) else [])
            if isinstance(li, dict)
        ],
        "variables": [],
    }


class RecordWorkflowOut(BaseModel):
    """One workflow run on a record, everything its panel draws (REQ-WF-023, -024)."""

    instance: InstanceOut
    workflow_name: str
    definition: dict[str, Any] = Field(
        description="The version's steps and links to draw, without their settings."
    )
    current_nodes: list[str] = Field(description="Where it is now (marked on the diagram).")
    steps: list[StepOut] = Field(description=f"Its log, oldest first (the last {STEPS_MAX}).")


@router.get(
    "/records/{record_type}/{record_id}",
    summary="The workflows on a record, for its Workflows panel",
)
async def record_workflows(
    record_type: Annotated[str, Path(min_length=1, max_length=20)],
    record_id: uuid.UUID,
    session: TenantSession,
    subject: Run,
) -> list[RecordWorkflowOut]:
    """Newest first: each run with its diagram, position and log.

    Requesters never get here (workflows.run), and nobody sees the runs of a record they
    cannot see (404).
    """
    await _visible(session, subject, record_type, record_id)
    rows = list(
        await session.scalars(
            select(WorkflowInstance)
            .where(
                WorkflowInstance.record_type == record_type,
                WorkflowInstance.record_id == record_id,
            )
            .order_by(WorkflowInstance.started_at.desc())
            .limit(50)
        )
    )
    found = []
    for row in rows:
        flow = await session.get(Workflow, row.workflow_id)
        version = await session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == row.workflow_id,
                WorkflowVersion.number == row.version_number,
            )
        )
        found.append(
            RecordWorkflowOut(
                instance=_instance(row),
                workflow_name=flow.name if flow is not None else "",
                definition=_diagram(dict(version.definition)) if version is not None else {},
                current_nodes=_current(row.state),
                steps=await _steps_of(session, row.id),
            )
        )
    return found


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


@router.post("/instances/{instance_id}/skip", summary="Skip a failed workflow's failed step")
async def skip_instance(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    instance_id: uuid.UUID,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Run,
    note: Annotated[
        AuditNote,
        audited(
            "automation.workflow_skipped",
            object_type="workflow_instance",
            object_param="instance_id",
        ),
    ],
) -> InstanceOut:
    """REQ-WF-024 AC2: on with the failed step's "next" output only.

    Audited with the step and the record; needs the right to edit the record, as retry does.
    """
    instance = await _instance_to_act_on(session, subject, instance_id)
    again, node = await workflow_runtime.skip(session, instance_id, expected_version=version)
    note.details = {
        **note.details,
        "node": node,
        "record_type": instance.record_type,
        "record_id": str(instance.record_id),
    }
    set_etag(response, again.version)
    return _instance(again)


# --- the overview and bulk jobs (WP-048b S3b; REQ-WF-025) -------------------------------------


class JobIn(BaseModel):
    """A bulk retry, cancel or migration over chosen runs of one workflow (REQ-WF-021, -025)."""

    kind: Literal["retry", "cancel", "migrate"]
    instance_ids: list[uuid.UUID] = Field(min_length=1, max_length=workflow_jobs.MAX_INSTANCES)
    # A migration (REQ-WF-021): the version to move to, old node → new node where the IDs
    # differ, and a dry run that says what would move and changes nothing.
    to_version: int | None = Field(default=None, ge=1)
    mapping: dict[str, str] = Field(default_factory=dict, max_length=200)
    dry_run: bool = False
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


def _options(body: JobIn) -> dict[str, Any]:
    if body.kind == "migrate":
        return {"to_version": body.to_version, "mapping": body.mapping}
    return {"reason": body.reason.strip()} if body.reason else {}


def _job(row: WorkflowJob) -> JobOut:
    return JobOut.model_validate(row, from_attributes=True)


@router.post(
    "/{workflow_id}/jobs",
    summary="Retry or cancel many runs, as a background job",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobOut,
)
async def queue_job(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    workflow_id: uuid.UUID,
    body: JobIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[
        AuditNote,
        audited(
            "automation.workflow_job_queued", object_type="workflow", object_param="workflow_id"
        ),
    ],
) -> Response:
    """The worker runs it in batches; its progress reaches the overview live.

    Audited with what it does to how many runs and, for a cancel, why (the coordinator, S5).
    """
    del subject
    note.details = {
        **note.details,
        "kind": body.kind,
        "runs": len(body.instance_ids),
        "dry_run": body.dry_run,
        "to_version": body.to_version,
        "reason": (body.reason or "").strip() or None,
    }
    if body.kind == "migrate" and body.to_version is None:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.to_version", code="required", message_key="errors.field.required"
                )
            ]
        )
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
            options=_options(body),
            dry_run=body.dry_run,
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


class WorkflowVersionOut(BaseModel):
    """One published version: who published it and when, and the runs still on it (WF-027)."""

    number: int
    published_at: datetime
    published_by: uuid.UUID | None
    running: int


@router.get("/{workflow_id}/versions", summary="A workflow's published versions")
async def versions(
    workflow_id: uuid.UUID, session: TenantSession, subject: Manage
) -> list[WorkflowVersionOut]:
    """Newest first, with how many runs are live on each (REQ-WF-021, -027)."""
    del subject
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None or workflow.deleted_at is not None:
        raise NotFound(code="workflow_not_found")
    live = (InstanceStatus.RUNNING.value, InstanceStatus.WAITING.value)
    grouped = await session.execute(
        select(WorkflowInstance.version_number, func.count())
        .where(WorkflowInstance.workflow_id == workflow_id, WorkflowInstance.status.in_(live))
        .group_by(WorkflowInstance.version_number)
    )
    counts = {int(number): int(count) for number, count in grouped.all()}
    rows = await session.scalars(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.number.desc())
    )
    return [
        WorkflowVersionOut(
            number=v.number,
            published_at=v.published_at,
            published_by=v.published_by,
            running=int(counts.get(v.number, 0)),
        )
        for v in rows
    ]


@router.get(
    "/{workflow_id}/versions/{number}/occupancy",
    summary="Where a version's live runs are: the migration's preview",
)
async def version_occupancy(
    workflow_id: uuid.UUID, number: int, session: TenantSession, subject: Manage
) -> dict[str, int]:
    """Live runs at each node of the version (REQ-WF-021: the per-node preview)."""
    del subject
    return await workflow_runtime.occupancy(session, workflow_id, number)


class VersionStepOut(BaseModel):
    """One step of a published version: what a migration can map a run's step onto."""

    id: str
    type: NodeType


@router.get(
    "/{workflow_id}/versions/{number}/steps",
    summary="A published version's steps: the migration's targets",
)
async def version_steps(
    workflow_id: uuid.UUID, number: int, session: TenantSession, subject: Manage
) -> list[VersionStepOut]:
    """The steps a run can be moved onto (REQ-WF-021): ids and types, in the version's order."""
    del subject
    found = await session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow_id, WorkflowVersion.number == number
        )
    )
    if found is None:
        raise NotFound(code="workflow_version_not_found")
    nodes = found.definition.get("nodes") if isinstance(found.definition, dict) else None
    return [
        VersionStepOut(id=str(n["id"]), type=NodeType(str(n["type"])))
        for n in (nodes if isinstance(nodes, list) else [])
        if isinstance(n, dict) and n.get("type") in {t.value for t in NodeType}
    ]


class CopyIn(BaseModel):
    """The copy's name, as the screen words it in the admin's language (REQ-WF-027 AC1)."""

    name: str = Field(min_length=1, max_length=workflow_admin.NAME_MAX)


@router.post(
    "/{workflow_id}/copy",
    summary="Copy a workflow as a new draft",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowOut,
    dependencies=[
        audited("automation.workflow_copied", object_type="workflow", object_param="workflow_id")
    ],
)
async def copy_workflow(
    workflow_id: uuid.UUID,
    body: CopyIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
) -> Response:
    """Independent of the original: its own draft, disabled, never published."""
    del subject

    async def operation() -> Created:
        made = await workflow_admin.copy_workflow(session, workflow_id, name=body.name)
        return Created(_out(made), {"ETag": f'"{made.version}"'})

    return await idempotency.run(body, operation)


@router.get(
    "/{workflow_id}/export",
    summary="A workflow as a file",
    dependencies=[
        audited("automation.workflow_exported", object_type="workflow", object_param="workflow_id")
    ],
)
async def export_workflow(
    workflow_id: uuid.UUID, session: TenantSession, subject: Manage
) -> Response:
    """Its draft and start templates, to import here again (REQ-WF-027 AC2)."""
    del subject
    content = await workflow_admin.export_workflow(session, workflow_id)
    return Response(
        content=json.dumps(content, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="workflow-{workflow_id}.json"'},
    )


@router.delete(
    "/{workflow_id}",
    summary="Delete a workflow",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited("automation.workflow_deleted", object_type="workflow", object_param="workflow_id")
    ],
)
async def delete_workflow(
    workflow_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Manage
) -> Response:
    """409 workflow_has_running_instances while runs are live: disable it instead (AC3)."""
    del subject
    await workflow_admin.delete_workflow(session, workflow_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- the run-as identity (ADR-043 §6; the coordinator's plan, 2026-11-11) -----------------------


@router.get("/{workflow_id}/run-as", summary="Who the workflow acts as, and its roles")
async def run_as(
    workflow_id: uuid.UUID, session: TenantSession, subject: Manage, policy: Policy
) -> ServiceRolesOut:
    """Before the first publish there is no identity yet; its roles are none until given."""
    identity = await workflow_admin.run_as_identity(session, workflow_id)
    return await service_roles_out(session, policy, subject, identity)


@router.put(
    "/{workflow_id}/run-as/roles/{role_id}",
    summary="Give the run-as identity a role",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        RecentAuth,
        audited(
            "automation.workflow_run_as_role_added",
            object_type="workflow",
            object_param="workflow_id",
            detail_params=("role_id",),
        ),
    ],
)
async def add_run_as_role(
    workflow_id: uuid.UUID,
    role_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    policy: Policy,
) -> Response:
    """Idempotent, and only roles a run-as identity may hold.

    Never tenant administration, a role managing identities, roles or API keys, or more than
    your own rights (403 with the reason); 409 workflow_not_published before the first publish.
    """
    await workflow_admin.set_run_as_role(session, policy, subject, workflow_id, role_id, held=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{workflow_id}/run-as/roles/{role_id}",
    summary="Take a role from the run-as identity",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited(
            "automation.workflow_run_as_role_removed",
            object_type="workflow",
            object_param="workflow_id",
            detail_params=("role_id",),
        )
    ],
)
async def remove_run_as_role(
    workflow_id: uuid.UUID,
    role_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    policy: Policy,
) -> Response:
    """Idempotent; through the same guarded path."""
    await workflow_admin.set_run_as_role(session, policy, subject, workflow_id, role_id, held=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- test mode (WP-048b S3e; REQ-WF-022) -------------------------------------------------------


class TestRunIn(BaseModel):
    """Test the draft on a record (its facts read once) or on sample values."""

    record_id: uuid.UUID | None = None
    sample: dict[str, Any] | None = Field(default=None, max_length=workflow_tests.SAMPLE_MAX_FIELDS)


class TestRunOut(BaseModel):
    """Where the test run is, what it did, and the commands waiting for an answer."""

    id: uuid.UUID
    workflow_id: uuid.UUID
    record_id: uuid.UUID | None
    status: Literal["running", "waiting", "failed", "finished", "cancelled"]
    facts: dict[str, Any]
    variables: dict[str, Any]
    steps: list[dict[str, Any]]
    pending: list[dict[str, Any]]
    current_nodes: list[str] = Field(
        default_factory=list,
        description="Where the run is now: its live tokens' nodes (the canvas marks them).",
    )
    clock_at: datetime
    live_call: dict[str, Any] | None
    version: int


_LIVE_TOKENS = frozenset({"ready", "waiting", "command", "joined"})


def _current(state: dict[str, Any]) -> list[str]:
    nodes = [str(t.get("node")) for t in state.get("tokens", []) if t.get("state") in _LIVE_TOKENS]
    return sorted(set(nodes))


def _test(row: WorkflowTestRun) -> TestRunOut:
    return TestRunOut(
        id=row.id,
        workflow_id=row.workflow_id,
        record_id=row.record_id,
        status=row.status,  # type: ignore[arg-type]  # checked by the table's status_code
        facts=row.facts,
        variables=dict(row.state.get("variables", {})),
        steps=row.steps,
        pending=row.pending,
        current_nodes=_current(row.state),
        clock_at=row.clock_at,
        live_call=row.live_call,
        version=row.version,
    )


@router.post(
    "/{workflow_id}/test-runs",
    summary="Test the draft, applying nothing",
    status_code=status.HTTP_201_CREATED,
    response_model=TestRunOut,
)
async def start_test(
    workflow_id: uuid.UUID,
    body: TestRunIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
) -> Response:
    """Its commands are shown, never applied; it never writes to the record (REQ-WF-022 AC2)."""

    async def operation() -> Created:
        run = await workflow_tests.start(
            session, subject, workflow_id, record_id=body.record_id, sample=body.sample
        )
        return Created(_test(run), {"ETag": f'"{run.version}"'})

    return await idempotency.run(body, operation)


@router.get("/test-runs/{run_id}", summary="A test run")
async def get_test(run_id: uuid.UUID, session: TenantSession, subject: Manage) -> TestRunOut:
    """Its path so far, its variables and decisions, and what waits for an answer."""
    del subject
    run = await session.get(WorkflowTestRun, run_id)
    if run is None:
        raise NotFound(code="workflow_test_run_not_found")
    return _test(run)


class AnswerIn(BaseModel):
    """The admin's answer to one shown command, or a change, or time moving on."""

    command_id: str | None = Field(default=None, min_length=1, max_length=20)
    ok: bool = True
    port: str | None = Field(default=None, min_length=1, max_length=40)
    record_changed: WaitEvent | None = None
    facts: dict[str, Any] = Field(default_factory=dict, max_length=workflow_tests.SAMPLE_MAX_FIELDS)
    fast_forward_seconds: int | None = Field(default=None, ge=1, le=workflow_tests.FAST_FORWARD_MAX)


@router.post("/test-runs/{run_id}/answer", summary="Answer a test run")
async def answer_test(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    run_id: uuid.UUID,
    body: AnswerIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
) -> TestRunOut:
    """One of: a command's answer (approved / rejected, done / failed), a change, time."""
    del subject
    given = [
        body.command_id is not None,
        body.record_changed is not None,
        body.fast_forward_seconds is not None,
    ]
    if sum(given) != 1:
        raise ValidationFailed(code="test_answer_one_of")
    if body.command_id is not None:
        run = await workflow_tests.answer(
            session,
            run_id,
            expected_version=version,
            command_id=body.command_id,
            ok=body.ok,
            port=body.port,
        )
    elif body.record_changed is not None:
        run = await workflow_tests.record_changed(
            session, run_id, expected_version=version, kind=body.record_changed, facts=body.facts
        )
    else:
        run = await workflow_tests.fast_forward(
            session, run_id, expected_version=version, seconds=int(body.fast_forward_seconds or 0)
        )
    set_etag(response, run.version)
    return _test(run)


class LiveCallIn(BaseModel):
    """The one live call of the run: a webhook or notify node's command."""

    command_id: str = Field(min_length=1, max_length=20)


@router.post("/test-runs/{run_id}/live-call", summary="Make the test run's one live call")
async def live_call(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    run_id: uuid.UUID,
    body: LiveCallIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
    note: Annotated[
        AuditNote,
        audited(
            "automation.workflow_test_live_call",
            object_type="workflow_test_run",
            object_param="run_id",
        ),
    ],
) -> TestRunOut:
    """Webhook or notify only, once a run, on its record; audited with the node and record."""
    run = await workflow_tests.live_call(
        session, run_id, expected_version=version, command_id=body.command_id, by=subject.user_id
    )
    called = run.live_call or {}
    note.details = {
        **note.details,
        "node": called.get("node"),
        "kind": called.get("kind"),
        "record_type": run.record_type,
        "record_id": str(run.record_id) if run.record_id else None,
    }
    set_etag(response, run.version)
    return _test(run)
