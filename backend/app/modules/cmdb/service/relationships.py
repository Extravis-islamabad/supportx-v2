"""Relationship types, relationships and the neighbour map (WP-053 S2; REQ-CMDB-006..008).

- **Types** (`cmdb.configure`, audited by their routes): the 8 built-in types (Appendix A) are
  made the first time a tenant's relationships are used; a tenant's own type needs both names in
  en, ar and ur. Rules limit which CI types a type joins; a rule covers the CI types below its.
- **Adding** (`POST /cmdb/cis/{id}/relationships`): one type and direction, up to 50 targets, all
  or nothing. Needs `cmdb.edit` on the source AND every target (lane C's condition 1): a target
  the person may see but not edit is a 403 naming it, one they cannot see a 404. The type's rules,
  a self-link and a duplicate are refused. Every CI involved is locked (in ID order), gets a new
  version, a history line (`child_added`, naming the type, direction and other CI by ID) and a
  snapshot with its relationships; one `cmdb.relationship.changed` event names them all.
- **Removing** (`DELETE /cmdb/relationships/{id}`): the same rights on both ends, a soft delete,
  both ends' versions, history (`child_removed`) and snapshots.
- **Neighbours** (`GET …/neighbours`): breadth first to depth 1..3, at most 500 nodes. A node the
  reader may not see is a placeholder with a per-response key (`r1`, …), never its ID, name, type
  or state; it ignores the CI type and end-of-life filters (which would tell its type) and is
  never walked through (lane C's condition 2). Links to CIs in the trash are left out.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules.cmdb.domain import relationships as rel
from app.modules.cmdb.domain import types as domain
from app.modules.cmdb.events import RelationshipsChanged
from app.modules.cmdb.infra.models import (
    Ci,
    CiState,
    CiType,
    Relationship,
    RelationshipType,
    RelationshipTypeRule,
)
from app.modules.cmdb.service.catalogue import (
    EDIT,
    config_event,
    ensure_defaults,
    invalid,
    require_configure,
    tenant_of,
)
from app.modules.cmdb.service.cis import (
    CIS,
    LINK_FIELD,
    RECORD_TYPE,
    snapshot,
    visible_rows,
    writer,
)
from app.modules.cmdb.service.open_counts import OpenCounts, counts_for
from app.modules.cmdb.service.snapshots import save_version
from app.modules.identity_access import Subject, authorize_stored
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes, stale_version
from app.shared.ids import new_id

RULES_MAX = 100
EDGE_READ_MAX = 5000  # edges read per level; a hub with more is truncated


class RelationshipTypeRepository(Repository[RelationshipType]):
    """Relationship types of the session's tenant."""

    model = RelationshipType


class RelationshipRepository(Repository[Relationship]):
    """Relationships of the session's tenant."""

    model = Relationship


def _now() -> datetime:
    return datetime.now(UTC)


# --- types --------------------------------------------------------------------------------------


async def ensure_types(session: AsyncSession) -> None:
    """The tenant's built-in relationship types, made once (idempotent, race-safe)."""
    if session.info.get("cmdb.relationship_types"):
        return
    await ensure_defaults(session)
    have = await session.scalar(
        select(RelationshipType.id).where(RelationshipType.built_in.is_(True)).limit(1)
    )
    if have is None:
        tenant = tenant_of(session)
        await session.execute(
            insert(RelationshipType)
            .values(
                [
                    {
                        "id": new_id(),
                        "tenant_id": tenant,
                        "code": code,
                        "built_in": True,
                        "names_forward": {},
                        "names_inverse": {},
                        "carries_impact": impact,
                    }
                    for code, impact in rel.BUILT_IN_TYPES
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "code"],
                index_where=RelationshipType.deleted_at.is_(None),
            )
        )
    session.info["cmdb.relationship_types"] = True


@dataclass(frozen=True)
class RelationshipTypeView:
    """One relationship type, its live rules and how many live relationships use it."""

    record: RelationshipType
    rules: list[RelationshipTypeRule]
    relationship_count: int
    suggested: bool = False


async def _parents(session: AsyncSession) -> dict[str, str | None]:
    rows = await session.execute(
        select(CiType.id, CiType.parent_id).where(CiType.deleted_at.is_(None))
    )
    return {str(i): (str(p) if p else None) for i, p in rows}


