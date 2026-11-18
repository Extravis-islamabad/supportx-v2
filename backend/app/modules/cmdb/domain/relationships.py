"""Relationships, the neighbour walk, business views and version compare (WP-053 S2). Pure.

- **Relationship types** (REQ-CMDB-006): a name per direction; a link "A runs on B" shows on B
  as "B hosts A". The built-in types are labelled `cmdb_relationship.<code>.forward|inverse`; a
  tenant's own type carries both names in en, ar and ur.
- **Rules:** a type with no rule joins any two CIs; with rules, the source's CI type (or one
  above it) must be a rule's `from` and the target's (or one above it) the same rule's `to`.
- **The walk** (REQ-CMDB-008): breadth first from the base, both directions, to a depth of 1..3
  and at most `NODE_MAX` nodes, `truncated` when more were found. A node the reader may not see
  is a placeholder with a per-response key and is never walked through (lane C's condition 2).
- **Compare** (REQ-CMDB-024): attributes added, removed and changed, and relationships added and
  removed, between two snapshots.
"""

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.modules.cmdb.domain.types import LANGUAGES, NAME_MAX, Problem

TARGETS_MAX = 50  # targets in one add (all or nothing)
DEPTH_MAX = 3
NODE_MAX = 500  # nodes in one neighbours answer; expand for more
POSITIONS_MAX = 1000
COORDINATE_MAX = 1_000_000.0

# Every field code these checks give (labelled `errors.field.<code>`; tests/test_error_labels.py
# reads FIELD_PROBLEMS sets).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "invalid_value",
        "invalid_key",
        "duplicate",
        "too_many",
        "not_found",
        "unknown_language",
        "cmdb_relationship_self",
        "cmdb_relationship_not_allowed",
    }
)
NOT_ALLOWED = "cmdb_relationship_not_allowed"  # a field code: the type's rules refuse the pair


class RelationshipDirection(StrEnum):
    """Which name of the type reads from this CI (`cmdb_relationship_direction.<code>`)."""

    FORWARD = "forward"  # this CI is the link's `from`: "this runs on that"
    INVERSE = "inverse"  # this CI is the link's `to`: "this hosts that"


class BusinessViewLayout(StrEnum):
    """A map's layout (`cmdb_view_layout.<code>`)."""

    RADIAL = "radial"
    HIERARCHICAL = "hierarchical"
    TREE = "tree"


# Appendix A (file 07): code, carries impact. Names are labels, never stored.
BUILT_IN_TYPES: tuple[tuple[str, bool], ...] = (
    ("depends_on", True),
    ("runs_on", True),
    ("connected_to", True),
    ("part_of", True),
    ("virtualised_by", True),
    ("backed_up_by", False),
    ("located_in", False),
    ("managed_by", False),
)


def names_problems(where: str, names: object, *, required: bool) -> list[Problem]:
    """A tenant's own type needs its name in every language, both directions."""
    if names is None or names == {}:
        return [Problem(where, "required")] if required else []
    if not isinstance(names, Mapping):
        return [Problem(where, "invalid_value")]
    problems: list[Problem] = []
    for language, text in names.items():
        if language not in LANGUAGES:
            problems.append(Problem(f"{where}.{language}", "unknown_language"))
        elif not isinstance(text, str) or not text.strip() or len(text) > NAME_MAX:
            problems.append(Problem(f"{where}.{language}", "invalid_value"))
    if required:
        problems += [
            Problem(f"{where}.{language}", "required")
            for language in LANGUAGES
            if not str(names.get(language, "")).strip()
        ]
    return problems


@dataclass(frozen=True)
class Rule:
    """One rule of a relationship type: from CI type, to CI type."""

    from_type: str
    to_type: str
    suggested: bool = False


def lineage(type_id: str, parents: Mapping[str, str | None]) -> list[str]:
    """The CI type and the types above it, nearest first (a loop is cut where it repeats)."""
    out: list[str] = []
    current: str | None = type_id
    while current is not None and current not in out:
        out.append(current)
        current = parents.get(current)
    return out


def allowed(
    rules: Sequence[Rule], from_type: str, to_type: str, parents: Mapping[str, str | None]
) -> bool:
    """Whether a type with these rules may join a CI of `from_type` to one of `to_type`."""
    if not rules:
        return True
    froms, tos = set(lineage(from_type, parents)), set(lineage(to_type, parents))
    return any(r.from_type in froms and r.to_type in tos for r in rules)


def suggested(rules: Sequence[Rule], ci_type: str, parents: Mapping[str, str | None]) -> bool:
    """Whether a type is offered first for CIs of `ci_type` (either end of a suggested rule)."""
    mine = set(lineage(ci_type, parents))
    return any(r.suggested and (r.from_type in mine or r.to_type in mine) for r in rules)


