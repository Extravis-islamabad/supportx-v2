"""The impact service: one answer for every module (REQ-CMDB-010, REQ-CMDB-011, WP-053 S3b).

`impact_of` is the public interface lane A's work-item links (S5) and change records (S7) call, and
the CI's Impact tab uses the same function, so the same question gets the same answer everywhere.

- **The walk reads the tenant's whole graph** (domain/impact.py), so a path through a CI the
  reader can't see is still found; every CI outside the reader's set (role scope, narrowed by
  ADR-053) is then a placeholder `{key, restricted}` with a per-answer key: no ID, name or type
  (REQ-CMDB-030). Their current rights, read now (lane C's S2 condition 3).
- **Inputs:** at most 50 CIs (422 `too_many`). A start the reader can't see is a placeholder and is
  never walked from, so nothing beyond it is revealed; an unknown or deleted ID is left out and
  counted in `missing`.
- **Bounds:** depth 1..10 (default 3), 5,000 CIs, and an optional deadline: hitting any of them
  gives `truncated`, never an error (S7 calls this inside a record create).
- **Business services** are the reader-visible affected CIs whose type is `business_service` or
  below it. A restricted one is only a placeholder among the CIs: listing it as a service would
  tell its type.
- **Affected users** (D-172 (3), 0185) are the active people the subscribers of the affected
  business services reach, each counted once: only services the reader may see (a hidden one's
  subscribers would tell about a CI they can't open), the starts included. `partial` says so
  whenever any CI in the answer is a placeholder ("of services you can see"). Names only for a
  reader holding `users.view`. No subscribers on any of them: None, `not_configured`.
- No event of its own: consumers refetch on `cmdb.relationship.changed` (`ci_id` and
  `other_ci_ids`), `cmdb.ci.updated`, `cmdb.ci.deleted|restored` and `cmdb.config.changed` (a
  type's `carries_impact`).
"""

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.cmdb.domain import impact as domain
from app.modules.cmdb.domain import relationships as rel
from app.modules.cmdb.domain.types import Problem
from app.modules.cmdb.infra.models import Ci, CiType, Relationship, RelationshipType
from app.modules.cmdb.service import subscribers
from app.modules.cmdb.service.catalogue import ensure_defaults, invalid
from app.modules.cmdb.service.cis import visible_rows
from app.modules.cmdb.service.relationships import NodeInfo, ensure_types, node_infos
from app.modules.identity_access import Subject
from app.modules.organization import count_people, people_in

BUSINESS_SERVICE = "business_service"  # the built-in CI type (domain/types.py BUILT_IN_TYPES)
NOT_CONFIGURED = "not_configured"  # affected users: no subscribers yet (labelled)
USERS_VIEW = "users.view"
PEOPLE_SHOWN = 50  # names in one answer
FRONTIER_CHUNK = 1000  # frontier CIs per edge read
LEVEL_EDGE_MAX = 100_000  # edges read for one level of the walk; `truncated` beyond
LIVE_CHUNK = 5000  # ends checked live per query


@dataclass(frozen=True)
class ImpactCi:
    """An affected CI, or a placeholder (`restricted`: its key, depth and `via` only).

    `info` is S2's `NodeInfo` (the one redaction helper, REQ-CMDB-030): a placeholder's has no
    field. `type_code` is the CI type's API name, for lane A's consumers.
    """

    key: str  # the CI's ID, or `r<n>` for a placeholder (this answer only)
    depth: int
    via: str | None  # the key it was reached from (None for a start)
    info: NodeInfo
    type_code: str | None = None
    via_type_id: uuid.UUID | None = None  # the relationship type of that step
    via_forward: bool = True  # the stored link runs from `via` to this CI

    @property
    def restricted(self) -> bool:
        """A CI the reader may not see."""
        return not self.info.visible

    @property
    def id(self) -> uuid.UUID | None:
        """The CI's ID, only when the reader may see it."""
        return self.info.id if self.info.visible else None

    @property
    def name(self) -> str | None:
        """The CI's name, only when the reader may see it."""
        return self.info.name


@dataclass(frozen=True)
class ImpactService:
    """An affected business service the reader may see."""

    id: uuid.UUID
    name: str


@dataclass(frozen=True)
class AffectedUsers:
    """How many people the affected services reach (names only with `users.view`)."""

    count: int
    people: list[tuple[uuid.UUID, str]] | None = None
    partial: bool = False  # services the reader can't see were left out


@dataclass(frozen=True)
class Impact:
    """One impact answer, in a stable order (by depth, then key)."""

    starts: list[ImpactCi]
    cis: list[ImpactCi]
    services: list[ImpactService]
    affected_users: AffectedUsers | None
    affected_users_reason: str | None
    missing: int
    truncated: bool
    as_of: datetime


