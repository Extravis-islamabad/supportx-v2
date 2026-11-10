"""Costs, total cost of ownership and depreciation (REQ-AST-036, 037), without I/O.

Golden values: each method against a worked example (REQ-AST-037 AC3). The standard example is
a 10,000 asset with a salvage value of 1,000 over five years; the textbook figures are below.
"""

import itertools
from datetime import date
from decimal import Decimal

import pytest

from app.modules.assets.domain.catalogue import AssetDepreciationMethod as M
from app.modules.assets.domain.financials import (
    CostKind,
    DepreciationChoice,
    Terms,
    TermsSource,
    book_value,
    cost_line_problems,
    months_elapsed,
    resolve,
    schedule,
    summarize,
    terms_problems,
    yearly_amounts,
)

D = Decimal
START = date(2025, 1, 15)


def _terms(method: M | None, cost: str = "10000", salvage: str = "1000", life: int = 5) -> Terms:
    return Terms(method=method, cost=D(cost), starts_on=START, life_years=life, salvage=D(salvage))


@pytest.mark.parametrize(
    ("method", "amounts", "closing"),
    [
        (M.STRAIGHT_LINE, ["1800"] * 5, ["8200", "6400", "4600", "2800", "1000"]),
        (
            M.SUM_OF_YEARS_DIGITS,  # 9,000 x 5/15, 4/15, 3/15, 2/15, 1/15
            ["3000", "2400", "1800", "1200", "600"],
            ["7000", "4600", "2800", "1600", "1000"],
        ),
        (
            M.DOUBLE_DECLINING_BALANCE,  # 40 % of the opening value; the last year to salvage
            ["4000", "2400", "1440", "864", "296"],
            ["6000", "3600", "2160", "1296", "1000"],
        ),
        (
            # 30 % of the opening value until straight line over what is left writes off more
            # (year 4: 2,430 / 2 = 1,215 > 30 % of 3,430 = 1,029).
            M.DECLINING_BALANCE,
            ["3000", "2100", "1470", "1215", "1215"],
            ["7000", "4900", "3430", "2215", "1000"],
        ),
    ],
)
def test_each_method_matches_its_worked_example(
    method: M, amounts: list[str], closing: list[str]
) -> None:
    terms = _terms(method)
    assert yearly_amounts(terms) == [D(a) for a in amounts]
    rows = schedule(terms)
    assert [r.closing for r in rows] == [D(c) for c in closing]
    assert [r.year for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0].opening == D(10000)
    assert rows[1].starts_on == date(2026, 1, 15)
    # Each year's closing value is the next year's opening one.
    assert all(a.closing == b.opening for a, b in itertools.pairwise(rows))


def test_ac1_a_1200_asset_over_three_years_is_worth_800_after_one() -> None:
    terms = Terms(M.STRAIGHT_LINE, D(1200), date(2025, 3, 1), 3)
    assert book_value(terms, date(2026, 3, 1)) == D(800)
    assert book_value(terms, date(2026, 2, 28)) == D("833.33")  # 11 months: 400 x 11/12
    assert book_value(terms, date(2025, 3, 1)) == D(1200)  # the day it was bought
    assert book_value(terms, date(2024, 1, 1)) == D(1200)  # before it was bought
    assert book_value(terms, date(2026, 9, 1)) == D(600)  # 18 months: 400 + 6/12 of 400
    assert book_value(terms, date(2040, 1, 1)) == D(0)  # fully depreciated, no salvage


def test_book_value_is_prorated_by_month_within_a_year() -> None:
    terms = _terms(M.DOUBLE_DECLINING_BALANCE)
    # Year 2 takes 2,400: three months into it, 600 of it.
    assert book_value(terms, date(2026, 4, 15)) == D(6000) - D(600)
    assert book_value(terms, date(2026, 4, 14)) == D(6000) - D(400)  # the third month not yet
    assert book_value(terms, date(2030, 1, 15)) == D(1000)  # the end of its life: salvage


def test_months_count_once_their_day_comes_or_the_months_last_day() -> None:
    assert months_elapsed(date(2025, 1, 31), date(2025, 2, 28)) == 1  # February is shorter
    assert months_elapsed(date(2025, 1, 31), date(2025, 2, 27)) == 0
    assert months_elapsed(date(2025, 1, 15), date(2025, 1, 14)) == 0
    assert months_elapsed(date(2024, 2, 29), date(2025, 2, 28)) == 12
    assert months_elapsed(date(2025, 6, 1), date(2027, 5, 31)) == 23


