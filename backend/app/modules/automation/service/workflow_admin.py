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

import copy
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.automation.domain import field_refs
from app.modules.automation.domain.rules import FieldKind
from app.modules.automation.domain.workflows import (
    FORMAT,
    REGISTRY,
    Category,
    Definition,
    NodeType,
    Problem,
    TypeFacts,
    masked,
    offered,
    parse,
    sub_flows,
    validate,
    with_kept_secrets,
)
from app.modules.automation.events import WorkflowChanged, WorkflowDeleted, WorkflowRunAsChanged
from app.modules.automation.infra.models import Workflow, WorkflowInstance, WorkflowVersion
from app.modules.automation.service import functions
from app.modules.automation.service.business_rules import person_group_problems
from app.modules.automation.service.registry import record_type as registered
from app.modules.identity_access import (
    PolicyService,
    Subject,
    assign_service_identity_role,
    create_service_identity,
    remove_service_identity_role,
    set_service_identity_active,
)
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
        notices=kind.notices,
        functions=await functions.offered(session.info[SESSION_TENANT_KEY].tenant_id),
        roles=frozenset(kind.approval_roles or ()),
    )


# Why a node type the record type has is not offered now (a licence, or the type's module).
_NEEDS: dict[NodeType, tuple[str, str]] = {
    NodeType.APPROVAL: ("approvals", "approval_not_offered"),
    NodeType.FUNCTION: ("functions", "function_not_offered"),
    NodeType.NOTIFY: ("notices", "notify_not_offered"),
}


@dataclass(frozen=True)
class NodeTypeOffer:
    """A palette entry: the type, its group, and whether it can be used now (and why not)."""

    type: NodeType
    category: Category
    available: bool
    why_not: str | None
    outputs: tuple[str, ...]
    optional: frozenset[str]
    # An approval's choice of the record's roles, for its settings form (QA F-05: no JSON).
    roles: tuple[str, ...] = ()


async def node_types(session: AsyncSession, record_type: str) -> list[NodeTypeOffer]:
    """The designer's palette for a record type (REQ-WF-009 AC3), from the one registry."""
    facts = await type_facts(session, record_type)
    found = []
    for node_type in offered(record_type):
        spec = REGISTRY[node_type]
        need = _NEEDS.get(node_type)
        available = need is None or bool(getattr(facts, need[0]))
        found.append(
            NodeTypeOffer(
                type=node_type,
                category=spec.category,
                available=available,
                why_not=None if available or need is None else need[1],
                outputs=spec.outputs({}),
                optional=spec.optional({}),
                roles=tuple(sorted(facts.roles)) if node_type == NodeType.APPROVAL else (),
            )
        )
    return found


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
    found += await _sub_flow_problems(session, record_type, parsed.definition, workflow_id)
    return found + await _person_problems(session, parsed.definition)


def _access_problems(
    author: Subject | None, record_type: str, definition: Mapping[str, Any]
) -> list[Problem]:
    """Fields a step names that the workflow's author does not see in clear (ADR-047 §8).

    A field update names its fields as the keys of `values`; conditions and copies name them
    under `field` / `from_field`. Shown on the step like any problem; publishing waits for none.
    """
    if author is None:
        return []
    hidden = field_refs.withheld(author.field_access, record_type)
    if not hidden:
        return []
    problems: list[Problem] = []
    for node in definition.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        config = node.get("config") or {}
        values = config.get("values") if isinstance(config, Mapping) else None
        named = field_refs.named_fields(config) | (
            set(values) if isinstance(values, Mapping) else set()
        )
        problems += [
            (f"node:{node.get('id', '')}", "field_not_permitted", {"field": f})
            for f in sorted(named & hidden)
        ]
    return problems


