"""Relationship rules, the neighbour walk, view positions and compare, without I/O (WP-053 S2)."""

import math
import time
from collections.abc import Callable

from app.modules.cmdb.domain import relationships as rel

# hardware > server > blade; application > database
PARENTS: dict[str, str | None] = {
    "hardware": None,
    "server": "hardware",
    "blade": "server",
    "application": None,
    "database": "application",
    "rack": None,
}


# --- names and rules (REQ-CMDB-006) ---------------------------------------------------------------


def test_a_tenant_type_needs_both_names_in_every_language() -> None:
    full = {"en": "runs on", "ar": "يعمل على", "ur": "پر چلتا ہے"}
    assert rel.names_problems("names_forward", full, required=True) == []
    missing = rel.names_problems("names_inverse", {"en": "hosts"}, required=True)
    assert {(p.field, p.code) for p in missing} == {
        ("names_inverse.ar", "required"),
        ("names_inverse.ur", "required"),
    }
    assert rel.names_problems("names_forward", None, required=True)[0].code == "required"
    assert rel.names_problems("names_forward", {"fr": "x"}, required=False)[0].code == (
        "unknown_language"
    )
    # A built-in type's names are labels: an override is optional.
    assert rel.names_problems("names_forward", {}, required=False) == []


def test_no_rule_joins_anything() -> None:
    assert rel.allowed([], "application", "rack", PARENTS)


def test_a_server_to_rack_type_refuses_two_applications() -> None:
    rules = [rel.Rule("server", "rack")]
    assert rel.allowed(rules, "server", "rack", PARENTS)
    assert not rel.allowed(rules, "application", "application", PARENTS)  # 006 AC2
    assert not rel.allowed(rules, "rack", "server", PARENTS)  # the rule has a direction


def test_a_rule_on_a_type_covers_the_types_below_it() -> None:
    rules = [rel.Rule("hardware", "rack")]
    assert rel.allowed(rules, "blade", "rack", PARENTS)
    assert not rel.allowed(rules, "database", "rack", PARENTS)


def test_suggested_and_usable_follow_the_lineage() -> None:
    rules = [rel.Rule("server", "rack", suggested=True), rel.Rule("application", "server")]
    assert rel.suggested(rules, "blade", PARENTS)
    assert rel.suggested(rules, "rack", PARENTS)
    assert not rel.suggested(rules, "database", PARENTS)
    assert rel.usable_from(rules, "database", PARENTS)
    assert not rel.usable_from([rel.Rule("server", "rack")], "database", PARENTS)
    assert rel.usable_from([], "database", PARENTS)


def test_a_stored_loop_in_the_type_tree_is_cut() -> None:
    assert rel.lineage("x", {"x": "y", "y": "x"}) == ["x", "y"]


def test_built_in_types_follow_appendix_a() -> None:
    codes = dict(rel.BUILT_IN_TYPES)
    assert len(codes) == 8
    assert [code for code, impact in rel.BUILT_IN_TYPES if not impact] == [
        "backed_up_by",
        "located_in",
        "managed_by",
    ]


def test_every_field_code_is_in_the_labelled_set() -> None:
    assert {rel.NOT_ALLOWED, "cmdb_relationship_self", "too_many"} <= rel.FIELD_PROBLEMS


# --- the walk (REQ-CMDB-008) ----------------------------------------------------------------------


def _edges(pairs: list[tuple[str, str]]) -> list[rel.Edge]:
    return [rel.Edge(f"e{n}", "t", a, b) for n, (a, b) in enumerate(pairs)]


def _everything(node: str) -> bool:
    del node
    return True


def _run(
    edges: list[rel.Edge],
    base: str,
    depth: int,
    *,
    keep: Callable[[str], bool] = _everything,
    walkable: Callable[[str], bool] = _everything,
    node_max: int = rel.NODE_MAX,
) -> rel.Walk:
    walk = rel.Walk(base=base)
    frontier = [base]
    for level in range(1, depth + 1):
        ends = set(frontier)
        touching = [e for e in edges if e.from_id in ends or e.to_id in ends]
        frontier = walk.add_level(
            level,
            touching,
            keep=keep,
            walkable=walkable,
            node_max=node_max,
        )
    return walk


