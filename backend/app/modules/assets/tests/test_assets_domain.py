"""The asset record's pure rules (no I/O)."""

from datetime import date

import pytest

from app.modules.assets.domain.assets import (
    SHARED_COUNTER_KEY,
    Age,
    age,
    clean_identifier,
    counts_toward_limit,
    format_tag,
    identifier_problem,
    tag_counter_key,
)
from app.shared.db.display_ids import (
    _KEY as COUNTER_KEY_PATTERN,  # the rule next_display_number applies
)


def test_identifiers_are_trimmed_and_shaped() -> None:
    assert clean_identifier("  SN-1/2 ") == "SN-1/2"
    assert clean_identifier("   ") is None
    assert identifier_problem("CN0X7Q#4:5.6") is None
    assert identifier_problem("a b") == "asset_identifier_invalid"
    assert identifier_problem("x" * 121) == "value_too_long"


def test_tag_counters_are_valid_display_id_keys_and_distinct_per_type() -> None:
    one = tag_counter_key("01a1a94e-54f7-77fc-965c-3cbd30920182")
    two = tag_counter_key("01a1a94e-54f7-77fc-965c-3cbd30920183")
    assert one != two
    for key in (one, two, tag_counter_key(None)):
        assert COUNTER_KEY_PATTERN.match(key), key
    assert tag_counter_key(None) == SHARED_COUNTER_KEY
    assert format_tag("LT-{n}", 7) == "LT-7"


@pytest.mark.parametrize(
    ("category", "kind", "state", "counts"),
    [
        ("it", "asset", "in_use", True),
        ("it", "asset", "retired", True),
        ("it", "asset", "disposed", False),
        ("non_it", "asset", "in_use", False),
        ("it", "component", "in_use", False),
        ("it", "consumable", "in_stock", False),
    ],
)
def test_only_it_assets_not_disposed_count(
    category: str, kind: str, state: str, *, counts: bool
) -> None:
    assert counts_toward_limit(category, kind, state) is counts


def test_age_in_years_months_and_days() -> None:
    assert age(date(2025, 9, 2), date(2026, 11, 5)) == Age(1, 2, 3)
    assert age(date(2026, 1, 31), date(2026, 3, 1)) == Age(0, 1, 1)  # from Feb 28
    assert age(date(2026, 11, 5), date(2026, 11, 5)) == Age(0, 0, 0)
    assert age(date(2027, 1, 1), date(2026, 11, 5)) is None
