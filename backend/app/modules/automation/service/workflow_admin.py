"""Designing, publishing and switching workflows (WP-048b S1, ADR-043 §1-3, §6, §9).

- A workflow starts as a draft (start → end). Its draft saves with its problems
  (REQ-WF-019: drafts may have problems; only a clean definition publishes).
- Publishing makes a new, immutable version (REQ-WF-021). The first publish makes the workflow's
  run-as service identity, "Workflow: <name>" (lane B's conditions); its roles are given apart,
  through identity_access's guarded path.
- Enabling and disabling (REQ-WF-010 AC3): disabling stops new instances and leaves running ones
  alone; it also deactivates the run-as identity (never deletes it), so a disabled workflow can do
  nothing even if an instance runs on, until it is enabled again.

Validation reads the record type through automation's registry (its fields, settable fields and
life-cycle actions), never the owning module's tables (rule e).
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.automation.domain.rules import FieldKind
from app.modules.automation.domain.workflows import (
    FORMAT,
    Definition,
    Problem,
    TypeFacts,
    parse,
    sub_flows,
    validate,
)
from app.modules.automation.events import WorkflowChanged
from app.modules.automation.infra.models import Workflow, WorkflowVersion
from app.modules.automation.service import functions
from app.modules.automation.service.registry import record_type as registered
from app.modules.identity_access import create_service_identity, set_service_identity_active
from app.shared.events import record_event

NAME_MAX = 200
STARTER: Mapping[str, Any] = {
    "format": FORMAT,
    "nodes": [
        {"id": "start", "type": "start", "config": {}, "position": {"x": 0, "y": 0}},
        {"id": "end", "type": "end", "config": {}, "position": {"x": 0, "y": 160}},
    ],
    "links": [{"from": "start", "port": "next", "to": "end"}],
    "variables": [],
}


async def type_facts(session: AsyncSession, record_type: str) -> TypeFacts:
    """What validation knows about a record type, from its registration."""
    kind = registered(record_type)
    if kind is None:
        raise ValidationFailed(code="unknown_record_type", params={"type": record_type})
    fields = await kind.fields(session)
    return TypeFacts(
        record_type=record_type,
        fields=fields,
        settable=frozenset(name for name, spec in fields.items() if spec.settable),
        actions=frozenset(kind.transition_actions),
        date_fields=frozenset(
            name for name, spec in fields.items() if spec.kind == FieldKind.DATETIME
        ),
        approvals=kind.approval_roles is not None,
        functions=await functions.offered(session.info[SESSION_TENANT_KEY].tenant_id),
        roles=frozenset(kind.approval_roles or ()),
    )


async def problems_of(
    session: AsyncSession,
    record_type: str,
    definition: Mapping[str, Any],
    workflow_id: uuid.UUID | None = None,
) -> list[Problem]:
    """Every problem of a definition: unreadable shapes, then validation (REQ-WF-019)."""
    parsed = parse(definition)
    if parsed.definition is None:
        return parsed.problems
    found = parsed.problems + validate(parsed.definition, await type_facts(session, record_type))
    return found + await _sub_flow_problems(session, record_type, parsed.definition, workflow_id)


MAX_SUB_FLOW_DEPTH = 10  # sub-flows of sub-flows, at most this deep


async def _sub_flow_problems(
    session: AsyncSession,
    record_type: str,
    definition: Definition,
    workflow_id: uuid.UUID | None,
) -> list[Problem]:
    """A sub-flow runs a workflow of the same record type that never leads back here (WF-017).

    The other workflows are followed through their published versions, which are what runs.
    """
    problems: list[Problem] = []
    for node_id, child_id in sub_flows(definition).items():
        where = f"node:{node_id}"
        child = await session.get(Workflow, child_id)
        if child is None or child.deleted_at is not None:
            problems.append((where, "workflow_not_found", {}))
        elif child.record_type != record_type:
            problems.append((where, "workflow_wrong_record_type", {"type": child.record_type}))
        elif await _leads_to(session, child, workflow_id):
            problems.append((where, "sub_flow_recursion", {"workflow": child.name}))
    return problems


async def _leads_to(session: AsyncSession, start: Workflow, target: uuid.UUID | None) -> bool:
    """Whether `start`, through published sub-flows, reaches `target` (or itself, or too deep)."""
    seen: set[uuid.UUID] = set()
    frontier, depth = [start], 0
    while frontier:
        depth += 1
        if depth > MAX_SUB_FLOW_DEPTH:
            return True  # deeper than allowed: refused as if it looped
        following: list[Workflow] = []
        for flow in frontier:
            if flow.id == target or flow.id in seen:
                return True
            seen.add(flow.id)
            for child_id in await _published_sub_flows(session, flow):
                child = await session.get(Workflow, child_id)
                if child is not None and child.deleted_at is None:
                    following.append(child)
        frontier = following
    return False


async def _published_sub_flows(session: AsyncSession, flow: Workflow) -> list[uuid.UUID]:
    if flow.published_version is None:
        return []
    version = await session.get(WorkflowVersion, (flow.tenant_id, flow.id, flow.published_version))
    parsed = parse(version.definition) if version is not None else None
    if parsed is None or parsed.definition is None:
        return []
    return list(sub_flows(parsed.definition).values())


async def _get(session: AsyncSession, workflow_id: uuid.UUID) -> Workflow:
    found = await session.get(Workflow, workflow_id)
    if found is None or found.deleted_at is not None:
        raise NotFound(code="workflow_not_found")
    return found


def _stale(workflow: Workflow, expected: int) -> None:
    if workflow.version != expected:
        raise Conflict(code="version_conflict", params={"current": workflow.version})


async def _changed(session: AsyncSession, workflow: Workflow, change: str) -> None:
    await record_event(
        session,
        WorkflowChanged(
            workflow_id=workflow.id,
            record_type=workflow.record_type,
            change=change,  # type: ignore[arg-type]  # one of the literal's values
            version=workflow.version,
        ),
        aggregate_id=workflow.id,
        aggregate_version=workflow.version,
    )


async def create_workflow(
    session: AsyncSession, *, record_type: str, name: str, description: str | None
) -> Workflow:
    """A new draft workflow: start linked to end, disabled, not yet published."""
    await type_facts(session, record_type)  # a known record type
    shown = name.strip()
    if not 0 < len(shown) <= NAME_MAX:
        raise ValidationFailed(code="name_invalid", params={"max": NAME_MAX})
    taken = await session.scalar(
        select(Workflow.id).where(
            Workflow.record_type == record_type,
            Workflow.deleted_at.is_(None),
            Workflow.name.ilike(shown),
        )
    )
    if taken is not None:
        raise Conflict(code="workflow_name_taken")
    workflow = Workflow(
        tenant_id=session.info[SESSION_TENANT_KEY].tenant_id,
        record_type=record_type,
        name=shown,
        description=description,
        draft=dict(STARTER),
    )
    session.add(workflow)
    await session.flush()
    await _changed(session, workflow, "created")
    return workflow


async def save_draft(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    *,
    expected_version: int,
    definition: Mapping[str, Any],
) -> tuple[Workflow, list[Problem]]:
    """The draft saves whatever its problems; they come back to be shown on the canvas."""
    workflow = await _get(session, workflow_id)
    _stale(workflow, expected_version)
    problems = await problems_of(session, workflow.record_type, definition, workflow.id)
    workflow.draft = dict(definition)
    workflow.draft_problems = len(problems)
    workflow.version += 1
    await session.flush()
    await _changed(session, workflow, "draft_saved")
    return workflow, problems


async def publish(
    session: AsyncSession, workflow_id: uuid.UUID, *, expected_version: int
) -> WorkflowVersion:
    """A clean draft becomes the next version; running instances keep theirs (REQ-WF-021)."""
    workflow = await _get(session, workflow_id)
    _stale(workflow, expected_version)
    problems = await problems_of(session, workflow.record_type, workflow.draft, workflow.id)
    if problems:
        raise ValidationFailed(code="workflow_has_problems", params={"count": len(problems)})
    if workflow.service_identity_id is None:
        workflow.service_identity_id = await create_service_identity(
            session, name=f"Workflow: {workflow.name}", source="workflow"
        )
    number = (workflow.published_version or 0) + 1
    version = WorkflowVersion(
        tenant_id=workflow.tenant_id,
        workflow_id=workflow.id,
        number=number,
        definition=dict(workflow.draft),
    )
    session.add(version)
    workflow.published_version = number
    workflow.version += 1
    await session.flush()
    await _changed(session, workflow, "published")
    return version


async def set_start_templates(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    *,
    expected_version: int,
    template_ids: list[uuid.UUID],
) -> Workflow:
    """The templates whose new records start this workflow (REQ-WF-010 AC1)."""
    workflow = await _get(session, workflow_id)
    _stale(workflow, expected_version)
    workflow.start_templates = sorted(set(template_ids))
    workflow.version += 1
    await session.flush()
    await _changed(session, workflow, "draft_saved")
    return workflow


async def set_enabled(
    session: AsyncSession, workflow_id: uuid.UUID, *, expected_version: int, enabled: bool
) -> Workflow:
    """On: new instances start. Off: none start, running ones keep going (REQ-WF-010 AC3)."""
    workflow = await _get(session, workflow_id)
    _stale(workflow, expected_version)
    if enabled and workflow.published_version is None:
        raise Conflict(code="workflow_not_published")
    if workflow.enabled == enabled:
        return workflow
    workflow.enabled = enabled
    workflow.version += 1
    if workflow.service_identity_id is not None:
        # Deactivated, never deleted: history keeps its name (lane B's conditions).
        await set_service_identity_active(session, workflow.service_identity_id, active=enabled)
    await session.flush()
    await _changed(session, workflow, "enabled" if enabled else "disabled")
    return workflow