async def _impact_types(session: AsyncSession) -> dict[uuid.UUID, domain.Flow]:
    """The live relationship types that carry impact, each with its flow."""
    await ensure_types(session)
    rows = await session.execute(
        select(RelationshipType.id, RelationshipType.code, RelationshipType.built_in).where(
            RelationshipType.deleted_at.is_(None), RelationshipType.carries_impact.is_(True)
        )
    )
    return {i: domain.flow_of(code if built_in else None) for i, code, built_in in rows}


async def _level(
    session: AsyncSession,
    frontier: Sequence[str],
    types: dict[uuid.UUID, domain.Flow],
) -> tuple[list[domain.ImpactEdge], bool]:
    """The live impact edges touching the frontier whose both ends are live CIs (and the cut).

    Read in chunks of the frontier, at most `LEVEL_EDGE_MAX` edges a level: a wide level of an
    impact walk touches far more links than one map node (S2's `EDGE_READ_MAX`), and cutting
    there would answer `truncated` long before the 5,000-CI cap.
    """
    ids = [uuid.UUID(n) for n in frontier]
    found: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]] = []
    cut = False
    for start in range(0, len(ids), FRONTIER_CHUNK):
        chunk = ids[start : start + FRONTIER_CHUNK]
        room = LEVEL_EDGE_MAX - len(found)
        rows = (
            await session.execute(
                select(
                    Relationship.id,
                    Relationship.type_id,
                    Relationship.from_ci_id,
                    Relationship.to_ci_id,
                )
                .where(
                    Relationship.deleted_at.is_(None),
                    Relationship.type_id.in_(list(types)),
                    or_(Relationship.from_ci_id.in_(chunk), Relationship.to_ci_id.in_(chunk)),
                )
                .order_by(Relationship.id)
                .limit(room)
            )
        ).all()
        found.extend((r[0], r[1], r[2], r[3]) for r in rows)
        if len(rows) >= room:
            cut = True
            break
    ends = {end for _, _, a, b in found for end in (a, b)}
    live: set[uuid.UUID] = set()
    for_ends = list(ends)
    for start in range(0, len(for_ends), LIVE_CHUNK):
        live |= set(
            await session.scalars(
                select(Ci.id).where(
                    Ci.id.in_(for_ends[start : start + LIVE_CHUNK]), Ci.deleted_at.is_(None)
                )
            )
        )
    seen: set[uuid.UUID] = set()
    edges: list[domain.ImpactEdge] = []
    for i, t, a, b in found:
        if i in seen or a not in live or b not in live:
            continue
        seen.add(i)  # a link touching two frontier chunks is read twice
        edges.append(domain.ImpactEdge(str(i), str(a), str(b), types[t], str(t)))
    return edges, cut


async def _service_types(session: AsyncSession) -> set[uuid.UUID]:
    """The business service type and every type below it."""
    rows = (
        await session.execute(
            select(CiType.id, CiType.parent_id, CiType.api_name, CiType.built_in).where(
                CiType.deleted_at.is_(None)
            )
        )
    ).all()
    parents = {str(i): (str(p) if p else None) for i, p, _, _ in rows}
    roots = {str(i) for i, _, name, built_in in rows if built_in and name == BUSINESS_SERVICE}
    return {uuid.UUID(t) for t in parents if roots & set(rel.lineage(t, parents))}


async def impact_of(  # noqa: PLR0913 - the question and its bounds, keyword-only
    session: AsyncSession,
    subject: Subject,
    ci_ids: Sequence[uuid.UUID],
    *,
    direction: domain.ImpactDirection | str = domain.ImpactDirection.DEPENDENTS,
    depth: int | None = None,
    deadline: float | None = None,
    ci_max: int = domain.CI_MAX,
) -> Impact:
    """What a failure of these CIs reaches (or what they rely on), as the reader may see it.

    `direction` takes `dependents|dependencies|both`, or lane A's `down|up`. `deadline` is a
    `time.monotonic()` value; reaching it ends the walk with `truncated`.
    """
    asked = list(dict.fromkeys(ci_ids))
    if len(asked) > domain.INPUT_MAX:
        raise invalid([Problem("ci_ids", "too_many")])
    way = domain.CONTRACT_DIRECTIONS.get(str(direction))
    if way is None:
        try:
            way = domain.ImpactDirection(direction)
        except ValueError:
            raise invalid([Problem("direction", "invalid_value")]) from None
    await ensure_defaults(session)
    live = set(
        await session.scalars(select(Ci.id).where(Ci.id.in_(asked), Ci.deleted_at.is_(None)))
    )
    seen_starts = set(
        await session.scalars(
            visible_rows(subject).with_only_columns(Ci.id).where(Ci.id.in_(list(live)))
        )
    )
    starts = tuple(str(i) for i in asked if i in seen_starts)
    walk = domain.ImpactWalk(starts=starts, direction=way, ci_max=ci_max)
    types = await _impact_types(session)
    frontier = list(starts)
    for level in range(1, domain.bounded_depth(depth) + 1):
        if not frontier or not types:
            break
        if deadline is not None and time.monotonic() >= deadline:
            walk.truncated = True
            break
        edges, cut = await _level(session, frontier, types)
        walk.truncated = walk.truncated or cut
        frontier = walk.add_level(level, frontier, edges)
    hidden_starts = [
        i for i in asked if i in live and i not in seen_starts and str(i) not in walk.reached
    ]
    return await _answer(
        session, subject, walk, hidden_starts=hidden_starts, missing=len(asked) - len(live)
    )


