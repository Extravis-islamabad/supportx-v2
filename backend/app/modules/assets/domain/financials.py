"""An asset's money: cost lines, total cost of ownership and depreciation (WP-049b s2).

Pure Python, no I/O (architecture.md §6.3). Parity 07 §9:

- **Cost lines (REQ-AST-036):** besides the purchase (the asset's price and tax, D-141), an asset
  has operational costs (a move, a service, a contract, anything else) and disposal costs, each
  with a date, an amount and a description. The total cost of ownership is purchase plus
  operational plus disposal. Amounts are `Decimal` all the way: no float ever touches them, so
  1,000 lines add up to the cent (AC3). Everything is in the tenant's base currency; nothing is
  converted (an asset bought in another currency is shown as such, never converted).
- **Depreciation (REQ-AST-037):** straight line, declining balance (150 %), double declining
  balance (200 %) and the sum of the years' digits, or none. The yearly amounts are worked out
  to the cent, the last year taking what rounding left over, so the book value ends exactly at
  the salvage value. The declining methods switch to straight line once that writes off more
  (the usual rule, so the salvage value is reached at the end of the useful life). Within a year
  the amount is spread evenly by month: a month counts once its day of the month is reached
  (or the month's last day, for a shorter month).
- **Settings (AC2):** the asset's own method, life and salvage value win; whatever it leaves
  empty comes from its product. `none` on the asset means no depreciation, whatever the product
  says.
"""

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.modules.assets.domain.catalogue import AssetDepreciationMethod, Problem, amount_problems

CENT = Decimal("0.01")
ZERO = Decimal(0)
LIFE_MAX = 100  # years
COST_DESCRIPTION_MAX = 500
COST_CENTRE_MAX = 60
GL_CODE_MAX = 40  # as on products (asset_products.gl_code)
# Declining balance: the straight-line rate times this factor (the usual 150 % and 200 %).
FACTORS = {
    AssetDepreciationMethod.DECLINING_BALANCE: Decimal("1.5"),
    AssetDepreciationMethod.DOUBLE_DECLINING_BALANCE: Decimal(2),
}


class DepreciationChoice(StrEnum):
    """What an asset says about its depreciation: a method, or `none` (none at all)."""

    STRAIGHT_LINE = "straight_line"
    DECLINING_BALANCE = "declining_balance"
    DOUBLE_DECLINING_BALANCE = "double_declining_balance"
    SUM_OF_YEARS_DIGITS = "sum_of_years_digits"
    NONE = "none"


class CostKind(StrEnum):
    """A cost line's kind (REQ-AST-036). The purchase is the asset's own price and tax."""

    MOVE = "move"
    SERVICE = "service"
    CONTRACT = "contract"
    OTHER = "other"
    DISPOSAL = "disposal"


OPERATIONAL = frozenset({CostKind.MOVE, CostKind.SERVICE, CostKind.CONTRACT, CostKind.OTHER})


class TermsSource(StrEnum):
    """Where an asset's depreciation settings came from (shown next to them)."""

    ASSET = "asset"
    PRODUCT = "product"


@dataclass(frozen=True, slots=True)
class CostSummary:
    """The four summary cards (REQ-AST-036), without the book value (see `book_value`)."""

    purchase: Decimal
    operational: Decimal
    disposal: Decimal

    @property
    def total(self) -> Decimal:
        """Total cost of ownership: purchase, operational and disposal costs."""
        return self.purchase + self.operational + self.disposal


def summarize(purchase: Decimal | None, lines: Iterable[tuple[str, Decimal]]) -> CostSummary:
    """Purchase plus each line by its kind (`(kind, amount)`), exactly."""
    operational = ZERO
    disposal = ZERO
    for kind, amount in lines:
        if kind == CostKind.DISPOSAL:
            disposal += amount
        else:
            operational += amount
    return CostSummary(purchase or ZERO, operational, disposal)


@dataclass(frozen=True, slots=True)
class Terms:
    """What depreciation needs: the cost, from when, how, over how long, down to what."""

    method: AssetDepreciationMethod | None  # None: no depreciation
    cost: Decimal
    starts_on: date | None
    life_years: int | None
    salvage: Decimal = ZERO

    @property
    def depreciates(self) -> bool:
        """Whether there is anything to work out (a method, a start, a life, a cost)."""
        return (
            self.method is not None
            and self.starts_on is not None
            and self.life_years is not None
            and self.life_years > 0
            and self.cost > self.salvage
        )


@dataclass(frozen=True, slots=True)
class ResolvedTerms:
    """The settings in effect and where each came from (None: not set anywhere)."""

    choice: DepreciationChoice | None
    method_from: TermsSource | None
    life_years: int | None
    life_from: TermsSource | None
    salvage: Decimal | None
    salvage_from: TermsSource | None

    @property
    def method(self) -> AssetDepreciationMethod | None:
        """The method that applies; None for `none` or nothing set."""
        if self.choice is None or self.choice == DepreciationChoice.NONE:
            return None
        return AssetDepreciationMethod(self.choice.value)


