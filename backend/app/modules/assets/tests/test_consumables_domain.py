"""Consumables: the pure rules (WP-049b s1; REQ-AST-033, 035)."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.assets.domain.consumables import (
    RuleCandidate,
    is_expired,
    low_stock_step,
    pick_rule,
    quantity_problem,
)


@pytest.mark.parametrize(
    ("value", "signed", "code"),
    [
        ("20", False, None),
        ("2.125", False, None),
        ("0", False, "asset_quantity_positive"),
        ("-1", False, "asset_quantity_positive"),
        ("-1", True, None),
        ("0", True, "asset_quantity_positive"),
        ("1.0001", False, "too_many_decimals"),
        ("100000000000", False, "out_of_range"),
        ("abc", False, "invalid_number"),
        ("NaN", False, "invalid_number"),
    ],
)
def test_quantities_are_exact_positive_and_within_three_places(
    value: str, *, signed: bool, code: str | None
) -> None:
    assert quantity_problem(value, signed=signed) == code


def test_033_ac2_a_batch_past_its_expiry_date_is_expired() -> None:
    today = date(2026, 11, 11)
    assert is_expired(date(2026, 11, 10), today)
    assert not is_expired(today, today)  # the expiry day itself is still good
    assert not is_expired(None, today)


def _rule(rule_id: str, *, product: bool, site: bool, depth: int | None) -> RuleCandidate:
    return RuleCandidate(rule_id, product, site, depth, Decimal(1))


def test_035_the_most_specific_rule_wins() -> None:
    parent_any = _rule("a", product=False, site=False, depth=1)
    type_any = _rule("b", product=False, site=False, depth=0)
    type_site = _rule("c", product=False, site=True, depth=1)
    product_any = _rule("d", product=True, site=False, depth=None)
    product_site = _rule("e", product=True, site=True, depth=None)
    assert pick_rule([]) is None
    assert pick_rule([parent_any, type_any]) == type_any
    assert pick_rule([type_any, type_site]) == type_site
    assert pick_rule([type_site, product_any]) == product_any
    assert pick_rule([product_any, product_site, parent_any]) == product_site


def test_035_ac1_alert_once_at_or_below_and_rearm_only_above() -> None:
    five = Decimal(5)
    assert low_stock_step(Decimal(6), five, alerted=False) is None
    assert low_stock_step(Decimal(4), five, alerted=False) == "alert"
    assert low_stock_step(Decimal(5), five, alerted=False) == "alert"  # at the minimum
    assert low_stock_step(Decimal(3), five, alerted=True) is None  # no second notice
    assert low_stock_step(Decimal(5), five, alerted=True) is None  # not above it yet
    assert low_stock_step(Decimal(6), five, alerted=True) == "rearm"
    assert low_stock_step(Decimal(0), None, alerted=True) == "rearm"  # no rule any more
    assert low_stock_step(Decimal(0), None, alerted=False) is None
