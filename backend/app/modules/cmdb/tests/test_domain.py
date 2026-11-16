"""CMDB domain rules, without I/O (WP-053 S1)."""

from app.modules.cmdb.domain import types as domain

PARENTS = {"server": "hardware", "hardware": None, "blade": "server"}


def test_chain_and_depth_follow_the_tree() -> None:
    assert domain.chain("blade", PARENTS) == ["blade", "server", "hardware"]
    assert domain.depth("hardware", PARENTS) == 1
    assert domain.depth("blade", PARENTS) == 3


def test_a_type_never_goes_below_itself() -> None:
    assert domain.would_loop("hardware", "blade", PARENTS)
    assert domain.would_loop("server", "server", PARENTS)
    assert not domain.would_loop("blade", "hardware", PARENTS)
    assert not domain.would_loop("blade", None, PARENTS)
    # A loop already stored is cut, never followed forever.
    assert domain.chain("x", {"x": "y", "y": "x"}) == ["x", "y"]


def test_every_field_code_is_in_the_labelled_set() -> None:
    codes = {"invalid_key", "duplicate", "cmdb_ci_type_loop", "cmdb_ci_type_too_deep"}
    assert codes <= domain.FIELD_PROBLEMS