def _rules_of(rows: Sequence[RelationshipTypeRule]) -> list[rel.Rule]:
    return [rel.Rule(str(r.from_ci_type_id), str(r.to_ci_type_id), r.suggested) for r in rows]


async def _live_rules(
    session: AsyncSession, type_ids: Sequence[uuid.UUID] | None = None
) -> dict[uuid.UUID, list[RelationshipTypeRule]]:
    query = select(RelationshipTypeRule).where(RelationshipTypeRule.deleted_at.is_(None))
    if type_ids is not None:
        query = query.where(RelationshipTypeRule.type_id.in_(type_ids))
    found: dict[uuid.UUID, list[RelationshipTypeRule]] = {}
    for row in await session.scalars(query.order_by(RelationshipTypeRule.id)):
        found.setdefault(row.type_id, []).append(row)
    return found


async def list_types(
    session: AsyncSession, *, for_ci_type: uuid.UUID | None = None
) -> list[RelationshipTypeView]:
    """Every live type with its rules.

    `for_ci_type` (the add dialog): only the types a CI of that type may take part in, suggested
    ones first.
    """
    await ensure_types(session)
    rows = list(
        await session.scalars(
            select(RelationshipType)
            .where(RelationshipType.deleted_at.is_(None))
            .order_by(RelationshipType.built_in.desc(), RelationshipType.code)
        )
    )
    rules = await _live_rules(session)
    counts = dict(
        (
            await session.execute(
                select(Relationship.type_id, func.count())
                .where(Relationship.deleted_at.is_(None))
                .group_by(Relationship.type_id)
            )
        ).all()  # a Result has keys(): dict() would read it as a mapping
    )
    views = [RelationshipTypeView(r, rules.get(r.id, []), int(counts.get(r.id, 0))) for r in rows]
    if for_ci_type is None:
        return views
    parents = await _parents(session)
    ci_type = str(for_ci_type)
    usable = [
        RelationshipTypeView(
            v.record,
            v.rules,
            v.relationship_count,
            suggested=rel.suggested(_rules_of(v.rules), ci_type, parents),
        )
        for v in views
        if rel.usable_from(_rules_of(v.rules), ci_type, parents)
    ]
    return sorted(usable, key=lambda v: not v.suggested)  # stable: suggested first


async def get_type(session: AsyncSession, type_id: uuid.UUID) -> RelationshipType:
    """A live relationship type (404 `cmdb_relationship_type_not_found`)."""
    await ensure_types(session)
    row = await session.scalar(
        select(RelationshipType).where(
            RelationshipType.id == type_id, RelationshipType.deleted_at.is_(None)
        )
    )
    if row is None:
        raise NotFound(code="cmdb_relationship_type_not_found")
    return row


async def _type_view(session: AsyncSession, row: RelationshipType) -> RelationshipTypeView:
    return next(v for v in await list_types(session) if v.record.id == row.id)


def _check_type_values(values: Mapping[str, Any], *, built_in: bool, creating: bool) -> None:
    problems: list[domain.Problem] = []
    if creating:
        code = values.get("code")
        if not isinstance(code, str) or not domain.API_NAME.fullmatch(code):
            problems.append(domain.Problem("code", "invalid_key"))
    for key in ("names_forward", "names_inverse"):
        if key in values or creating:
            problems += rel.names_problems(key, values.get(key), required=not built_in)
    if problems:
        raise invalid(problems)


async def _check_rules(session: AsyncSession, rules: object) -> list[dict[str, Any]]:
    """The rules as rows to write: each pair once, both CI types live."""
    if not isinstance(rules, Sequence) or isinstance(rules, str):
        raise invalid([domain.Problem("rules", "invalid_value")])
    if len(rules) > RULES_MAX:
        raise invalid([domain.Problem("rules", "too_many")])
    live = {uuid.UUID(k) for k in await _parents(session)}
    problems: list[domain.Problem] = []
    out: list[dict[str, Any]] = []
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for n, rule in enumerate(rules):
        pair = (rule.get("from_ci_type_id"), rule.get("to_ci_type_id"))
        if pair in seen:
            problems.append(domain.Problem(f"rules.{n}", "duplicate"))
            continue
        seen.add(pair)
        problems += [
            domain.Problem(f"rules.{n}.{key}", "not_found")
            for key, value in zip(("from_ci_type_id", "to_ci_type_id"), pair, strict=True)
            if value not in live
        ]
        out.append(
            {
                "from_ci_type_id": pair[0],
                "to_ci_type_id": pair[1],
                "suggested": bool(rule.get("suggested", False)),
            }
        )
    if problems:
        raise invalid(problems)
    return out


