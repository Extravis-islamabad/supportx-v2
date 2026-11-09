"""The asset catalogue's pure rules and the Appendix A defaults (no I/O)."""

from decimal import Decimal

import pytest

from app.modules.assets.domain.catalogue import (
    NAME_LANGUAGES,
    SEED_MOVES,
    SEED_STATES,
    SEED_TYPES,
    AssetStateCategory,
    AssetTypeKind,
    Move,
    SeedType,
    amount_problems,
    clean_names,
    depth,
    descendants,
    duplicate_moves,
    reason_needed,
    tag_pattern_problems,
    would_cycle,
)


def test_names_need_english_and_are_trimmed() -> None:
    names, problems = clean_names("names", {"en": "  Laptop  pro ", "ar": "", "xx": "drop"})
    assert names == {"en": "Laptop pro"}
    assert problems == []
    _, problems = clean_names("names", {"ar": "حاسوب"})
    assert [p.code for p in problems] == ["required"]
    _, problems = clean_names("names", {"en": "x" * 121})
    assert [p.code for p in problems] == ["value_too_long"]
    _, problems = clean_names("names", "Laptop")
    assert [p.field for p in problems] == ["names.en"]


@pytest.mark.parametrize(
    ("pattern", "ok"),
    [("AST-{n}", True), ("{n}", False), ("LT-{n}-{n}", False), ("LT", False), (None, True)],
)
def test_tag_patterns_hold_one_counter(pattern: str | None, *, ok: bool) -> None:
    assert (tag_pattern_problems("tag_pattern", pattern) == []) is ok


def test_amounts() -> None:
    assert amount_problems("price", Decimal("10.50")) == []
    assert [p.code for p in amount_problems("price", Decimal(-1))] == ["out_of_range"]
    assert [p.code for p in amount_problems("price", Decimal("1.234"))] == ["too_many_decimals"]
    assert amount_problems("price", None) == []


def test_tree_cycles_depth_and_descendants() -> None:
    parents: dict[str, str | None] = {"root": None, "a": "root", "b": "a", "c": "b"}
    assert would_cycle("a", "c", parents)
    assert would_cycle("a", "a", parents)
    assert not would_cycle("c", "root", parents)
    assert not would_cycle("a", None, parents)
    assert depth("c", parents) == 4
    assert depth(None, parents) == 0
    assert descendants("a", parents) == {"b", "c"}
    assert descendants("c", parents) == set()


def test_moves() -> None:
    assert reason_needed(Move("a", "b"), to_state_reason_required=True)
    assert reason_needed(Move("a", "b", reason_required=True), to_state_reason_required=False)
    assert not reason_needed(Move("a", "b"), to_state_reason_required=False)
    assert duplicate_moves([Move("a", "b"), Move("a", "b"), Move("a", "a")]) == [1, 2]


def _walk(types: tuple[SeedType, ...]) -> list[SeedType]:
    found: list[SeedType] = []
    for node in types:
        found.append(node)
        found.extend(_walk(node.children))
    return found


def test_appendix_a_defaults_hold_together() -> None:
    codes = [s.code for s in SEED_STATES]
    assert len(codes) == len(set(codes)) == 7
    # One default state per category, every category covered (the automatic moves need them).
    defaults = [s.category for s in SEED_STATES if s.default_for_category]
    assert sorted(defaults) == sorted(AssetStateCategory)
    for move in SEED_MOVES:
        assert move.from_state in codes
        assert move.to_state in codes
    assert duplicate_moves(SEED_MOVES) == []
    assert not [m for m in SEED_MOVES if m.from_state == "disposed"]  # disposed: no way out

    every = _walk(SEED_TYPES)
    api_names = [t.api_name for t in every]
    assert len(api_names) == len(set(api_names))
    for top in SEED_TYPES:
        assert top.category is not None
        assert top.kind is not None
    for node in every:
        assert set(node.names) == set(NAME_LANGUAGES)
        assert all(node.names.values())
    kinds = {top.kind for top in SEED_TYPES}
    assert kinds == set(AssetTypeKind)
    for state in SEED_STATES:
        assert set(state.names) == set(NAME_LANGUAGES)
