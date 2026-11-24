"""Merging duplicate CIs (WP-053 S4b; REQ-CMDB-017), as assets' merge (REQ-AST-052).

- **Who:** `cmdb.manage` on BOTH CIs, within its scope (the coordinator's (3)). A CI the person
  may not see is 404, as everywhere; one they see but may not manage is 403. Never across
  tenants (RLS). Both CIs are of one type, and at most one of them is linked to an asset.
- **Preview:** each field's two values and the suggested side (the survivor's unless it has none).
  Custom fields hidden or masked from the merger (ADR-047, ADR-050) show neither side and stay the
  survivor's (lane C (9)); the suggested survivor (the asset-linked one, then the older) never
  looks at a value.
- **The merge, one transaction:** the survivor takes the chosen values through the ordinary save
  (history, a version, the outbox); the merged CI's relationships move with duplicates and
  self-links collapsed (AC1), its business views re-base, its service subscribers move, its asset
  link moves; work items' links move through lane A's port (`links.py`, IDs only). The merged CI
  goes to the trash with a "merged into" line, keeping its own versions. The alias then answers
  its ID with the survivor, for a reader who may see the survivor (`aliases.py`). The route
  writes ONE `cmdb.ci_merged` audit entry with the field mapping.
- **Restore:** see `cis.restore`: a warning, then the alias ends; nothing moves back (lane C (10)).
"""

import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, PermissionDenied
from app.core.logging import get_logger
from app.modules.cmdb.domain import merge as domain
from app.modules.cmdb.domain import relationships as rel
from app.modules.cmdb.domain.types import Problem
from app.modules.cmdb.events import BusinessViewChanged, CiDeleted, RelationshipsChanged
from app.modules.cmdb.infra.models import (
    BusinessView,
    Ci,
    CiAlias,
    Relationship,
    ServiceSubscriber,
)
from app.modules.cmdb.service import cis
from app.modules.cmdb.service.catalogue import MANAGE, invalid
from app.modules.cmdb.service.links import ci_links_port
from app.modules.cmdb.service.relationships import _link, _locked, _touch
from app.modules.identity_access import Subject, authorize_stored
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes
from app.shared.ids import new_id

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MergeField:
    """One field of the preview: both values and the suggested side."""

    field: str
    survivor: Any
    merged: Any
    side: domain.CiMergeSide


@dataclass(frozen=True, slots=True)
class MergePreview:
    """The two CIs in the suggested order, and the field-by-field choice."""

    survivor: cis.CiView
    merged: cis.CiView
    fields: list[MergeField]
    swapped: bool  # the suggestion reversed the order asked for


@dataclass(slots=True)
class MergeResult:
    """The survivor after the merge, the alias, the mapping and what moved (counts)."""

    survivor: cis.CiView
    alias: CiAlias
    mapping: list[dict[str, str]]
    moved: dict[str, int] = field(default_factory=dict)


def _denied(reason: str) -> PermissionDenied:
    return PermissionDenied(params={"permission": MANAGE, "reason": reason})


async def _manageable(
    session: AsyncSession, subject: Subject, first_id: uuid.UUID, second_id: uuid.UUID
) -> tuple[Ci, Ci]:
    """Both CIs, locked, each managed by the subject (coordinator (3)); refused otherwise."""
    if not subject.holds(MANAGE):
        raise _denied(reason="no_permission")
    if first_id == second_id:
        raise Conflict(code="cmdb_merge_same")
    for ci_id in (first_id, second_id):
        await cis.get_visible(session, subject, ci_id)  # 404 when not seen, never a hint
    locked = await _locked(session, [first_id, second_id])
    if len(locked) < 2:  # noqa: PLR2004 - both CIs; removed meanwhile
        raise cis.not_found()
    for ci_id in (first_id, second_id):
        if not await authorize_stored(session, subject, MANAGE, cis.CIS, Ci.id, ci_id):
            raise _denied(reason="out_of_scope")
    first, second = locked[first_id], locked[second_id]
    if first.type_id != second.type_id:
        raise Conflict(code="cmdb_merge_types_differ")
    if first.asset_id is not None and second.asset_id is not None:
        raise Conflict(code="cmdb_merge_both_assets")
    return first, second


def _candidate(row: Ci) -> domain.Candidate:
    return domain.Candidate(asset_linked=row.asset_id is not None, created_at=row.created_at)


def _value(row: Ci, name: str) -> Any:  # noqa: ANN401 - a field's JSON value
    if name.startswith(domain.CUSTOM):
        return (row.custom or {}).get(name.removeprefix(domain.CUSTOM))
    return cis.json_value(getattr(row, name))


def _allowed(subject: Subject, survivor: Ci, merged: Ci) -> list[str]:
    withheld = cis.withheld_custom(subject)
    return domain.mergeable_fields(survivor.custom or {}, merged.custom or {}, withheld)