async def _replace_rules(
    session: AsyncSession, type_id: uuid.UUID, rules: Sequence[Mapping[str, Any]]
) -> bool:
    """Replace a type's live rules; whether anything changed."""
    current = (await _live_rules(session, [type_id])).get(type_id, [])
    old = {(r.from_ci_type_id, r.to_ci_type_id, r.suggested) for r in current}
    new = {(r["from_ci_type_id"], r["to_ci_type_id"], r["suggested"]) for r in rules}
    if old == new:
        return False
    await session.execute(
        update(RelationshipTypeRule)
        .where(RelationshipTypeRule.type_id == type_id, RelationshipTypeRule.deleted_at.is_(None))
        .values(deleted_at=_now(), version=RelationshipTypeRule.version + 1, updated_at=_now())
    )
    for from_type, to_type, suggested in sorted(new, key=str):
        session.add(
            RelationshipTypeRule(
                id=new_id(),
                tenant_id=tenant_of(session),
                type_id=type_id,
                from_ci_type_id=from_type,
                to_ci_type_id=to_type,
                suggested=suggested,
            )
        )
    await session.flush()
    return True


async def create_type(
    session: AsyncSession, subject: Subject, values: Mapping[str, Any]
) -> RelationshipTypeView:
    """A tenant's own relationship type, with its rules."""
    require_configure(subject)
    await ensure_types(session)
    _check_type_values(values, built_in=False, creating=True)
    taken = await session.scalar(
        select(RelationshipType.id).where(
            RelationshipType.code == values["code"], RelationshipType.deleted_at.is_(None)
        )
    )
    if taken is not None:
        raise invalid([domain.Problem("code", "duplicate")])
    rules = await _check_rules(session, values.get("rules") or [])
    row = RelationshipType(
        id=new_id(),
        code=values["code"],
        built_in=False,
        names_forward=dict(values["names_forward"]),
        names_inverse=dict(values["names_inverse"]),
        carries_impact=bool(values.get("carries_impact", True)),
    )
    await RelationshipTypeRepository(session).add(row)
    await _replace_rules(session, row.id, rules)
    await config_event(session, "relationship_type", "created", row.id, row.version)
    return await _type_view(session, row)


async def update_type(
    session: AsyncSession,
    subject: Subject,
    type_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
) -> RelationshipTypeView:
    """Rename, change impact or replace the rules (If-Match). A built-in type keeps its code."""
    require_configure(subject)
    row = await get_type(session, type_id)
    _check_type_values(values, built_in=row.built_in, creating=False)
    rules = await _check_rules(session, values["rules"]) if "rules" in values else None
    changes = {
        k: v
        for k, v in values.items()
        if k in {"names_forward", "names_inverse", "carries_impact"} and getattr(row, k) != v
    }
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    rules_changed = rules is not None and await _replace_rules(session, row.id, rules)
    if not changes and not rules_changed:
        return await _type_view(session, row)
    updated = await RelationshipTypeRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )
    await config_event(session, "relationship_type", "updated", updated.id, updated.version)
    return await _type_view(session, updated)


async def delete_type(
    session: AsyncSession, subject: Subject, type_id: uuid.UUID, *, expected_version: int
) -> None:
    """Remove a tenant's own type: refused while live relationships use it (with the count)."""
    require_configure(subject)
    row = await get_type(session, type_id)
    if row.built_in:
        raise Conflict(code="cmdb_built_in_locked")
    used = await session.scalar(
        select(func.count()).where(
            Relationship.type_id == row.id, Relationship.deleted_at.is_(None)
        )
    )
    if used:
        raise Conflict(
            code="cmdb_relationship_type_in_use", params={"relationship_count": int(used)}
        )
    deleted = await RelationshipTypeRepository(session).soft_delete(
        row.id, expected_version=expected_version
    )
    await _replace_rules(session, row.id, [])
    await config_event(session, "relationship_type", "deleted", row.id, deleted.version)