async def _person_problems(session: AsyncSession, definition: Definition) -> list[Problem]:
    """A field step that sets a technician names the group too, as trigger saves (D-154).

    In several groups the step sets which one; the one it sets must be theirs; in none, nothing
    can be given to them. At run time a person who left falls back to the group only.
    """
    problems: list[Problem] = []
    for node in definition.nodes:
        values = node.config.get("values") if node.type is NodeType.FIELD_UPDATE else None
        if not isinstance(values, dict):
            continue
        for field, code in (await person_group_problems(session, values)).items():
            problems.append((f"node:{node.id}", code, {"field": field}))
    return problems


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
    author: Subject | None = None,
) -> tuple[Workflow, list[Problem]]:
    """The draft saves whatever its problems; they come back to be shown on the canvas."""
    workflow = await _get(session, workflow_id)
    _stale(workflow, expected_version)
    # The designer only ever saw header values masked: the ones sent back masked stay as stored.
    definition = with_kept_secrets(definition, workflow.draft)
    problems = await problems_of(session, workflow.record_type, definition, workflow.id)
    problems += _access_problems(author, workflow.record_type, definition)
    workflow.draft = dict(definition)
    workflow.draft_problems = len(problems)
    workflow.version += 1
    await session.flush()
    await _changed(session, workflow, "draft_saved")
    return workflow, problems


async def publish(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    *,
    expected_version: int,
    by: uuid.UUID | None = None,
    author: Subject | None = None,
) -> WorkflowVersion:
    """A clean draft becomes the next version; running instances keep theirs (REQ-WF-021)."""
    workflow = await _get(session, workflow_id)
    _stale(workflow, expected_version)
    problems = await problems_of(session, workflow.record_type, workflow.draft, workflow.id)
    problems += _access_problems(author, workflow.record_type, workflow.draft)
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
        published_by=by,  # the Versions tab says who (REQ-WF-027)
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
    await _check_templates(session, workflow.record_type, template_ids)
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


# --- copy, export, import, delete (WP-048b S3d; REQ-WF-027) --------------------------------------

EXPORT_FORMAT = "supportx.workflow"  # the file's own tag, so another kind of file is refused
EXPORT_VERSION = 1


async def _free_name(session: AsyncSession, record_type: str, wanted: str) -> str:
    """`wanted`, or `wanted (2)`, `(3)` … when a workflow of the type has it (case-blind)."""
    base = wanted[: NAME_MAX - 6]
    candidate, number = wanted[:NAME_MAX], 2
    while await session.scalar(
        select(Workflow.id).where(
            Workflow.record_type == record_type,
            Workflow.deleted_at.is_(None),
            Workflow.name.ilike(candidate),
        )
    ):
        candidate, number = f"{base} ({number})", number + 1
    return candidate


async def _check_templates(
    session: AsyncSession, record_type: str, template_ids: list[uuid.UUID]
) -> None:
    """Start templates are live templates of the workflow's own type, here (rule a, D-027)."""
    kind = registered(record_type)
    if not template_ids:
        return
    known = (
        await kind.known_templates(session, template_ids)
        if kind and kind.known_templates
        else set()
    )
    unknown = [t for t in template_ids if t not in known]
    if unknown:
        raise ValidationFailed(code="templates_not_found", params={"count": len(unknown)})


async def copy_workflow(session: AsyncSession, workflow_id: uuid.UUID, *, name: str) -> Workflow:
    """An independent draft: the same draft and start templates, disabled, never published.

    `name` comes from the screen, in the admin's language ("Major incident (copy)", REQ-WF-027
    AC1), as a template's copy does; a name already taken gets a number.
    """
    source = await _get(session, workflow_id)
    shown = name.strip()
    if not 0 < len(shown) <= NAME_MAX:
        raise ValidationFailed(code="name_invalid", params={"max": NAME_MAX})
    name = await _free_name(session, source.record_type, shown)
    copied = Workflow(
        tenant_id=source.tenant_id,
        record_type=source.record_type,
        name=name,
        description=source.description,
        draft=copy.deepcopy(source.draft),
        start_templates=list(source.start_templates),
    )
    session.add(copied)
    await session.flush()
    copied.draft_problems = len(
        await problems_of(session, copied.record_type, copied.draft, copied.id)
    )
    await _changed(session, copied, "created")
    return copied


async def export_workflow(session: AsyncSession, workflow_id: uuid.UUID) -> dict[str, Any]:
    """The workflow as a file: its draft and start templates, tagged with its tenant."""
    workflow = await _get(session, workflow_id)
    return {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_VERSION,
        "tenant_id": str(workflow.tenant_id),
        "record_type": workflow.record_type,
        "name": workflow.name,
        "description": workflow.description,
        # Header values never leave in a file: an import asks for them again (#406).
        "definition": masked(workflow.draft),
        "start_templates": [str(t) for t in workflow.start_templates],
    }