async def _answer(
    session: AsyncSession,
    subject: Subject,
    walk: domain.ImpactWalk,
    *,
    hidden_starts: Sequence[uuid.UUID],
    missing: int,
) -> Impact:
    """Redact what the reader may not see, now, and put the answer in its stable order."""
    ids = [uuid.UUID(n) for n in walk.reached] + list(hidden_starts)
    infos = await node_infos(session, subject, ids)
    hidden = rel.placeholder_keys(str(i) for i, info in infos.items() if not info.visible)

    def key(node: str) -> str:
        return hidden.get(node, node)

    shown = {info.type_id for info in infos.values() if info.visible}
    type_codes = dict(
        (await session.execute(select(CiType.id, CiType.api_name).where(CiType.id.in_(shown))))
        .tuples()
        .all()
    )
    service_types = await _service_types(session)

    def item(
        node: str,
        depth: int,
        via: str | None,
        via_type: str | None = None,
        *,
        forward: bool = True,
    ) -> ImpactCi:
        info = infos[uuid.UUID(node)]
        code = type_codes.get(info.type_id) if info.visible and info.type_id else None
        return ImpactCi(
            key=key(node),
            depth=depth,
            via=via,
            info=info,
            type_code=code,
            via_type_id=uuid.UUID(via_type) if via_type else None,
            via_forward=forward,
        )

    reached = [
        item(
            node, r.depth, None if r.via is None else key(r.via), r.via_type, forward=r.via_forward
        )
        for node, r in walk.reached.items()
    ]
    starts = [c for c in reached if c.depth == 0] + [item(str(i), 0, None) for i in hidden_starts]
    cis = sorted((c for c in reached if c.depth > 0), key=lambda c: (c.depth, c.key))
    services = sorted(
        (
            ImpactService(id=c.info.id, name=c.info.name or "")
            for c in cis
            if c.info.visible and c.info.type_id in service_types
        ),
        key=lambda s: (s.name, str(s.id)),
    )
    served = [
        c.info.id
        for c in [*starts, *cis]
        if c.info.visible and c.info.type_id in service_types and c.info.id is not None
    ]
    affected = await _affected_users(
        session, subject, served, partial=any(c.restricted for c in [*starts, *cis])
    )
    return Impact(
        starts=sorted(starts, key=lambda c: c.key),
        cis=cis,
        services=services,
        affected_users=affected,
        affected_users_reason=NOT_CONFIGURED if affected is None else None,
        missing=missing,
        truncated=walk.truncated,
        as_of=datetime.now(UTC),
    )


async def _affected_users(
    session: AsyncSession,
    subject: Subject,
    service_ids: Sequence[uuid.UUID],
    *,
    partial: bool,
) -> AffectedUsers | None:
    """The people the visible affected services' subscribers reach, each once."""
    audience = await subscribers.audience_of(session, service_ids)
    if audience.empty:
        return None
    count = await count_people(session, audience)
    people = (
        await people_in(session, subject, audience, limit=PEOPLE_SHOWN)
        if subject.holds(USERS_VIEW)
        else None
    )
    return AffectedUsers(count=count, people=people, partial=partial)


async def ci_impact(
    session: AsyncSession,
    subject: Subject,
    ci_id: uuid.UUID,
    *,
    direction: domain.ImpactDirection,
    depth: int | None,
) -> Impact:
    """One CI's impact for its Impact tab; 404 for a CI the reader may not see (no start)."""
    found = await impact_of(session, subject, [ci_id], direction=direction, depth=depth)
    if not found.starts or found.starts[0].restricted:
        raise NotFound(code="cmdb_ci_not_found")
    return found
