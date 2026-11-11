"""The rules of the list-settings store (WP-049b s4a; REQ-AST-047, REQ-INC-104, 106, 107). Pure.

One row per person, list and view: its columns (with widths), sort, page size and whether the
person starred it. A saved view is such a row whose key is `custom:<its id>`, with a name and a
filter of its own. Settings never cross people, lists or views.
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

PAGE_SIZES = (25, 50, 100)
DEFAULT_PAGE_SIZE = 50
MAX_COLUMNS = 40
MIN_WIDTH, MAX_WIDTH = 60, 800
NAME_MAX = 120
SORT_MAX = 200
LIST_KEY_MAX = 60
VIEW_KEY_MAX = 80
MAX_SAVED_VIEWS = 100  # per person and list
CUSTOM = "custom:"  # a saved view's key: "custom:<view id>"
ALL = "all"  # the list with no view: everything the person may see

_COLUMN_KEY = re.compile(r"^[a-z][a-z0-9_.]{0,79}$")
_LIST_KEY = re.compile(r"^[a-z][a-z0-9_]{0,59}$")


@dataclass(frozen=True, slots=True)
class Problem:
    """One field problem; the service turns it into an RFC 9457 field error."""

    field: str
    code: str
    params: tuple[tuple[str, int | str], ...] = ()


def list_key_valid(key: str) -> bool:
    """Lowercase snake case, e.g. `assets`."""
    return bool(_LIST_KEY.match(key))


def saved_view_id(view_key: str) -> uuid.UUID | None:
    """The saved view's ID in a `custom:<id>` key, else None."""
    if not view_key.startswith(CUSTOM):
        return None
    try:
        return uuid.UUID(view_key.removeprefix(CUSTOM))
    except ValueError:
        return None


def custom_key(view_id: uuid.UUID) -> str:
    """The view key of a saved view."""
    return f"{CUSTOM}{view_id}"


def view_key_valid(view_key: str, builtin: Sequence[str]) -> bool:
    """A built-in view of the list, `all`, or `custom:<uuid>`."""
    return view_key == ALL or view_key in builtin or saved_view_id(view_key) is not None


def width_valid(width: int) -> bool:
    """A column width a person may drag to."""
    return MIN_WIDTH <= width <= MAX_WIDTH


def _column_problem(column: object, seen: set[str]) -> Problem | None:
    if not isinstance(column, Mapping):
        return Problem("columns", "invalid_choice")
    key, width = column.get("key"), column.get("width")
    if not isinstance(key, str) or not _COLUMN_KEY.match(key) or key in seen:
        return Problem("columns", "invalid_choice")
    if width is not None and (
        isinstance(width, bool) or not isinstance(width, int) or not width_valid(width)
    ):
        return Problem("columns", "out_of_range", (("min", MIN_WIDTH), ("max", MAX_WIDTH)))
    return None


def clean_columns(columns: object) -> tuple[list[dict[str, Any]], list[Problem]]:
    """Each column once, `{"key", "width"}` (width None: automatic); at most MAX_COLUMNS.

    Keys are checked for shape only: a column of a field removed later is dropped by the screen.
    """
    if columns is None:
        return [], []
    if not isinstance(columns, Sequence) or isinstance(columns, str):
        return [], [Problem("columns", "invalid_choice")]
    if len(columns) > MAX_COLUMNS:
        return [], [Problem("columns", "too_many_items", (("max", MAX_COLUMNS),))]
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for column in columns:
        if problem := _column_problem(column, seen):
            return [], [problem]
        seen.add(column["key"])
        clean.append({"key": column["key"], "width": column.get("width")})
    return clean, []


def clean_name(raw: object) -> tuple[str | None, list[Problem]]:
    """A saved view's name: one line, required, at most NAME_MAX."""
    name = " ".join(str(raw or "").split())
    if not name:
        return None, [Problem("name", "required")]
    if len(name) > NAME_MAX:
        return None, [Problem("name", "value_too_long", (("max", NAME_MAX),))]
    return name, []


def page_size_problems(page_size: object) -> list[Problem]:
    """25, 50 or 100."""
    if isinstance(page_size, bool) or page_size not in PAGE_SIZES:
        return [Problem("page_size", "invalid_choice")]
    return []