async def import_workflow(  # noqa: PLR0913 - the file's parts, explicit
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    record_type: str,
    name: str,
    description: str | None,
    definition: dict[str, Any],
    start_templates: list[uuid.UUID],
) -> tuple[Workflow, list[Problem]]:
    """A file exported here becomes a new draft, its problems shown (REQ-WF-027 AC2).

    Same tenant only (the coordinator, 2026-11-11): a file from another tenant is refused, as
    the people, groups and templates it names would not be these. Cross-tenant import would
    need an ID-mapping step (later).
    """
    here = session.info[SESSION_TENANT_KEY].tenant_id
    if tenant_id != here:
        raise ValidationFailed(code="workflow_file_other_tenant")
    await type_facts(session, record_type)  # a known record type
    await _check_templates(session, record_type, start_templates)
    shown = name.strip()
    if not 0 < len(shown) <= NAME_MAX:
        raise ValidationFailed(code="name_invalid", params={"max": NAME_MAX})
    imported = Workflow(
        tenant_id=here,
        record_type=record_type,
        name=await _free_name(session, record_type, shown),
        description=description,
        draft=definition,
        start_templates=sorted(set(start_templates)),
    )
    session.add(imported)
    await session.flush()
    problems = await problems_of(session, record_type, definition, imported.id)
    imported.draft_problems = len(problems)
    await _changed(session, imported, "created")
    return imported, problems


async def delete_workflow(
    session: AsyncSession, workflow_id: uuid.UUID, *, expected_version: int
) -> Workflow:
    """To the trash; refused while it has live runs: disable it instead (REQ-WF-027 AC3)."""
    workflow = await _get(session, workflow_id)
    _stale(workflow, expected_version)
    live = await session.scalar(
        select(func.count())
        .select_from(WorkflowInstance)
        .where(
            WorkflowInstance.workflow_id == workflow_id,
            WorkflowInstance.status.in_(("running", "waiting")),
        )
    )
    if live:
        raise Conflict(code="workflow_has_running_instances", params={"count": int(live)})
    was_enabled = workflow.enabled
    workflow.deleted_at = datetime.now(UTC)
    workflow.enabled = False
    workflow.version += 1
    if was_enabled and workflow.service_identity_id is not None:  # as switching it off does
        await set_service_identity_active(session, workflow.service_identity_id, active=False)
    await session.flush()
    await record_event(
        session,
        WorkflowDeleted(
            workflow_id=workflow.id, record_type=workflow.record_type, version=workflow.version
        ),
        aggregate_id=workflow.id,
        aggregate_version=workflow.version,
    )
    return workflow


# --- the run-as identity's roles (ADR-043 §6; the coordinator's plan, 2026-11-11) -------------


async def run_as_identity(session: AsyncSession, workflow_id: uuid.UUID) -> uuid.UUID | None:
    """The workflow's run-as identity, or None before its first publish makes it."""
    return (await _get(session, workflow_id)).service_identity_id


async def set_run_as_role(  # noqa: PLR0913 - the workflow, the role and who asks, explicit
    session: AsyncSession,
    policy: PolicyService,
    subject: Subject,
    workflow_id: uuid.UUID,
    role_id: uuid.UUID,
    *,
    held: bool,
) -> None:
    """Give or take one role, only through identity_access's guarded path (lane B's rules).

    The admin hands out nothing beyond their own rights, and never tenant administration or a
    role that manages identities, roles or API keys. No role is ever given without an admin
    choosing it: publishing makes the identity with none.
    """
    workflow = await _get(session, workflow_id)
    if workflow.service_identity_id is None:
        raise Conflict(code="workflow_not_published")
    if held:
        changed = await assign_service_identity_role(
            session, policy, subject, workflow.service_identity_id, role_id
        )
    else:
        changed = await remove_service_identity_role(
            session, policy, subject, workflow.service_identity_id, role_id
        )
    if changed:
        await record_event(
            session,
            WorkflowRunAsChanged(
                workflow_id=workflow.id,
                record_type=workflow.record_type,
                change="role_added" if held else "role_removed",
                version=workflow.version,
            ),
            aggregate_id=workflow.id,
            aggregate_version=workflow.version,
        )
