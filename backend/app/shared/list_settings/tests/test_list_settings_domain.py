"""The list-settings store's rules (WP-049b s4a): pure, no I/O."""

import uuid

from app.shared.list_settings import domain as rules


def test_view_keys_are_built_in_all_or_a_saved_view() -> None:
    builtin = ("mine", "in_stock")
    assert rules.view_key_valid("all", builtin)
    assert rules.view_key_valid("mine", builtin)
    view_id = uuid.uuid4()
    key = rules.custom_key(view_id)
    assert rules.view_key_valid(key, builtin)
    assert rules.saved_view_id(key) == view_id
    assert not rules.view_key_valid("custom:nope", builtin)
    assert not rules.view_key_valid("someone_elses", builtin)
    assert rules.saved_view_id("mine") is None


def test_columns_are_kept_once_with_widths_in_range() -> None:
    clean, problems = rules.clean_columns([{"key": "name", "width": 240}, {"key": "tag"}])
    assert problems == []
    assert clean == [{"key": "name", "width": 240}, {"key": "tag", "width": None}]
    assert rules.clean_columns(None) == ([], [])
    for bad, code in (
        ([{"key": "name"}, {"key": "name"}], "invalid_choice"),
        ([{"key": "Name!"}], "invalid_choice"),
        ([{"key": "name", "width": 10}], "out_of_range"),
        ([{"key": "name", "width": True}], "out_of_range"),
        ("name", "invalid_choice"),
        ([{"key": f"c{i}"} for i in range(rules.MAX_COLUMNS + 1)], "too_many_items"),
    ):
        assert [p.code for p in rules.clean_columns(bad)[1]] == [code]


def test_names_and_page_sizes() -> None:
    assert rules.clean_name("  My   laptops ") == ("My laptops", [])
    assert rules.clean_name("")[1][0].code == "required"
    assert rules.clean_name("x" * (rules.NAME_MAX + 1))[1][0].code == "value_too_long"
    assert rules.page_size_problems(50) == []
    assert rules.page_size_problems(40)[0].code == "invalid_choice"
    flag: object = True  # a boolean is no page size, though Python counts it as 1
    assert rules.page_size_problems(flag)[0].code == "invalid_choice"
    assert rules.list_key_valid("assets")
    assert not rules.list_key_valid("Assets-list")
