"""Impact analysis: which CIs a failure reaches, and from where (WP-053 S3b). Pure.

- **Which way a failure travels** depends on the relationship type (REQ-CMDB-010): "A depends
  on B" means a failure of B reaches A; "A is part of B" means a failure of A reaches B (the part
  breaks the whole); "A is connected to B" goes both ways. The built-ins are fixed here
  (`IMPACT_FLOW`); a tenant's own type reads as "A relies on B" (`DEFAULT_FLOW`). A per-type
  choice waits for demand (coordinator, 2026-11-20).
- **Direction asked:** `dependents` (what a failure of these CIs reaches: "if this fails, what
  breaks"), `dependencies` (what these CIs rely on), or `both`.
- **The walk goes through every node, hidden ones too**, so paths stay true (REQ-CMDB-030); the
  service redacts what the reader may not see afterwards. Unlike S2's map, nothing stops at a
  placeholder. Breadth first, each CI once (a cycle ends), to `depth`, at most `CI_MAX` CIs.
- **Paths:** each reached CI keeps the node it was first reached from (`via`); with the stable
  order below, that is one shortest path, the same on every call.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

INPUT_MAX = 50  # CIs one question may start from (lane A's contract)
DEPTH_DEFAULT = 3
DEPTH_MAX = 10
CI_MAX = 5000  # CIs in one answer; `truncated` beyond


class ImpactDirection(StrEnum):
    """What the question follows (`cmdb_impact_direction.<code>`)."""

    DEPENDENTS = "dependents"  # what a failure of these CIs reaches
    DEPENDENCIES = "dependencies"  # what these CIs rely on
    BOTH = "both"


# Lane A's contract words (S5, S7), accepted by the public service only.
CONTRACT_DIRECTIONS: Mapping[str, ImpactDirection] = {
    "down": ImpactDirection.DEPENDENTS,
    "up": ImpactDirection.DEPENDENCIES,
    "both": ImpactDirection.BOTH,
}


class Flow(StrEnum):
    """Which end's failure reaches the other along a link from A to B."""

    TO_FROM = "to_from"  # a failure of B reaches A ("A relies on B")
    FROM_TO = "from_to"  # a failure of A reaches B ("A is part of B")
    BOTH = "both"


# The built-in types that carry impact (domain/relationships.py BUILT_IN_TYPES).
IMPACT_FLOW: Mapping[str, Flow] = {
    "depends_on": Flow.TO_FROM,
    "runs_on": Flow.TO_FROM,
    "virtualised_by": Flow.TO_FROM,
    "part_of": Flow.FROM_TO,
    "connected_to": Flow.BOTH,
}
DEFAULT_FLOW = Flow.TO_FROM  # a tenant's own type: "A <verb> B" reads as A relying on B


def flow_of(type_code: str | None) -> Flow:
    """A relationship type's flow; a tenant's own type (no built-in code) gets the default."""
    return IMPACT_FLOW.get(type_code or "", DEFAULT_FLOW)


@dataclass(frozen=True)
class ImpactEdge:
    """A live link whose type carries impact, with that type's flow."""

    id: str
    from_id: str
    to_id: str
    flow: Flow
    type_id: str = ""


def _failure_pairs(edge: ImpactEdge) -> list[tuple[str, str]]:
    """(failing end, the end it reaches) for this link."""
    forward = (edge.from_id, edge.to_id)
    backward = (edge.to_id, edge.from_id)
    if edge.flow is Flow.TO_FROM:
        return [backward]
    if edge.flow is Flow.FROM_TO:
        return [forward]
    return [backward, forward]


def steps(edge: ImpactEdge, direction: ImpactDirection) -> list[tuple[str, str]]:
    """(from, to) steps the walk may take along this link, for the direction asked."""
    pairs = _failure_pairs(edge)
    found: list[tuple[str, str]] = []
    if direction in {ImpactDirection.DEPENDENTS, ImpactDirection.BOTH}:
        found.extend(pairs)  # from a failing CI to what it reaches
    if direction in {ImpactDirection.DEPENDENCIES, ImpactDirection.BOTH}:
        found.extend((reached, failing) for failing, reached in pairs)  # to what it relies on
    return list(dict.fromkeys(found))


@dataclass(frozen=True)
class Reached:
    """A CI the walk reached: how far, and the node it was first reached from."""

    depth: int
    via: str | None  # None for a start
    via_type: str | None = None  # the relationship type of the step (None for a start)
    # The stored link runs from `via` to this CI (True) or from this CI to `via` (False).
    via_forward: bool = True


@dataclass
class ImpactWalk:
    """What the walk found so far; the service feeds it one level of edges at a time."""

    starts: tuple[str, ...]
    direction: ImpactDirection
    ci_max: int = CI_MAX
    reached: dict[str, Reached] = field(default_factory=dict)
    truncated: bool = False

    def __post_init__(self) -> None:
        """The starts are reached at depth 0, in their given order."""
        for start in self.starts:
            self.reached.setdefault(start, Reached(0, None))

    def add_level(
        self, level: int, frontier: Iterable[str], edges: Iterable[ImpactEdge]
    ) -> list[str]:
        """Add one level from `frontier`; returns the next frontier (the CIs new at this level).

        Deterministic: the frontier and each node's steps are taken in a stable order, so the
        same graph gives the same depths and paths on every call. Linear in the edges read.
        """
        current = set(frontier)
        # source -> target -> the step's link (type, stored from->to), the lowest for stability
        onward: dict[str, dict[str, tuple[str, bool]]] = {}
        for edge in edges:
            for step_from, step_to in steps(edge, self.direction):
                if step_from in current:
                    targets = onward.setdefault(step_from, {})
                    link = (edge.type_id, edge.from_id == step_from)
                    known = targets.get(step_to)
                    targets[step_to] = link if known is None else min(known, link)
        found: list[str] = []
        for source in sorted(onward):
            for target in sorted(onward[source]):
                if target in self.reached:
                    continue
                if len(self.reached) >= self.ci_max:
                    self.truncated = True
                    return found
                type_id, forward = onward[source][target]
                self.reached[target] = Reached(level, source, type_id or None, forward)
                found.append(target)
        return found


def bounded_depth(depth: int | None) -> int:
    """The depth asked, within 1..DEPTH_MAX (DEPTH_DEFAULT when not given)."""
    if depth is None:
        return DEPTH_DEFAULT
    return max(1, min(depth, DEPTH_MAX))