# --- adding and removing ------------------------------------------------------------------------


def _target_denied(record: Ci) -> PermissionDenied:
    return PermissionDenied(
        code="cmdb_relationship_target_denied",
        params={"permission": EDIT, "reason": "out_of_scope", "display_id": record.display_id},
    )


async def _may_edit(session: AsyncSession, subject: Subject, ci_id: uuid.UUID) -> bool:
    key = writer(subject, EDIT)
    return key is not None and bool(
        await authorize_stored(session, subject, key, CIS, Ci.id, ci_id)
    )


async def _locked(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Ci]:
    """The live CIs, locked in ID order (two adds on the same CIs never deadlock)."""
    rows = await session.scalars(
        select(Ci)
        .where(Ci.id.in_(ids), Ci.deleted_at.is_(None))
        .order_by(Ci.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {row.id: row for row in rows}


async def _touch(  # noqa: PLR0913, PLR0917 - the CI, what happened and the source, explicit
    session: AsyncSession,
    subject: Subject | None,
    record: Ci,
    kind: Literal["child_added", "child_removed"],
    links: Sequence[dict[str, str]],
    source: Source,
) -> None:
    """A new version of one end: history naming each link, and a snapshot with its links."""
    record.version += 1
    record.updated_at = _now()
    saved_by = None if subject is None else subject.user_id  # None: the sync identity
    record.updated_by = saved_by
    await session.flush()
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind=kind,
        changes=[
            Change(LINK_FIELD, None, dict(link))
            if kind == "child_added"
            else Change(LINK_FIELD, dict(link), None)
            for link in links
        ],
        source=source,
    )
    await save_version(session, record, snapshot(record), saved_by)


def _link(
    type_id: uuid.UUID, direction: rel.RelationshipDirection, other: uuid.UUID
) -> dict[str, str]:
    return {"type_id": str(type_id), "direction": direction.value, "ci_id": str(other)}


def _flip(direction: rel.RelationshipDirection) -> rel.RelationshipDirection:
    return (
        rel.RelationshipDirection.INVERSE
        if direction is rel.RelationshipDirection.FORWARD
        else rel.RelationshipDirection.FORWARD
    )


async def _targets(
    session: AsyncSession, subject: Subject, source_id: uuid.UUID, target_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    unique = list(dict.fromkeys(target_ids))
    if not unique:
        raise invalid([domain.Problem("targets", "required")])
    if len(unique) > rel.TARGETS_MAX:
        raise invalid([domain.Problem("targets", "too_many")])
    if source_id in unique:
        raise invalid([domain.Problem("targets", "cmdb_relationship_self")])
    seen = {
        row.id: row for row in await session.scalars(visible_rows(subject).where(Ci.id.in_(unique)))
    }
    if len(seen) < len(unique):
        raise NotFound(code="cmdb_ci_not_found")  # never says which: it may not be seen
    for target in unique:
        if not await _may_edit(session, subject, target):
            raise _target_denied(seen[target])
    return unique


async def add(  # noqa: PLR0913 - the CI, the type, the direction and the targets, explicit
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    type_id: uuid.UUID,
    direction: rel.RelationshipDirection,
    target_ids: Sequence[uuid.UUID],
    source: Source,
) -> list[Relationship]:
    """Link the CI to each target with one type, all or nothing (REQ-CMDB-007)."""
    if writer(subject, EDIT) is None:
        raise PermissionDenied(params={"permission": EDIT, "reason": "no_permission"})
    base = await session.scalar(visible_rows(subject).where(Ci.id == ci_id))
    if base is None:
        raise NotFound(code="cmdb_ci_not_found")
    if not await _may_edit(session, subject, ci_id):
        raise PermissionDenied(params={"permission": EDIT, "reason": "out_of_scope"})
    kind = await get_type(session, type_id)
    targets = await _targets(session, subject, ci_id, target_ids)
    rows = await _locked(session, [ci_id, *targets])
    if len(rows) < len(targets) + 1:  # removed meanwhile
        raise NotFound(code="cmdb_ci_not_found")
    pairs = [
        (ci_id, t) if direction is rel.RelationshipDirection.FORWARD else (t, ci_id)
        for t in targets
    ]
    rules = _rules_of((await _live_rules(session, [kind.id])).get(kind.id, []))
    parents = await _parents(session)
    refused = [
        domain.Problem(f"targets.{n}", rel.NOT_ALLOWED)
        for n, (src, dst) in enumerate(pairs)
        if not rel.allowed(rules, str(rows[src].type_id), str(rows[dst].type_id), parents)
    ]
    if refused:
        raise invalid(refused)
    existing = await session.execute(
        select(Relationship.from_ci_id, Relationship.to_ci_id).where(
            Relationship.type_id == kind.id,
            Relationship.deleted_at.is_(None),
            or_(
                *(
                    (Relationship.from_ci_id == src) & (Relationship.to_ci_id == dst)
                    for src, dst in pairs
                )
            ),
        )
    )
    for src, dst in existing:
        other = rows[dst] if src == ci_id else rows[src]
        raise Conflict(code="cmdb_relationship_exists", params={"display_id": other.display_id})
    repository = RelationshipRepository(session)
    made = [
        await repository.add(Relationship(type_id=kind.id, from_ci_id=src, to_ci_id=dst))
        for src, dst in pairs
    ]
    await _touch(
        session,
        subject,
        rows[ci_id],
        "child_added",
        [_link(kind.id, direction, t) for t in targets],
        source,
    )
    for target in targets:
        await _touch(
            session,
            subject,
            rows[target],
            "child_added",
            [_link(kind.id, _flip(direction), ci_id)],
            source,
        )
    await record_event(
        session,
        RelationshipsChanged(
            ci_id=ci_id,
            action="added",
            type_id=kind.id,
            relationship_ids=[r.id for r in made],
            other_ci_ids=list(targets),
        ),
        aggregate_id=ci_id,
        aggregate_version=rows[ci_id].version,
    )
    return made


async def remove(
    session: AsyncSession,
    subject: Subject,
    relationship_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Unlink (soft delete): `cmdb.edit` on both ends; both get a version (REQ-CMDB-007)."""
    if writer(subject, EDIT) is None:
        raise PermissionDenied(params={"permission": EDIT, "reason": "no_permission"})
    row = await session.scalar(
        select(Relationship).where(
            Relationship.id == relationship_id, Relationship.deleted_at.is_(None)
        )
    )
    ends = (
        {
            r.id: r
            for r in await session.scalars(
                visible_rows(subject).where(Ci.id.in_([row.from_ci_id, row.to_ci_id]))
            )
        }
        if row is not None
        else {}
    )
    if row is None or len(ends) < 2:  # noqa: PLR2004 - both ends
        raise NotFound(code="cmdb_relationship_not_found")
    for end in (row.from_ci_id, row.to_ci_id):
        if not await _may_edit(session, subject, end):
            raise _target_denied(ends[end])
    locked = await _locked(session, [row.from_ci_id, row.to_ci_id])
    if len(locked) < 2:  # noqa: PLR2004 - both ends
        raise NotFound(code="cmdb_relationship_not_found")
    await RelationshipRepository(session).soft_delete(row.id, expected_version=expected_version)
    for this, other, direction in (
        (row.from_ci_id, row.to_ci_id, rel.RelationshipDirection.FORWARD),
        (row.to_ci_id, row.from_ci_id, rel.RelationshipDirection.INVERSE),
    ):
        await _touch(
            session,
            subject,
            locked[this],
            "child_removed",
            [_link(row.type_id, direction, other)],
            source,
        )
    await record_event(
        session,
        RelationshipsChanged(
            ci_id=row.from_ci_id,
            action="removed",
            type_id=row.type_id,
            relationship_ids=[row.id],
            other_ci_ids=[row.to_ci_id],
        ),
        aggregate_id=row.from_ci_id,
        aggregate_version=locked[row.from_ci_id].version,
    )


# --- what a reader may know of CIs ----------------------------------------------------------------


@dataclass(frozen=True)
class NodeInfo:
    """A CI as a node: everything only when `visible`, else nothing but the placeholder."""

    id: uuid.UUID
    visible: bool
    display_id: str | None = None
    name: str | None = None
    type_id: uuid.UUID | None = None
    type_label_key: str | None = None
    type_names: dict[str, str] = field(default_factory=dict)
    state_id: uuid.UUID | None = None
    state_category: str | None = None
    state_label_key: str | None = None
    state_names: dict[str, str] = field(default_factory=dict)
    version: int | None = None


async def node_infos(
    session: AsyncSession, subject: Subject, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, NodeInfo]:
    """What the reader may know of each live CI now (their CURRENT rights, lane C's condition 3).

    A CI they may not see, in the trash or gone is a placeholder (`visible` False) with no field.
    """
    unique = list(dict.fromkeys(ids))
    if not unique:
        return {}
    rows = {r.id: r for r in await session.scalars(visible_rows(subject).where(Ci.id.in_(unique)))}
    types = {
        t.id: t
        for t in await session.scalars(
            select(CiType).where(CiType.id.in_({r.type_id for r in rows.values()}))
        )
    }
    states = {
        s.id: s
        for s in await session.scalars(
            select(CiState).where(CiState.id.in_({r.state_id for r in rows.values()}))
        )
    }
    out: dict[uuid.UUID, NodeInfo] = {}
    for ci_id in unique:
        row = rows.get(ci_id)
        if row is None:
            out[ci_id] = NodeInfo(id=ci_id, visible=False)
            continue
        ci_type, state = types.get(row.type_id), states.get(row.state_id)
        out[ci_id] = NodeInfo(
            id=row.id,
            visible=True,
            display_id=row.display_id,
            name=row.name,
            type_id=row.type_id,
            type_label_key=(
                f"cmdb_ci_type.{ci_type.api_name}" if ci_type and ci_type.built_in else None
            ),
            type_names=dict(ci_type.names) if ci_type and not ci_type.built_in else {},
            state_id=row.state_id,
            state_category=state.category if state else None,
            state_label_key=f"cmdb_ci_state.{state.api_name}" if state and state.built_in else None,
            state_names=dict(state.names) if state and not state.built_in else {},
            version=row.version,
        )
    return out


# --- neighbours (REQ-CMDB-008) --------------------------------------------------------------------


@dataclass(frozen=True)
class GraphNode:
    """A node of a map: its key (the CI's ID, or `r<n>` for a placeholder) and what may show."""

    key: str
    depth: int
    info: NodeInfo
    counts: OpenCounts | None = None


@dataclass(frozen=True)
class GraphEdge:
    """A link of a map between two keys (its ID and version only when both ends show)."""

    id: uuid.UUID | None
    type_id: uuid.UUID
    from_key: str
    to_key: str
    version: int | None


@dataclass(frozen=True)
class Graph:
    """A map: nodes, edges, whether the cap cut it, and whether open counts exist yet."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    counts_available: bool


async def _ci_type_set(session: AsyncSession, roots: Sequence[uuid.UUID]) -> set[str]:
    """The CI types and every type below them (a filter on a type covers its subtypes)."""
    parents = await _parents(session)
    wanted = {str(r) for r in roots}
    return {t for t in parents if wanted & set(rel.lineage(t, parents))}


@dataclass
class _Facts:
    """What the walk knows of each end: live, seen by the reader, its type and state."""

    wanted_types: set[str] | None
    eol_states: set[str]
    show_eol: bool
    known: dict[str, tuple[bool, str, str]] = field(default_factory=dict)

    async def learn(self, session: AsyncSession, subject: Subject, ids: set[str]) -> None:
        """Read the new ends in two queries (what the reader sees; type and state if live)."""
        new = [uuid.UUID(i) for i in ids if i not in self.known]
        if not new:
            return
        seen = set(
            await session.scalars(
                visible_rows(subject).with_only_columns(Ci.id).where(Ci.id.in_(new))
            )
        )
        rows = await session.execute(
            select(Ci.id, Ci.type_id, Ci.state_id).where(Ci.id.in_(new), Ci.deleted_at.is_(None))
        )
        for ci, ci_type, state in rows:
            self.known[str(ci)] = (ci in seen, str(ci_type), str(state))

    def keep(self, node: str) -> bool:
        """Whether the node is on the map (a placeholder ignores filters: they'd tell its type)."""
        fact = self.known.get(node)
        if fact is None:  # in the trash or gone: not on the map at all
            return False
        visible, ci_type, state = fact
        if not visible:
            return True
        if self.wanted_types is not None and ci_type not in self.wanted_types:
            return False
        return self.show_eol or state not in self.eol_states

    def walkable(self, node: str) -> bool:
        """Only a node the reader may see is walked through."""
        return self.known.get(node, (False, "", ""))[0]


async def _level_edges(
    session: AsyncSession, frontier: Sequence[uuid.UUID], type_ids: Sequence[uuid.UUID]
) -> tuple[list[rel.Edge], bool]:
    """The live edges touching the frontier (of the chosen types), and whether the read was cut."""
    query = select(
        Relationship.id, Relationship.type_id, Relationship.from_ci_id, Relationship.to_ci_id
    ).where(
        Relationship.deleted_at.is_(None),
        or_(Relationship.from_ci_id.in_(frontier), Relationship.to_ci_id.in_(frontier)),
    )
    if type_ids:
        query = query.where(Relationship.type_id.in_(type_ids))
    found = (await session.execute(query.order_by(Relationship.id).limit(EDGE_READ_MAX))).all()
    edges = [rel.Edge(str(i), str(t), str(a), str(b)) for i, t, a, b in found]
    return edges, len(found) >= EDGE_READ_MAX


async def neighbours(  # noqa: PLR0913 - the base and the map's filters, explicit
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    depth: int,
    type_ids: Sequence[uuid.UUID] = (),
    ci_type_ids: Sequence[uuid.UUID] = (),
    show_eol: bool = False,
    node_max: int = rel.NODE_MAX,
) -> Graph:
    """The CI and its neighbours to `depth`, as the reader may see them.

    404 for a CI they may not see, a placeholder's key included: there is no CI to start from.
    """
    if await session.scalar(visible_rows(subject).where(Ci.id == ci_id)) is None:
        raise NotFound(code="cmdb_ci_not_found")
    await ensure_types(session)
    eol = select(CiState.id).where(CiState.category == domain.CiStateCategory.END_OF_LIFE.value)
    facts = _Facts(
        wanted_types=await _ci_type_set(session, ci_type_ids) if ci_type_ids else None,
        eol_states={str(s) for s in await session.scalars(eol)},
        show_eol=show_eol,
    )
    walk = rel.Walk(base=str(ci_id))
    frontier = [ci_id]
    for level in range(1, max(1, min(depth, rel.DEPTH_MAX)) + 1):
        if not frontier:
            break
        edges, cut = await _level_edges(session, frontier, type_ids)
        walk.truncated = walk.truncated or cut
        await facts.learn(session, subject, {end for e in edges for end in (e.from_id, e.to_id)})
        added = walk.add_level(
            level, edges, keep=facts.keep, walkable=facts.walkable, node_max=node_max
        )
        frontier = [uuid.UUID(n) for n in added]
    return await _graph(session, subject, walk)


async def _graph(session: AsyncSession, subject: Subject, walk: rel.Walk) -> Graph:
    ids = [uuid.UUID(n) for n in walk.depth]
    infos = await node_infos(session, subject, ids)
    hidden = rel.placeholder_keys(str(i) for i, info in infos.items() if not info.visible)

    def key(node: str) -> str:
        return hidden.get(node, node)

    shown = [i for i, info in infos.items() if info.visible]
    counts = await counts_for(session, subject, shown)
    nodes = [
        GraphNode(
            key=key(str(i)),
            depth=walk.depth[str(i)],
            info=infos[i],
            counts=(counts.get(i) if counts is not None and infos[i].visible else None),
        )
        for i in ids
    ]
    versions: dict[uuid.UUID, int] = {}
    if walk.edges:
        versions = dict(
            (
                await session.execute(
                    select(Relationship.id, Relationship.version).where(
                        Relationship.id.in_([uuid.UUID(e.id) for e in walk.edges])
                    )
                )
            ).all()
        )
    edges: list[GraphEdge] = []
    for edge in walk.edges:
        both = edge.from_id not in hidden and edge.to_id not in hidden
        rid = uuid.UUID(edge.id)
        edges.append(
            GraphEdge(
                id=rid if both else None,
                type_id=uuid.UUID(edge.type_id),
                from_key=key(edge.from_id),
                to_key=key(edge.to_id),
                version=versions.get(rid) if both else None,
            )
        )
    return Graph(nodes, edges, walk.truncated, counts is not None)
