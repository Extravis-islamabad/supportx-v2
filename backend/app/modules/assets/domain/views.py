"""The asset list's built-in views (WP-049b s4a; REQ-AST-047). Pure.

`recently_discovered` lists assets discovery found in the last RECENT_DAYS days; it stays empty
until discovery (WP-050) exists, and the screen says so.
"""

from enum import StrEnum

RECENT_DAYS = 30
LIST_KEY = "assets"  # the asset list's key in the shared list-settings store
CONSUMABLES_LIST_KEY = "asset_consumables"  # the consumables list's


class AssetView(StrEnum):
    """A built-in view of the asset list."""

    ALL = "all"
    MINE = "mine"
    SCAN_FAILURES = "scan_failures"
    LOANABLE = "loanable"
    IN_STOCK = "in_stock"
    WARRANTY_EXPIRING = "warranty_expiring"
    RECENTLY_DISCOVERED = "recently_discovered"


VIEW_CODES: tuple[str, ...] = tuple(v.value for v in AssetView)
