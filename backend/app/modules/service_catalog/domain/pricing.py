"""An item's price and a request's estimated cost (WP-047b S1; REQ-CAT-020, D-184). Pure.

- An item may have a price: once, or per month or year (REQ-CAT-020 AC2), and an internal cost
  when it differs. Money is the tenant's base currency only (D-164): no currency per item.
- A choice or multi-choice question may price its options (`option_prices`: code -> amount);
  amounts are decimal text in the question's JSON, never floats.
- The estimate is (the price + the chosen options' prices) times the quantity (1 when the item asks
  none): 500 with a "+100" option is 600 (AC1). Nothing priced: no estimate (None, never 0).
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from app.modules.service_catalog.domain.items import CHOICE_KINDS, Problem, Question

MONEY_MAX = Decimal("9999999999.99")  # Numeric(14, 2)
_CENT = Decimal("0.01")
PRICED_KINDS = CHOICE_KINDS  # a choice or a multi-choice


class ChargeTo(StrEnum):
    """Who a fulfilled request charges (REQ-CAT-021): the person's department, or an answer."""

    REQUESTED_FOR_DEPARTMENT = "requested_for_department"
    QUESTION = "question"  # a form answer naming a cost centre (V1: no cost-centre list)


class PricePeriod(StrEnum):
    """How often an item's price is paid (REQ-CAT-020 AC2)."""

    ONCE = "once"
    MONTH = "month"
    YEAR = "year"


def money(value: Any) -> Decimal | None:  # noqa: ANN401 - untrusted JSON or a column value
    """An amount, if `value` is one: at least 0, at most two decimals, within the column."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0 or amount > MONEY_MAX:
        return None
    if amount != amount.quantize(_CENT):
        return None  # never rounded silently
    return amount.quantize(_CENT)


def price_problems(price: Any, internal_cost: Any) -> list[Problem]:  # noqa: ANN401 - untrusted JSON
    """The item's own amounts: none, or a valid amount each."""
    found: list[Problem] = []
    for name, value in (("price", price), ("internal_cost", internal_cost)):
        if value is not None and money(value) is None:
            found.append((name, "invalid_amount"))
    return found


def option_price_problems(questions: Sequence[Question]) -> list[Problem]:
    """Option prices: on choice questions only, for their own options, valid amounts."""
    found: list[Problem] = []
    for i, q in enumerate(questions):
        if not q.option_prices:
            continue
        at = f"questions.{i}.option_prices"
        if q.kind not in PRICED_KINDS:
            found.append((at, "not_allowed"))
            continue
        for code, amount in q.option_prices.items():
            if code not in q.options:
                found.append((f"{at}.{code}", "invalid_choice"))
            elif money(amount) is None:
                found.append((f"{at}.{code}", "invalid_amount"))
    return found


def _chosen(answer: Any) -> list[str]:  # noqa: ANN401 - a stored answer
    if isinstance(answer, list):
        return [str(a) for a in answer]
    return [] if answer is None or answer == "" else [str(answer)]


def estimate(
    price: Any,  # noqa: ANN401 - a column value
    option_prices: Mapping[str, Mapping[str, str]],
    answers: Mapping[str, Any],
    quantity: int | None,
) -> Decimal | None:
    """(The price + the chosen options' prices) times the quantity; None when nothing is priced.

    `option_prices`: per question key, its options' prices (`priced_options`).
    """
    base = money(price)
    extras = [
        money(prices.get(code))
        for key, prices in option_prices.items()
        for code in _chosen(answers.get(key))
        if code in prices
    ]
    priced = [a for a in extras if a is not None]
    if base is None and not priced:
        return None
    each = (base or Decimal("0.00")) + sum(priced, Decimal("0.00"))
    return min((each * max(quantity or 1, 1)).quantize(_CENT), MONEY_MAX)


def priced_options(questions: Sequence[Question]) -> dict[str, dict[str, str]]:
    """Each question's option prices, by question key (only those that price an option)."""
    return {q.key: dict(q.option_prices) for q in questions if q.option_prices}


__all__ = [
    "MONEY_MAX",
    "PRICED_KINDS",
    "ChargeTo",
    "PricePeriod",
    "estimate",
    "money",
    "option_price_problems",
    "price_problems",
    "priced_options",
]
