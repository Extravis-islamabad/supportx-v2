"""The asset record's pure rules (WP-049a s2; parity 07 §3: REQ-AST-002, 007, 008, 011). No I/O."""

import re
from dataclasses import dataclass
from datetime import date

from app.modules.assets.domain.catalogue import AssetStateCategory, AssetTypeCategory, AssetTypeKind

NAME_MAX = 200
IDENTIFIER_MAX = 120  # asset tag, serial, discovered serial, barcode
LOCATION_MAX = 200
# Identifiers: letters, digits and the separators labels print; no spaces inside.
IDENTIFIER = re.compile(r"^[\w\-./:#]+$", re.UNICODE)
COUNTER = "{n}"
SHARED_COUNTER_KEY = "ASSET_TAG"  # types without their own pattern share one counter
# Hex digits as letters: counter keys allow letters and underscores only (display_ids).
_HEX_AS_LETTERS = str.maketrans("0123456789abcdef", "GHIJKLMNOPABCDEF")


def clean_identifier(value: object) -> str | None:
    """Trimmed; blank is None. Case is kept (labels print it); uniqueness ignores it."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def identifier_problem(value: str | None) -> str | None:
    """A code for what is wrong with an identifier, or None."""
    if value is None:
        return None
    if len(value) > IDENTIFIER_MAX:
        return "value_too_long"
    if not IDENTIFIER.match(value):
        return "asset_identifier_invalid"
    return None


def tag_counter_key(product_type_id: str | None) -> str:
    """The display-ID counter a tag pattern draws from: its own type's, or the shared one.

    A type with its own pattern counts on its own (LT-1, LT-2, ...); the counter never goes back,
    so a deleted asset's tag is never handed out again (REQ-AST-008 AC2).
    """
    if product_type_id is None:
        return SHARED_COUNTER_KEY
    return "AT_" + product_type_id.replace("-", "").lower().translate(_HEX_AS_LETTERS).upper()


def format_tag(pattern: str, number: int) -> str:
    """`LT-{n}` with 7 → `LT-7` (the pattern holds exactly one `{n}`, checked when saved)."""
    return pattern.replace(COUNTER, str(number), 1)


def counts_toward_limit(
    category: AssetTypeCategory | str,
    kind: AssetTypeKind | str,
    state: AssetStateCategory | str,
) -> bool:
    """Whether an asset uses one of the plan's managed-asset slots (REQ-AST-002, D-141).

    Only IT assets count; components, consumables and non-IT assets never do, and a disposed
    asset frees its slot.
    """
    return (
        category == AssetTypeCategory.IT
        and kind == AssetTypeKind.ASSET
        and state != AssetStateCategory.DISPOSED
    )


@dataclass(frozen=True, slots=True)
class Age:
    """Whole years, months and days between two dates (REQ-AST-011)."""

    years: int
    months: int
    days: int


def age(since: date, today: date) -> Age | None:
    """The age from `since` to `today`; None for a date in the future."""
    if since > today:
        return None
    months = (today.year - since.year) * 12 + today.month - since.month
    if today.day < since.day:
        months -= 1
    # The day count runs from the same day of the last whole month, clamped to month ends.
    anchor_month = since.month + months
    year, month = since.year + (anchor_month - 1) // 12, (anchor_month - 1) % 12 + 1
    day = min(since.day, _days_in(year, month))
    days = (today - date(year, month, day)).days
    return Age(months // 12, months % 12, days)


def _days_in(year: int, month: int) -> int:
    next_month = date(year + month // 12, month % 12 + 1, 1)
    return (next_month - date(year, month, 1)).days