def test_rounding_never_drifts_the_total_written_off() -> None:
    for method in (M.STRAIGHT_LINE, M.SUM_OF_YEARS_DIGITS, M.DECLINING_BALANCE):
        terms = _terms(method, cost="1000.00", salvage="0.01", life=7)
        amounts = yearly_amounts(terms)
        assert sum(amounts) == D("999.99"), method
        assert all(a == a.quantize(D("0.01")) for a in amounts)
        assert schedule(terms)[-1].closing == D("0.01")
    assert yearly_amounts(_terms(M.STRAIGHT_LINE, cost="1000", salvage="0", life=3)) == [
        D("333.33"),
        D("333.33"),
        D("333.34"),
    ]


def test_one_year_of_life_and_nothing_to_depreciate() -> None:
    assert yearly_amounts(_terms(M.DOUBLE_DECLINING_BALANCE, life=1)) == [D(9000)]
    assert yearly_amounts(_terms(None)) == []  # no method: no depreciation
    assert book_value(_terms(None), date(2030, 1, 1)) == D(10000)
    assert yearly_amounts(_terms(M.STRAIGHT_LINE, cost="1000", salvage="1000")) == []
    no_start = Terms(M.STRAIGHT_LINE, D(100), None, 3)
    assert schedule(no_start) == []
    assert book_value(no_start, date(2030, 1, 1)) == D(100)


def test_ac2_the_assets_own_settings_win_and_the_rest_comes_from_the_product() -> None:
    product_only = resolve(
        asset_method=None,
        asset_life=None,
        asset_salvage=None,
        product_method="straight_line",
        product_life=4,
        product_salvage=D(50),
    )
    assert (product_only.method, product_only.method_from) == (M.STRAIGHT_LINE, TermsSource.PRODUCT)
    assert (product_only.life_years, product_only.salvage) == (4, D(50))
    mixed = resolve(
        asset_method="sum_of_years_digits",
        asset_life=None,
        asset_salvage=D(0),
        product_method="straight_line",
        product_life=4,
        product_salvage=D(50),
    )
    assert (mixed.method, mixed.method_from) == (M.SUM_OF_YEARS_DIGITS, TermsSource.ASSET)
    assert (mixed.life_years, mixed.life_from) == (4, TermsSource.PRODUCT)
    assert (mixed.salvage, mixed.salvage_from) == (D(0), TermsSource.ASSET)
    # `none` on the asset: no depreciation, whatever the product says.
    off = resolve(
        asset_method="none",
        asset_life=None,
        asset_salvage=None,
        product_method="straight_line",
        product_life=4,
        product_salvage=None,
    )
    assert (off.choice, off.method) == (DepreciationChoice.NONE, None)


def test_ac1_and_ac3_costs_add_up_exactly() -> None:
    summary = summarize(D(1200), [(CostKind.SERVICE, D(200))])
    assert (summary.operational, summary.total) == (D(200), D(1400))
    many = summarize(None, [(CostKind.OTHER, D("0.01"))] * 1000 + [(CostKind.DISPOSAL, D("0.10"))])
    assert (many.purchase, many.operational, many.disposal) == (D(0), D("10.00"), D("0.10"))
    assert many.total == D("10.10")
    thirds = summarize(D("0.10"), [(CostKind.MOVE, D("0.20"))] * 1000)
    assert thirds.total == D("200.10")  # 0.1 + 0.2 never drifts in decimals


def test_settings_and_lines_are_checked() -> None:
    assert terms_problems(0, None, None)[0].code == "out_of_range"
    assert terms_problems(101, None, None)[0].code == "out_of_range"
    assert terms_problems(5, D(2000), D(1000))[0].code == "asset_salvage_above_cost"
    assert terms_problems(5, D("1.001"), None)[0].code == "too_many_decimals"
    assert terms_problems(5, D(10), D(1000)) == []
    assert [p.code for p in cost_line_problems(None, None)] == ["required"]
    assert [p.code for p in cost_line_problems(D(-1), "x" * 501)] == [
        "out_of_range",
        "value_too_long",
    ]
    assert cost_line_problems(D("19.99"), "Battery") == []
