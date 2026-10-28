"""List settings, saved views and bulk jobs (WP-020d; REQ-INC-104, 106, 110, 119, 120).

Pure rules: which page sizes and column widths are allowed, how a view key is spelled and what a
bulk job may ask for. The service checks column keys against the live field catalogue.
"""

import re
import uuid
from enum import StrEnum

PAGE_SIZES = (25, 50, 100)  # REQ-INC-110
DEFAULT_PAGE_SIZE = 50
MAX_COLUMNS = 40
MIN_WIDTH, MAX_WIDTH = 60, 800
MAX_BULK = 1000  # architecture.md §10: bulk ≤ 1,000 items, as background jobs
BULK_BATCH = 50  # records per transaction; lists refresh once per batch (REQ-INC-120)
CUSTOM_VIEW = "custom:"  # list settings of a saved view are keyed "custom:<view id>"
_SORT = re.compile(r"^-?[a-z][a-z0-9_.]{0,79}$")


class BulkAction(StrEnum):
    """What a bulk job does to each record."""

    EDIT = "edit"  # only the fields the user changed (REQ-INC-120 AC2)
    ASSIGN = "assign"
    TAKE = "take"
    RESOLVE = "resolve"
    CLOSE = "close"


class BulkStatus(StrEnum):
    """Where a bulk job is."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"  # the job itself broke (logged); records already done stay done


class BulkOutcome(StrEnum):
    """What happened to one record of a bulk job."""

    DONE = "done"
    SKIPPED = "skipped"  # with the reason as an error code and params, shown in words


class ViewVisibility(StrEnum):
    """Who sees a saved view in their list of views."""

    PRIVATE = "private"
    SHARED = "shared"  # with everyone who may see the list (REQ-INC-106)


def view_key_valid(key: str, builtin: tuple[str, ...]) -> bool:
    """A built-in view code, `custom:<uuid>`, or `all` (the list with no view)."""
    if key in builtin:
        return True
    if not key.startswith(CUSTOM_VIEW):
        return False
    try:
        uuid.UUID(key.removeprefix(CUSTOM_VIEW))
    except ValueError:
        return False
    return True


def sort_valid(sort: str) -> bool:
    """`field` or `-field` (descending); the service checks the field is sortable."""
    return bool(_SORT.match(sort))


def width_valid(width: int | None) -> bool:
    """A column width in pixels, or none for the default."""
    return width is None or MIN_WIDTH <= width <= MAX_WIDTH
