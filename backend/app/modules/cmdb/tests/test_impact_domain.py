"""The impact walk (WP-053 S3b): each built-in type's flow, directions, cycles, the cap, paths."""

import pytest

from app.modules.cmdb.domain import relationships as rel
from app.modules.cmdb.domain.impact import (
    CONTRACT_DIRECTIONS,
    DEFAULT_FLOW,
    DEPTH_DEFAULT,
    DEPTH_MAX,
    IMPACT_FLOW,
    Flow,
    ImpactDirection,
    ImpactEdge,
    ImpactWalk,
    bounded_depth,
    flow_of,
    steps,
)

DEPENDENTS, DEPENDENCIES, BOTH = (
    ImpactDirection.DEPENDENTS,
    ImpactDirection.DEPENDENCIES,
    ImpactDirection.BOTH,
)


def _edge(n: int, a: str, b: str, code: str | None) -> ImpactEdge:
    return ImpactEdge(id=f"e{n}", from_id=a, to_id=b, flow=flow_of(code))


def _path(walk: ImpactWalk, node: str) -> tuple[int, str | None]:
    found = walk.reached[node]
    return found.depth, found.via


def _walk(
    starts: tuple[str, ...], direction: ImpactDirection, edges: list[ImpactEdge], depth: int
) -> ImpactWalk:
    walk = ImpactWalk(starts=starts, direction=direction)
    frontier = list(starts)
    for level in range(1, depth + 1):
        frontier = walk.add_level(level, frontier, edges)
        if not frontier:
            break
    return walk


def test_every_built_in_impact_type_has_a_flow() -> None:
    carrying = {code for code, impact in rel.BUILT_IN_TYPES if impact}
    assert set(IMPACT_FLOW) == carrying
    assert flow_of("a_tenant_type") is DEFAULT_FLOW is Flow.TO_FROM
    assert flow_of(None) is DEFAULT_FLOW


@pytest.mark.parametrize(
    ("code", "dependents_of_a", "dependents_of_b"),
    [
        ("depends_on", set(), {"A"}),  # A depends on B: B failing breaks A
        ("runs_on", set(), {"A"}),
        ("virtualised_by", set(), {"A"}),
        ("part_of", {"B"}, set()),  # A is part of B: A failing breaks B
        ("connected_to", {"B"}, {"A"}),
    ],
)
def test_each_built_in_type_flows_its_own_way(
    code: str, dependents_of_a: set[str], dependents_of_b: set[str]
) -> None:
    edges = [_edge(1, "A", "B", code)]
    for start, expected in (("A", dependents_of_a), ("B", dependents_of_b)):
        down = _walk((start,), DEPENDENTS, edges, 1)
        assert set(down.reached) - {start} == expected, (code, start)
        # Dependencies are the reverse question: what the start relies on.
        other = {"A": "B", "B": "A"}[start]
        up = _walk((other,), DEPENDENCIES, edges, 1)
        assert (start in up.reached) == (other in expected), (code, other)


def test_both_is_the_union_and_each_step_once() -> None:
    edge = _edge(1, "A", "B", "connected_to")
    assert steps(edge, BOTH) == [("B", "A"), ("A", "B")]
    assert set(_walk(("A",), BOTH, [_edge(1, "A", "B", "depends_on")], 1).reached) == {"A", "B"}


def test_acceptance_database_two_apps_two_services() -> None:
    # REQ-CMDB-010 AC1/AC2: two applications depend on a database, each used by one service.
    edges = [
        _edge(1, "app1", "db", "depends_on"),
        _edge(2, "app2", "db", "depends_on"),
        _edge(3, "svc1", "app1", "depends_on"),
        _edge(4, "svc2", "app2", "depends_on"),
    ]
    two = _walk(("db",), DEPENDENTS, edges, 2)
    assert set(two.reached) == {"db", "app1", "app2", "svc1", "svc2"}
    assert _path(two, "svc1") == (2, "app1")  # the path back: svc1 ← app1 ← db
    assert _path(two, "app2") == (1, "db")
    one = _walk(("db",), DEPENDENTS, edges, 1)
    assert set(one.reached) == {"db", "app1", "app2"}  # depth 1 drops the services


def test_a_cycle_ends_and_lists_each_ci_once() -> None:
    edges = [
        _edge(1, "A", "B", "depends_on"),
        _edge(2, "B", "C", "depends_on"),
        _edge(3, "C", "A", "depends_on"),
    ]
    walk = _walk(("A",), DEPENDENTS, edges, DEPTH_MAX)
    assert set(walk.reached) == {"A", "B", "C"}
    assert _path(walk, "A") == (0, None)  # the start is never re-reached
    assert not walk.truncated


def test_the_cap_truncates() -> None:
    edges = [_edge(n, f"x{n}", "hub", "depends_on") for n in range(10)]
    walk = ImpactWalk(starts=("hub",), direction=DEPENDENTS, ci_max=5)
    walk.add_level(1, ["hub"], edges)
    assert len(walk.reached) == 5
    assert walk.truncated


def test_the_walk_is_deterministic() -> None:
    edges = [
        _edge(1, "p", "s1", "depends_on"),
        _edge(2, "p", "s2", "depends_on"),
        _edge(3, "q", "p", "depends_on"),
    ]
    first = _walk(("s2", "s1"), DEPENDENTS, edges, 3)
    again = _walk(("s2", "s1"), DEPENDENTS, list(reversed(edges)), 3)
    assert {k: _path(first, k) for k in first.reached} == {
        k: _path(again, k) for k in again.reached
    }
    assert _path(first, "p") == (1, "s1")  # reached first from the lower key


def test_depth_bounds_and_contract_words() -> None:
    assert bounded_depth(None) == DEPTH_DEFAULT == 3
    assert bounded_depth(0) == 1
    assert bounded_depth(99) == DEPTH_MAX == 10
    assert CONTRACT_DIRECTIONS == {"down": DEPENDENTS, "up": DEPENDENCIES, "both": BOTH}


def test_each_step_keeps_its_link_type_and_way() -> None:
    edges = [ImpactEdge("e1", "app", "db", Flow.TO_FROM, "t-dep")]
    walk = _walk(("db",), DEPENDENTS, edges, 1)
    reached = walk.reached["app"]
    # From the database to the app that depends on it: the stored link runs app -> db.
    assert (reached.via, reached.via_type, reached.via_forward) == ("db", "t-dep", False)
