"""An item's price and the request's estimate (WP-047b S1; REQ-CAT-020, D-184): no I/O."""

from decimal import Decimal

from app.modules.service_catalog.domain.items import Question, QuestionKind
from app.modules.service_catalog.domain.pricing import (
    estimate as _estimate,
)
from app.modules.service_catalog.domain.pricing import (
    money,
    option_price_problems,
    price_problems,
    priced_options,
)


def estimate(
    price: object, questions: list[Question], answers: dict[str, object], quantity: int | None
) -> object:
    return _estimate(price, priced_options(questions), answers, quantity)


MEMORY = Question(
    "memory",
    {"en": "Memory"},
    QuestionKind.CHOICE,
    options=("16", "32"),
    option_prices={"32": "100.00"},
)
EXTRAS = Question(
    "extras",
    {"en": "Extras"},
    QuestionKind.MULTI_CHOICE,
    options=("bag", "dock", "mouse"),
    option_prices={"bag": "20", "dock": "80.50"},
)


def test_ac1_an_option_adds_its_price_and_the_quantity_multiplies() -> None:
    assert estimate("500", [MEMORY], {"memory": "32"}, None) == Decimal("600.00")
    assert estimate("500", [MEMORY], {"memory": "16"}, None) == Decimal("500.00")
    assert estimate("500", [MEMORY], {"memory": "32"}, 3) == Decimal("1800.00")
    assert estimate("10", [EXTRAS], {"extras": ["bag", "dock", "mouse"]}, 2) == Decimal("221.00")


def test_nothing_priced_is_no_estimate_never_zero() -> None:
    assert estimate(None, [MEMORY], {"memory": "16"}, 2) is None
    assert estimate(None, [MEMORY], {"memory": "32"}, None) == Decimal("100.00")  # options alone


def test_amounts_are_checked_never_rounded() -> None:
    assert money("12.5") == Decimal("12.50")
    for wrong in ("-1", "1.005", "abc", True, "1e20", "NaN"):
        assert money(wrong) is None, wrong
    assert price_problems("1.005", "-2") == [
        ("price", "invalid_amount"),
        ("internal_cost", "invalid_amount"),
    ]
    assert price_problems(None, None) == []


def test_option_prices_belong_to_choices_and_their_own_options() -> None:
    text = Question("note", {"en": "Note"}, QuestionKind.TEXT, option_prices={"x": "1"})
    stray = Question(
        "memory", {"en": "Memory"}, QuestionKind.CHOICE, options=("16",), option_prices={"64": "9"}
    )
    bad = Question(
        "memory", {"en": "Memory"}, QuestionKind.CHOICE, options=("16",), option_prices={"16": "x"}
    )
    assert option_price_problems([MEMORY, EXTRAS]) == []
    assert option_price_problems([text]) == [("questions.0.option_prices", "not_allowed")]
    assert option_price_problems([stray]) == [("questions.0.option_prices.64", "invalid_choice")]
    assert option_price_problems([bad]) == [("questions.0.option_prices.16", "invalid_amount")]