def test_the_walk_goes_both_ways_to_its_depth() -> None:
    edges = _edges([("a", "b"), ("c", "a"), ("b", "d"), ("d", "e")])
    one = _run(edges, "a", 1)
    assert one.depth == {"a": 0, "b": 1, "c": 1}
    two = _run(edges, "a", 2)
    assert two.depth["d"] == 2
    assert "e" not in two.depth
    assert not two.truncated


def test_a_placeholder_stays_but_is_never_walked_through() -> None:
    edges = _edges([("a", "hidden"), ("hidden", "secret")])
    walk = _run(edges, "a", 3, walkable=lambda node: node != "hidden")
    assert set(walk.depth) == {"a", "hidden"}
    assert [(e.from_id, e.to_id) for e in walk.edges] == [("a", "hidden")]


def test_a_filtered_node_drops_with_its_edges() -> None:
    edges = _edges([("a", "b"), ("a", "eol"), ("eol", "c")])
    walk = _run(edges, "a", 2, keep=lambda node: node != "eol")
    assert set(walk.depth) == {"a", "b"}
    assert all("eol" not in (e.from_id, e.to_id) for e in walk.edges)


def test_the_cap_cuts_and_says_so() -> None:
    edges = _edges([("a", f"n{i:03}") for i in range(20)])
    walk = _run(edges, "a", 1, node_max=10)
    assert len(walk.depth) == 10
    assert walk.truncated


def test_the_walk_is_deterministic_and_keeps_cycles_finite() -> None:
    edges = _edges([("a", "b"), ("b", "c"), ("c", "a")])
    first = _run(edges, "a", 3)
    second = _run(list(reversed(edges)), "a", 3)
    assert first.depth == second.depth
    assert sorted(e.id for e in first.edges) == sorted(e.id for e in second.edges)
    assert len(first.edges) == 3


def test_placeholder_keys_are_opaque_and_per_response() -> None:
    keys = rel.placeholder_keys(["0190-secret-id", "0190-other-id"])
    assert set(keys.values()) == {"r1", "r2"}
    assert all("0190" not in key for key in keys.values())


def test_a_thousand_node_walk_is_quick() -> None:
    edges = _edges([(f"n{i // 10}", f"n{i}") for i in range(1, 1000)])
    started = time.perf_counter()
    walk = _run(edges, "n0", 3, node_max=1000)
    assert time.perf_counter() - started < 1.0
    assert len(walk.depth) == 1000


# --- business views (REQ-CMDB-009) ----------------------------------------------------------------


def test_positions_are_bounded_and_finite() -> None:
    assert rel.positions_problems({"id": {"x": 1, "y": -2.5}}) == []
    assert rel.positions_problems({"id": {"x": math.inf, "y": 0}})[0].code == "invalid_value"
    assert rel.positions_problems({"id": {"x": 1}})[0].code == "invalid_value"
    assert rel.positions_problems({"id": {"x": True, "y": 0}})[0].code == "invalid_value"
    assert rel.positions_problems({"id": {"x": 2e6, "y": 0}})[0].code == "invalid_value"
    many = {str(i): {"x": 0, "y": 0} for i in range(rel.POSITIONS_MAX + 1)}
    assert rel.positions_problems(many)[0].code == "too_many"
    assert rel.positions_problems([])[0].code == "invalid_value"


# --- compare (REQ-CMDB-024) -----------------------------------------------------------------------


def test_compare_lists_added_removed_and_changed_attributes() -> None:
    old = {"name": "Web 1", "description": None, "site_id": "s1"}
    new = {"name": "Web 01", "description": "Front", "site_id": None}
    found = rel.compare_attributes(old, new, ("name", "description", "site_id", "criticality"))
    assert [(c.field, c.kind) for c in found] == [
        ("name", "changed"),
        ("description", "added"),
        ("site_id", "removed"),
    ]


def test_compare_lists_relationships_added_and_removed() -> None:
    runs_on = {"type_id": "t1", "direction": "forward", "ci_id": "db"}
    hosts = {"type_id": "t2", "direction": "inverse", "ci_id": "app"}
    used_by = {"type_id": "t3", "direction": "inverse", "ci_id": "svc"}
    added, removed = rel.compare_links([runs_on, hosts], [hosts, used_by])
    assert added == [used_by]
    assert removed == [runs_on]