def resolve(  # noqa: PLR0913 - the asset's three settings and the product's three, explicit
    *,
    asset_method: str | None,
    asset_life: int | None,
    asset_salvage: Decimal | None,
    product_method: str | None,
    product_life: int | None,
    product_salvage: Decimal | None,
) -> ResolvedTerms:
    """The asset's own settings first; what it leaves empty comes from its product (AC2)."""

    def pick[T](own: T | None, inherited: T | None) -> tuple[T | None, TermsSource | None]:
        if own is not None:
            return own, TermsSource.ASSET
        if inherited is not None:
            return inherited, TermsSource.PRODUCT
        return None, None

    method, method_from = pick(asset_method, product_method)
    life, life_from = pick(asset_life, product_life)
    salvage, salvage_from = pick(asset_salvage, product_salvage)
    return ResolvedTerms(
        choice=None if method is None else DepreciationChoice(method),
        method_from=method_from,
        life_years=life,
        life_from=life_from,
        salvage=salvage,
        salvage_from=salvage_from,
    )


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def yearly_amounts(terms: Terms) -> list[Decimal]:
    """Each year's depreciation, to the cent; they add up to cost minus salvage exactly."""
    if not terms.depreciates:
        return []
    assert terms.method is not None  # noqa: S101 - depreciates says so
    assert terms.life_years is not None  # noqa: S101 - depreciates says so
    life = terms.life_years
    base = terms.cost - terms.salvage
    amounts: list[Decimal] = []
    if terms.method == AssetDepreciationMethod.STRAIGHT_LINE:
        amounts = [_cents(base / life) for _ in range(life)]
    elif terms.method == AssetDepreciationMethod.SUM_OF_YEARS_DIGITS:
        digits = life * (life + 1) // 2
        amounts = [_cents(base * (life - year) / digits) for year in range(life)]
    else:
        rate = FACTORS[terms.method] / life
        book = terms.cost
        for year in range(life):
            remaining = book - terms.salvage
            straight = remaining / (life - year)  # straight line over what is left
            amount = _cents(min(max(book * rate, straight), remaining))
            amounts.append(amount)
            book -= amount
    # The last year takes what rounding left over (never a cent of drift).
    amounts[-1] += base - sum(amounts, ZERO)
    return amounts


def months_elapsed(starts_on: date, on: date) -> int:
    """Whole months from `starts_on` to `on` (0 before it); a month counts once its day comes.

    A start on the 31st completes a month on the last day of a shorter month (28 Feb).
    """
    if on <= starts_on:
        return 0
    months = (on.year - starts_on.year) * 12 + on.month - starts_on.month
    last_day = calendar.monthrange(on.year, on.month)[1]
    if on.day < min(starts_on.day, last_day):
        months -= 1
    return max(months, 0)


def book_value(terms: Terms, on: date) -> Decimal:
    """The book value on `on`: cost less depreciation so far, by month (never below salvage)."""
    amounts = yearly_amounts(terms)
    if not amounts:
        return terms.cost
    assert terms.starts_on is not None  # noqa: S101 - depreciates says so
    months = months_elapsed(terms.starts_on, on)
    whole, part = divmod(months, 12)
    if whole >= len(amounts):
        return terms.salvage
    taken = sum(amounts[:whole], ZERO) + _cents(amounts[whole] * part / 12)
    return terms.cost - taken


@dataclass(frozen=True, slots=True)
class ScheduleYear:
    """One year of the depreciation schedule (REQ-AST-037)."""

    year: int  # 1 for the first year
    starts_on: date
    opening: Decimal
    depreciation: Decimal
    closing: Decimal


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February in a year without one
        return day.replace(year=day.year + years, day=28)


def schedule(terms: Terms) -> list[ScheduleYear]:
    """The schedule by year: opening value, that year's depreciation, closing value."""
    amounts = yearly_amounts(terms)
    if not amounts:
        return []
    assert terms.starts_on is not None  # noqa: S101 - depreciates says so
    rows: list[ScheduleYear] = []
    book = terms.cost
    for index, amount in enumerate(amounts):
        rows.append(
            ScheduleYear(
                year=index + 1,
                starts_on=_add_years(terms.starts_on, index),
                opening=book,
                depreciation=amount,
                closing=book - amount,
            )
        )
        book -= amount
    return rows


def terms_problems(
    life_years: int | None, salvage: Decimal | None, cost: Decimal | None
) -> list[Problem]:
    """A life of 1 to 100 years; a salvage value that is an amount and not above the cost."""
    problems: list[Problem] = []
    if life_years is not None and not 1 <= life_years <= LIFE_MAX:
        limits = (("min", 1), ("max", LIFE_MAX))
        problems.append(Problem("useful_life_years", "out_of_range", limits))
    problems += amount_problems("salvage_value", salvage)
    if salvage is not None and cost is not None and salvage > cost and not problems:
        problems.append(Problem("salvage_value", "asset_salvage_above_cost"))
    return problems


def cost_line_problems(amount: Decimal | None, description: str | None) -> list[Problem]:
    """A cost line's amount (required, at least zero, cents) and its description's length."""
    problems: list[Problem] = []
    if amount is None:
        problems.append(Problem("amount", "required"))
    else:
        problems += amount_problems("amount", amount)
    if description is not None and len(description) > COST_DESCRIPTION_MAX:
        problems.append(Problem("description", "value_too_long", (("max", COST_DESCRIPTION_MAX),)))
    return problems
