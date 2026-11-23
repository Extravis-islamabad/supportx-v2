"""Checklists on work items (WP-046a S2; REQ-INC-077, -078). Pure rules.

Items are short lines of text. Empty ones are dropped on save and the caller is told how many
(AC2); a checklist holds at most the type's limit (100 by default, admins change it).
"""

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

TITLE_MAX = 200
ITEM_MAX = 500
DEFAULT_ITEM_LIMIT = 100


@dataclass(frozen=True)
class CleanItems:
    """The items kept, in order, and how many empty ones were dropped."""

    items: list[str]
    dropped: int


def clean_items(raw: Iterable[object]) -> CleanItems:
    """Trim each item, drop the empty ones (AC2), collapse inner whitespace."""
    kept: list[str] = []
    dropped = 0
    for value in raw:
        text = " ".join(str(value or "").split())
        if text:
            kept.append(text)
        else:
            dropped += 1
    return CleanItems(kept, dropped)


def item_problems(items: list[str], limit: int) -> list[tuple[str, str]]:
    """(field, code) for items too long or too many."""
    problems: list[tuple[str, str]] = []
    if len(items) > limit:
        problems.append(("items", "too_many_items"))
    problems += [(f"items.{i}", "value_too_long") for i, t in enumerate(items) if len(t) > ITEM_MAX]
    return problems


# CSV import (REQ-INC-078 AC1): the same limits as the other imports (people, WP-021).
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 40


class ImportFailure(StrEnum):
    """Why a whole file was refused (labels `checklist_import_failure.<code>`)."""

    TOO_LARGE = "too_large"
    NOT_TEXT = "not_text"
    TOO_MANY_ROWS = "too_many_rows"
    TOO_MANY_COLUMNS = "too_many_columns"


@dataclass(frozen=True)
class ImportedItems:
    """The items read (first column of each row, in order) and the rows refused, with why."""

    items: list[str]
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (row number, reason code)


def parse_items_csv(content: bytes, *, limit: int) -> ImportedItems | ImportFailure:
    """Checklist items from a CSV: one per row, its first column (AC1: good rows kept).

    A header row "item" (any case) is skipped. A row refused says why: empty, too long, or past
    the checklist's item limit.
    """
    if len(content) > MAX_FILE_BYTES:
        return ImportFailure.TOO_LARGE
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ImportFailure.NOT_TEXT
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) > MAX_ROWS:
        return ImportFailure.TOO_MANY_ROWS
    if any(len(row) > MAX_COLUMNS for row in rows):
        return ImportFailure.TOO_MANY_COLUMNS
    items: list[str] = []
    rejected: list[tuple[int, str]] = []
    for number, row in enumerate(rows, start=1):
        value = " ".join((row[0] if row else "").split())
        if number == 1 and value.casefold() == "item":
            continue
        if not value:
            rejected.append((number, "empty"))
        elif len(value) > ITEM_MAX:
            rejected.append((number, "value_too_long"))
        elif len(items) >= limit:
            rejected.append((number, "too_many_items"))
        else:
            items.append(value)
    return ImportedItems(items, rejected)


def progress(done: int, total: int) -> int:
    """Percent done, rounded down; an empty checklist is 0."""
    return (100 * done) // total if total else 0


__all__ = [
    "DEFAULT_ITEM_LIMIT",
    "ITEM_MAX",
    "MAX_FILE_BYTES",
    "TITLE_MAX",
    "CleanItems",
    "ImportFailure",
    "ImportedItems",
    "clean_items",
    "item_problems",
    "parse_items_csv",
    "progress",
]
