"""Consumables: the pure rules (WP-049b s1; REQ-AST-033, 034, 035). No I/O.

- **Quantities** are exact decimals (three places at most: 2.5 litres, 0.250 kg), never floats.
- **Batches (033 AC2):** a batch whose expiry date has passed is flagged as expired.
- **Minimum stock (035):** the most specific rule decides for a stock row: a product's own rule
  before its type's, a site's own before the any-site one, the nearest type before a parent's.
  A row is alerted once when it falls to or below the minimum and re-armed only once it rises
  above it again (AC1).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

QUANTITY_MAX = Decimal("99999999999.999")  # NUMERIC(14, 3)
QUANTITY_PLACES = 3
MOVEMENT_KINDS = ("receive", "allocate", "adjust", "return")
RECIPIENT_KINDS = ("user", "department", "asset")
LOT_MAX = 120
COMMENT_MAX = 2000

MovementKind = Literal["receive", "allocate", "adjust", "return"]
RecipientKind = Literal["user", "department", "asset"]


def quantity_problem(value: object, *, signed: bool = False) -> str | None:
    """Why `value` is not a usable quantity (a field error code), or None.

    `signed`: an adjustment may be negative, but never zero.
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "invalid_number"
    if not amount.is_finite():
        return "invalid_number"
    if amount == 0 or (amount < 0 and not signed):
        return "asset_quantity_positive"
    if abs(amount) > QUANTITY_MAX:
        return "out_of_range"
    if amount != amount.quantize(Decimal(1).scaleb(-QUANTITY_PLACES)):
        return "too_many_decimals"
    return None


def is_expired(expires_on: date | None, today: date) -> bool:
    """A batch past its expiry date (033 AC2); the expiry day itself is still good."""
    return expires_on is not None and expires_on < today


@dataclass(frozen=True, slots=True)
class RuleCandidate:
    """A minimum-stock rule as the picker sees it.

    `type_depth` is how far up the product's type tree the rule's type is (0: the product's own
    type); None for a rule on the product itself.
    """

    id: str
    product_rule: bool
    site_rule: bool
    type_depth: int | None
    minimum: Decimal


def pick_rule(candidates: Sequence[RuleCandidate]) -> RuleCandidate | None:
    """The most specific rule that applies to one stock row (035)."""
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda r: (
            not r.product_rule,
            not r.site_rule,
            0 if r.type_depth is None else r.type_depth,
            r.id,
        ),
    )


LowStockStep = Literal["alert", "rearm"]


def low_stock_step(
    quantity: Decimal, minimum: Decimal | None, *, alerted: bool
) -> LowStockStep | None:
    """What a stock change means for its alert (035 AC1).

    At or below the minimum and not yet alerted: alert (once). Above it while alerted: re-arm, so
    the next fall alerts again. Anything else: nothing. With no rule, an old alert is re-armed.
    """
    if minimum is None:
        return "rearm" if alerted else None
    if quantity <= minimum and not alerted:
        return "alert"
    if quantity > minimum and alerted:
        return "rearm"
    return None
