"""The disposal record's pure rules (WP-049a s3; REQ-AST-017). No I/O."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.modules.assets.domain.catalogue import AMOUNT_MAX, Problem, amount_problems

# The same list as migration 0108's check.
DISPOSAL_METHODS = (
    "resale",
    "recycling",
    "donation",
    "destruction",
    "returned_to_vendor",
    "other",
)
REASON_MAX = 1000
COST_MAX = AMOUNT_MAX  # Numeric(14, 2)


_CURRENCY = re.compile(r"^[A-Z]{3}$")


def _date(disposed_on: date | None, today: date) -> list[Problem]:
    if disposed_on is None:
        return [Problem("disposed_on", "required")]
    return [Problem("disposed_on", "date_in_future")] if disposed_on > today else []


def _method(method: str | None) -> list[Problem]:
    if method is None:
        return [Problem("method", "required")]
    return [] if method in DISPOSAL_METHODS else [Problem("method", "invalid_choice")]


def _reason(reason: str | None) -> list[Problem]:
    text = (reason or "").strip()
    if not text:
        return [Problem("reason", "required")]
    if len(text) > REASON_MAX:
        return [Problem("reason", "value_too_long", (("max", REASON_MAX),))]
    return []


def _money(cost: object, currency: str | None) -> list[Problem]:
    problems: list[Problem] = []
    if cost is not None:
        try:
            amount = Decimal(str(cost))
        except InvalidOperation:
            amount = Decimal("NaN")
        if not amount.is_finite():
            problems.append(Problem("cost", "out_of_range", (("min", 0), ("max", str(COST_MAX)))))
        else:
            problems += amount_problems("cost", amount)
            if currency is None:
                problems.append(Problem("currency", "required"))
    if currency is not None and _CURRENCY.match(currency) is None:
        problems.append(Problem("currency", "currency_unknown"))
    return problems


def disposal_problems(  # noqa: PLR0913 - one field each, checked together
    *,
    disposed_on: date | None,
    today: date,
    method: str | None,
    reason: str | None,
    cost: object,
    currency: str | None,
) -> list[Problem]:
    """What is wrong with a disposal record, field by field (all at once, never the first only)."""
    return [*_date(disposed_on, today), *_method(method), *_reason(reason), *_money(cost, currency)]