def usable_from(rules: Sequence[Rule], ci_type: str, parents: Mapping[str, str | None]) -> bool:
    """Whether a CI of `ci_type` may take part in the type at all (either end)."""
    if not rules:
        return True
    mine = set(lineage(ci_type, parents))
    return any(r.from_type in mine or r.to_type in mine for r in rules)


# --- the walk -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Edge:
    """A live relationship as the walk sees it."""

    id: str
    type_id: str
    from_id: str
    to_id: str


@dataclass
class Walk:
    """What the walk found so far: node IDs with their depth, the edges, and the cap.

    The service reads one level at a time (the edges touching the frontier, then what it may
    know of their ends) and hands it to `add_level`; this keeps the rules pure and tested.
    """

    base: str
    depth: dict[str, int] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    truncated: bool = False
    _seen: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        """The base is always on the map, at depth 0."""
        self.depth.setdefault(self.base, 0)

    def add_level(
        self,
        level: int,
        edges: Iterable[Edge],
        *,
        keep: Callable[[str], bool],
        walkable: Callable[[str], bool],
        node_max: int = NODE_MAX,
    ) -> list[str]:
        """Add one level; returns the next frontier (new nodes that may be walked through).

        `keep(id)` drops a node and its edges (a CI type filtered out, an end-of-life CI hidden, a
        CI in the trash); `walkable(id)` is False for a node the reader may not see: it stays as a
        placeholder but its own neighbours are never read. Deterministic: edges in a stable order.
        """
        frontier: list[str] = []
        for edge in sorted(edges, key=lambda e: (e.type_id, e.from_id, e.to_id, e.id)):
            if edge.id in self._seen:
                continue
            ends = (edge.from_id, edge.to_id)
            if not all(end in self.depth or keep(end) for end in ends):
                continue
            new = [end for end in dict.fromkeys(ends) if end not in self.depth]
            if len(self.depth) + len(new) > node_max:
                self.truncated = True
                continue
            for end in new:
                self.depth[end] = level
                if walkable(end):
                    frontier.append(end)
            self._seen.add(edge.id)
            self.edges.append(edge)
        return frontier


def placeholder_keys(hidden: Iterable[str]) -> dict[str, str]:
    """An opaque key per hidden node, for this response only (never the CI's ID)."""
    return {node: f"r{n}" for n, node in enumerate(sorted(hidden), start=1)}


# --- business views -------------------------------------------------------------------------------


def positions_problems(positions: object) -> list[Problem]:
    """Pinned positions: at most POSITIONS_MAX, each {x, y} finite and in range."""
    if not isinstance(positions, Mapping):
        return [Problem("positions", "invalid_value")]
    if len(positions) > POSITIONS_MAX:
        return [Problem("positions", "too_many")]
    for key, value in positions.items():
        ok = isinstance(key, str) and isinstance(value, Mapping) and set(value) == {"x", "y"}
        if ok:
            ok = all(_coordinate(value[axis]) for axis in ("x", "y"))
        if not ok:
            return [Problem("positions", "invalid_value")]
    return []


def _coordinate(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and abs(value) <= COORDINATE_MAX
    )


# --- compare --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AttributeChange:
    """One attribute between two versions: `added`, `removed` or `changed`."""

    field: str
    kind: str
    old: Any = None
    new: Any = None


def _empty(value: object) -> bool:
    return value is None or value in ("", {}, [])


def compare_attributes(
    old: Mapping[str, Any], new: Mapping[str, Any], fields: Sequence[str]
) -> list[AttributeChange]:
    """The attributes in `fields` that differ, in the fields' order."""
    out: list[AttributeChange] = []
    for name in fields:
        before, after = old.get(name), new.get(name)
        if before == after:
            continue
        if _empty(before):
            out.append(AttributeChange(name, "added", None, after))
        elif _empty(after):
            out.append(AttributeChange(name, "removed", before, None))
        else:
            out.append(AttributeChange(name, "changed", before, after))
    return out


def _link_key(link: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(link.get("type_id")), str(link.get("direction")), str(link.get("ci_id")))


def compare_links(
    old: Sequence[Mapping[str, Any]], new: Sequence[Mapping[str, Any]]
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Relationships (type, direction, other CI) added and removed, in a stable order."""
    before = {_link_key(link): link for link in old}
    after = {_link_key(link): link for link in new}
    added = [after[k] for k in sorted(after.keys() - before.keys())]
    removed = [before[k] for k in sorted(before.keys() - after.keys())]
    return added, removed
