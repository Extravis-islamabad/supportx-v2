"""Fitting an asset to another never nests it in itself (REQ-AST-018 AC3), without I/O."""

from app.modules.assets.domain.ownership import would_nest_in_itself


def test_an_asset_cannot_be_its_own_parent_or_inside_its_children() -> None:
    parents = {"monitor": "workstation", "workstation": "rack", "rack": None}
    assert would_nest_in_itself("monitor", "monitor", parents)
    assert would_nest_in_itself("rack", "monitor", parents)  # the rack inside its own monitor
    assert not would_nest_in_itself("monitor", "rack", parents)
    assert not would_nest_in_itself("printer", "workstation", parents)


def test_a_stored_loop_is_refused_rather_than_walked_forever() -> None:
    assert would_nest_in_itself("x", "a", {"a": "b", "b": "a"})