async def preview(
    session: AsyncSession, subject: Subject, first_id: uuid.UUID, second_id: uuid.UUID
) -> MergePreview:
    """What a merge of the two would keep, with the suggested survivor first (nothing changes)."""
    first, second = await _manageable(session, subject, first_id, second_id)
    swapped = domain.suggest_survivor(_candidate(first), _candidate(second)) == 1
    survivor, merged = (second, first) if swapped else (first, second)
    return MergePreview(
        survivor=await cis.view(session, subject, survivor),
        merged=await cis.view(session, subject, merged),
        fields=[
            MergeField(
                name,
                _value(survivor, name),
                _value(merged, name),
                domain.default_side(_value(survivor, name), _value(merged, name)),
            )
            for name in _allowed(subject, survivor, merged)
        ],
        swapped=swapped,
    )


def _mapping(
    survivor: Ci, merged: Ci, allowed: list[str], choices: Mapping[str, str]
) -> list[dict[str, str]]:
    return [
        {
            "field": name,
            "side": domain.CiMergeSide(
                choices.get(name, domain.default_side(_value(survivor, name), _value(merged, name)))
            ).value,
        }
        for name in allowed
    ]


def _chosen(
    survivor: Ci, merged: Ci, mapping: list[dict[str, str]]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The survivor's new core values, and its custom values (None: unchanged)."""
    core: dict[str, Any] = {}
    custom = dict(survivor.custom or {})
    for item in mapping:
        if item["side"] != domain.CiMergeSide.MERGED:
            continue
        name = item["field"]
        theirs = getattr(merged, name) if not name.startswith(domain.CUSTOM) else None
        if name.startswith(domain.CUSTOM):
            key = name.removeprefix(domain.CUSTOM)
            value = (merged.custom or {}).get(key)
            if value is None:
                custom.pop(key, None)
            else:
                custom[key] = value
        elif theirs != getattr(survivor, name):
            core[name] = theirs
    return core, (custom if custom != (survivor.custom or {}) else None)


async def merge(  # noqa: PLR0913 - the two CIs, their versions, the choices and the source
    session: AsyncSession,
    subject: Subject,
    survivor_id: uuid.UUID,
    merged_id: uuid.UUID,
    *,
    survivor_version: int,
    merged_version: int,
    choices: Mapping[str, str],
    source: Source,
) -> MergeResult:
    """Merge `merged_id` into `survivor_id` with the person's field choices (If-Match on both)."""
    survivor, merged = await _manageable(session, subject, survivor_id, merged_id)
    for row, expected in ((survivor, survivor_version), (merged, merged_version)):
        if row.version != expected:
            raise await cis.stale(session, row.id, expected, row.version)
    allowed = _allowed(subject, survivor, merged)
    if problems := domain.choice_problems(choices, allowed):
        raise invalid([Problem(name, code) for name, code in problems])
    mapping = _mapping(survivor, merged, allowed, choices)
    core, custom = _chosen(survivor, merged, mapping)
    moved: dict[str, int] = {}
    asset_id = merged.asset_id if survivor.asset_id is None else None
    # The merged CI first: out of the live set (its asset link, too), so the survivor may take it.
    now = datetime.now(UTC)
    merged.deleted_at, merged.asset_id = now, None
    merged.version += 1
    merged.updated_at, merged.updated_by = now, subject.user_id
    await session.flush()
    columns: dict[str, Any] = dict(core)
    if custom is not None:
        columns["custom"] = custom
    if asset_id is not None:
        columns["asset_id"] = asset_id
        moved["asset"] = 1
    updated = await cis.save_merged(
        session,
        subject,
        survivor,
        columns=columns,
        source=source,
        extra=[Change(cis.MERGED_FROM, None, {"ci_id": str(merged.id)})],
    )
    moved["relationships"] = await _move_links(session, subject, updated, merged, source)
    moved["business_views"] = await _move_views(session, updated, merged)
    moved["subscribers"] = await _move_subscribers(session, subject, updated, merged)
    port = ci_links_port()
    if port is None:  # work items registers it with work_item_cis (lane A, S5)
        log.info("cmdb_merge_without_links_port", merged_id=str(merged.id))
    moved["work_items"] = (
        await port(session, merged.id, updated.id, source=source) if port is not None else 0
    )
    await record_changes(
        session,
        record_type=cis.RECORD_TYPE,
        record_id=merged.id,
        version=merged.version,
        kind="deleted",
        changes=[Change(cis.MERGED_INTO, None, {"ci_id": str(updated.id)})],
        source=source,
    )
    await record_event(
        session,
        CiDeleted(ci_id=merged.id, type_id=merged.type_id),
        aggregate_id=merged.id,
        aggregate_version=merged.version,
    )
    alias = CiAlias(
        id=new_id(),
        tenant_id=updated.tenant_id,
        created_by=subject.user_id,
        alias_id=merged.id,
        ci_id=updated.id,
        alias_display_id=merged.display_id,
        mapping=mapping,
        moved=moved,
    )
    session.add(alias)
    await session.flush()
    return MergeResult(
        survivor=await cis.view(session, subject, updated),
        alias=alias,
        mapping=mapping,
        moved=moved,
    )


async def _move_links(
    session: AsyncSession, subject: Subject, survivor: Ci, merged: Ci, source: Source
) -> int:
    """The merged CI's relationships go to the survivor; a duplicate or self-link is removed.

    Each other end gets a version naming the link it lost and the one it gained (IDs only, read
    through the reader's view), and one event per type names every CI touched (live maps).
    """
    rows = list(
        await session.scalars(
            select(Relationship).where(
                or_(Relationship.from_ci_id == merged.id, Relationship.to_ci_id == merged.id),
                Relationship.deleted_at.is_(None),
            )
        )
    )
    if not rows:
        return 0
    others = await session.scalars(
        select(Relationship).where(
            or_(Relationship.from_ci_id == survivor.id, Relationship.to_ci_id == survivor.id),
            Relationship.deleted_at.is_(None),
        )
    )
    moves = domain.move_links(
        [domain.Link(r.id, r.type_id, r.from_ci_id, r.to_ci_id) for r in rows],
        merged.id,
        survivor.id,
        [domain.Link(o.id, o.type_id, o.from_ci_id, o.to_ci_id) for o in others],
    )
    by_id = {r.id: r for r in rows}
    ends = {m.to_ci_id if m.from_ci_id == survivor.id else m.from_ci_id for m in moves}
    ends.discard(survivor.id)
    neighbours = await _locked(session, sorted(ends))
    now = datetime.now(UTC)
    kept = 0
    touched: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for move in moves:
        row = by_id[move.link.id]
        row.version += 1
        row.updated_at, row.updated_by = now, subject.user_id
        other = move.to_ci_id if move.from_ci_id == survivor.id else move.from_ci_id
        forward = move.from_ci_id == survivor.id
        if move.collapse:
            row.deleted_at = now
        else:
            row.from_ci_id, row.to_ci_id = move.from_ci_id, move.to_ci_id
            kept += 1
            touched[row.type_id].append(other)
        if other in neighbours:
            direction = (
                rel.RelationshipDirection.INVERSE if forward else rel.RelationshipDirection.FORWARD
            )
            await _touch(
                session,
                subject,
                neighbours[other],
                "child_removed",
                [_link(row.type_id, direction, merged.id)],
                source,
            )
            if not move.collapse:
                await _touch(
                    session,
                    subject,
                    neighbours[other],
                    "child_added",
                    [_link(row.type_id, direction, survivor.id)],
                    source,
                )
    await session.flush()
    for type_id, other_ids in touched.items():
        await record_event(
            session,
            RelationshipsChanged(
                ci_id=survivor.id,
                action="added",
                type_id=type_id,
                relationship_ids=[m.link.id for m in moves if m.link.type_id == type_id],
                other_ci_ids=sorted(set(other_ids), key=str),
            ),
            aggregate_id=survivor.id,
            aggregate_version=survivor.version,
        )
    return kept


async def _move_views(session: AsyncSession, survivor: Ci, merged: Ci) -> int:
    """Business views based on the merged CI re-base on the survivor (a pinned spot follows)."""
    views = list(
        await session.scalars(
            select(BusinessView).where(
                BusinessView.base_ci_id == merged.id, BusinessView.deleted_at.is_(None)
            )
        )
    )
    for view in views:
        positions = dict(view.positions or {})
        if str(merged.id) in positions:
            positions.setdefault(str(survivor.id), positions[str(merged.id)])
            positions.pop(str(merged.id))
        view.base_ci_id, view.positions = survivor.id, positions
        view.version += 1
        await session.flush()
        await record_event(
            session,
            BusinessViewChanged(
                view_id=view.id,
                base_ci_id=survivor.id,
                action="updated",
                changed_fields=["base_ci_id"],
            ),
            aggregate_id=view.id,
            aggregate_version=view.version,
        )
    return len(views)


async def _move_subscribers(
    session: AsyncSession, subject: Subject, survivor: Ci, merged: Ci
) -> int:
    """The merged service's subscribers serve the survivor (each unit once)."""
    rows = list(
        await session.scalars(
            select(ServiceSubscriber).where(
                ServiceSubscriber.ci_id.in_([merged.id, survivor.id]),
                ServiceSubscriber.deleted_at.is_(None),
            )
        )
    )
    have = {(r.kind, r.ref_id) for r in rows if r.ci_id == survivor.id}
    moved = 0
    now = datetime.now(UTC)
    for row in rows:
        if row.ci_id != merged.id:
            continue
        row.version += 1
        row.updated_at, row.updated_by = now, subject.user_id
        if (row.kind, row.ref_id) in have:
            row.deleted_at = now
            continue
        have.add((row.kind, row.ref_id))
        row.ci_id = survivor.id
        moved += 1
    await session.flush()
    return moved
