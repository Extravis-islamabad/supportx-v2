"""Bulk actions, merges and imports of assets (WP-049b S4b; REQ-AST-051, 052, 053). Pure.

- **Bulk (051):** at most MAX_BULK assets per job (architecture.md §10), run in batches of
  BULK_BATCH per transaction. Edit takes only the fields in EDIT_FIELDS (never money, never an
  identifier: those are one asset at a time); move takes a state; assign a holder; delete is the
  trash, never a hard delete.
- **Merge (052):** which fields a person chooses between, and which asset is suggested to survive:
  the discovered one over one added by hand or from a PO, and the newest scan between discovered
  ones (the spec's default).
- **Import (053):** the columns of each kind, read with WP-021's limits (app/shared/sheets.py),
  up to MAX_IMPORT_ROWS rows.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from app.modules.assets.domain.catalogue import Problem
from app.shared import sheets

# --- bulk actions (REQ-AST-051) ---------------------------------------------------------------

MAX_BULK = 1000  # architecture.md §10: bulk ≤ 1,000 items, as background jobs
BULK_BATCH = 50  # assets per transaction; lists refresh once per batch (as work items')
BULK_TOO_MANY = "asset_bulk_too_many"  # the existing error code (and label)


class AssetBulkAction(StrEnum):
    """What a bulk job does to each asset."""

    EDIT = "edit"
    MOVE = "move"
    ASSIGN = "assign"
    DELETE = "delete"


class AssetBulkStatus(StrEnum):
    """Where a bulk job is."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"  # the job itself broke (logged); assets already done stay done


class AssetBulkOutcome(StrEnum):
    """What happened to one asset of a bulk job."""

    DONE = "done"
    SKIPPED = "skipped"  # with the reason as an error code and params, shown in words


# The fields a bulk edit may set: what many assets share. Money (D-157), identifiers (unique)
# and custom fields stay one asset at a time.
EDIT_FIELDS = frozenset(
    {
        "product_id",
        "vendor_id",
        "site_id",
        "location",
        "description",
        "cost_centre",
        "gl_code",
        "acquired_on",
        "warranty_expires_on",
        "expires_on",
    }
)
HOLDER_KINDS = ("user", "department")
_KEYS: Mapping[AssetBulkAction, frozenset[str]] = {
    AssetBulkAction.EDIT: EDIT_FIELDS,
    AssetBulkAction.MOVE: frozenset({"to_state_id", "reason"}),
    AssetBulkAction.ASSIGN: frozenset({"holder_kind", "holder_id"}),
    AssetBulkAction.DELETE: frozenset(),
}


def bulk_change_problems(action: AssetBulkAction, changes: Mapping[str, Any]) -> list[Problem]:
    """What is wrong with a job's changes before any asset is touched."""
    problems: list[Problem] = []
    unknown = sorted(set(changes) - _KEYS[action])
    problems += [Problem(f"changes.{name}", "invalid_choice") for name in unknown]
    if action == AssetBulkAction.EDIT and not changes:
        problems.append(Problem("changes", "required"))  # only what the person changed, and some
    if action == AssetBulkAction.MOVE and not changes.get("to_state_id"):
        problems.append(Problem("changes.to_state_id", "required"))
    if action == AssetBulkAction.ASSIGN:
        kind = changes.get("holder_kind")
        if kind is not None and kind not in HOLDER_KINDS:
            problems.append(Problem("changes.holder_kind", "invalid_choice"))
        if (kind is None) != (changes.get("holder_id") is None):
            problems.append(Problem("changes.holder_id", "required"))
    return problems


# --- merging duplicates (REQ-AST-052) ---------------------------------------------------------


class MergeSide(StrEnum):
    """Whose value a merged field keeps."""

    SURVIVOR = "survivor"
    MERGED = "merged"


# The fields a merge chooses between. Identifiers stay on each asset: the merged asset's tag,
# serial and barcode find the survivor through the merge's alias instead (they stay unique,
# trash included). MONEY_CHOICES need assets.view_financials (D-157).
MERGE_FIELDS: tuple[str, ...] = (
    "name",
    "product_id",
    "site_id",
    "location",
    "vendor_id",
    "purchase_order_id",
    "acquired_on",
    "warranty_expires_on",
    "expires_on",
    "description",
    "cost_centre",
    "gl_code",
    "currency",
    "purchase_price",
    "purchase_tax",
)
MONEY_CHOICES = frozenset({"purchase_price", "purchase_tax"})


@dataclass(frozen=True, slots=True)
class MergeCandidate:
    """What decides the suggested survivor: discovered, and when last scanned."""

    discovered: bool
    last_scanned_at: datetime | None


def suggest_survivor(first: MergeCandidate, second: MergeCandidate) -> int:
    """0 or 1: which asset should survive (the spec's default; the person may swap them)."""
    if first.discovered != second.discovered:
        return 0 if first.discovered else 1
    if first.discovered and first.last_scanned_at != second.last_scanned_at:
        if first.last_scanned_at is None:
            return 1
        if second.last_scanned_at is None:
            return 0
        return 0 if first.last_scanned_at >= second.last_scanned_at else 1
    return 0


def default_side(survivor_value: object, merged_value: object) -> MergeSide:
    """Keep the survivor's value unless it has none and the merged asset has one."""
    if survivor_value in (None, "") and merged_value not in (None, ""):
        return MergeSide.MERGED
    return MergeSide.SURVIVOR


def merge_choice_problems(choices: Mapping[str, str], *, sees_money: bool) -> list[Problem]:
    """Unknown fields or sides, and money chosen by someone who may not see it."""
    problems: list[Problem] = []
    for field, side in choices.items():
        if field not in MERGE_FIELDS or side not in {s.value for s in MergeSide}:
            problems.append(Problem(f"choices.{field}", "invalid_choice"))
        elif field in MONEY_CHOICES and side == MergeSide.MERGED and not sees_money:
            problems.append(Problem(f"choices.{field}", "permission_denied"))
    return problems


# --- imports (REQ-AST-053) --------------------------------------------------------------------

MAX_IMPORT_ROWS = 20_000  # the spec's target (AC1); every other limit is WP-021's
IMPORT_LIMITS = sheets.SheetLimits(max_rows=MAX_IMPORT_ROWS)
MAX_IMPORT_PROBLEMS = 5000  # kept on the import (the error file); the counts stay exact beyond


class ImportKind(StrEnum):
    """What a file holds."""

    ASSETS = "assets"
    CONSUMABLES = "consumables"
    VENDORS = "vendors"


class ImportMode(StrEnum):
    """What a row does (no "delete existing and add" mode: the spec's BETTER)."""

    ADD = "add"
    UPDATE = "update"
    ADD_UPDATE = "add_update"


class ImportMatch(StrEnum):
    """How a row finds the record it updates."""

    TAG = "tag"
    SERIAL_NUMBER = "serial_number"
    PRODUCT = "product"  # consumables: one per product
    NAME = "name"  # vendors: names are unique


class AssetImportStatus(StrEnum):
    """Where an import is. `checked`: a dry run finished; the file waits to be run."""

    QUEUED = "queued"
    RUNNING = "running"
    CHECKED = "checked"
    DONE = "done"
    FAILED = "failed"


class ImportRowOutcome(StrEnum):
    """What a row did (or, in a dry run, would do)."""

    CREATED = "created"
    UPDATED = "updated"


MATCHES: Mapping[ImportKind, tuple[ImportMatch, ...]] = {
    ImportKind.ASSETS: (ImportMatch.TAG, ImportMatch.SERIAL_NUMBER),
    ImportKind.CONSUMABLES: (ImportMatch.PRODUCT,),
    ImportKind.VENDORS: (ImportMatch.NAME,),
}

# Column heading (lowercase, spaces or underscores) -> field. Field codes and English headings.
_ASSET_COLUMNS = {
    "name": "name",
    "product": "product",
    "tag": "tag",
    "asset tag": "tag",
    "serial number": "serial_number",
    "serial": "serial_number",
    "barcode": "barcode",
    "site": "site",
    "location": "location",
    "vendor": "vendor",
    "acquired on": "acquired_on",
    "warranty expires on": "warranty_expires_on",
    "expires on": "expires_on",
    "description": "description",
    "cost centre": "cost_centre",
    "cost center": "cost_centre",
    "gl code": "gl_code",
    "purchase price": "purchase_price",
    "purchase tax": "purchase_tax",
    "currency": "currency",
}
_CONSUMABLE_COLUMNS = {
    "product": "product",
    "batch tracked": "batch_tracked",
    "barcode": "barcode",
    "vendor": "vendor",
    "unit cost": "unit_cost",
    "comment": "comment",
}
_VENDOR_COLUMNS = {
    "name": "name",
    "currency": "currency",
    "description": "description",
    "contact person": "contact_person",
    "address": "address",
    "email": "email",
    "phone": "phone",
    "fax": "fax",
    "website": "website",
}
COLUMNS: Mapping[ImportKind, Mapping[str, str]] = {
    ImportKind.ASSETS: _ASSET_COLUMNS,
    ImportKind.CONSUMABLES: _CONSUMABLE_COLUMNS,
    ImportKind.VENDORS: _VENDOR_COLUMNS,
}
# A file must name these (the key the rows are found or made by).
REQUIRED_COLUMNS: Mapping[ImportKind, frozenset[str]] = {
    ImportKind.ASSETS: frozenset(),  # checked per match: the tag or serial column, see below
    ImportKind.CONSUMABLES: frozenset({"product"}),
    ImportKind.VENDORS: frozenset({"name"}),
}
NO_HEADER = "no_header"
UNKNOWN_COLUMN = "unknown_column"
NO_KEY_COLUMN = "no_key_column"
TRUE_WORDS = frozenset({"yes", "y", "true", "1", "x"})
FALSE_WORDS = frozenset({"no", "n", "false", "0"})


class ImportRefused(Exception):
    """The file cannot be imported at all: a sheet code or one of the header codes above."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        """`detail`: the unknown column's heading, or the row with a long cell."""
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ImportRows:
    """The mapped header and the data rows (row numbers as in the file, header = 1)."""

    fields: list[str]
    rows: list[tuple[int, dict[str, str]]]


def _fields(kind: ImportKind, match: ImportMatch, cells: list[str]) -> list[str]:
    known = COLUMNS[kind]
    fields: list[str] = []
    for cell in cells:
        heading = " ".join(cell.strip().lower().replace("_", " ").split())
        if not heading:
            fields.append("")
            continue
        field = known.get(heading)
        if field is None and (code := heading.replace(" ", "_")) in known.values():
            field = code  # the field code itself (serial_number) is a heading too
        if field is None:
            raise ImportRefused(UNKNOWN_COLUMN, cell.strip()[:100])
        fields.append(field)
    if not any(fields):
        raise ImportRefused(NO_HEADER)
    needed = set(REQUIRED_COLUMNS[kind])
    if kind == ImportKind.ASSETS:
        needed.add(match.value)
    if needed - set(fields):
        raise ImportRefused(NO_KEY_COLUMN, min(needed - set(fields)))
    return fields


def read_import(
    kind: ImportKind, match: ImportMatch, file_format: str, content: bytes
) -> ImportRows:
    """Every data row as {field: text}; refuses the whole file when a limit is crossed."""
    header: list[str] | None = None
    rows: list[tuple[int, dict[str, str]]] = []
    try:
        for number, cells in enumerate(sheets.raw_rows(file_format, content, IMPORT_LIMITS), 1):
            if header is None:
                header = _fields(kind, match, cells)
                continue
            if not any(cell.strip() for cell in cells):
                continue
            values = {
                field: cells[index].strip()
                for index, field in enumerate(header)
                if field and index < len(cells)
            }
            rows.append((number, values))
    except sheets.SheetRefused as refused:
        raise ImportRefused(refused.code, refused.detail) from refused
    if header is None:
        raise ImportRefused(NO_HEADER)
    if not rows:
        raise ImportRefused(sheets.FILE_EMPTY)
    return ImportRows([f for f in header if f], rows)


def flag(value: str) -> bool | None:
    """Yes/no cells; None when the cell says neither."""
    word = value.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    return None


def day(value: str) -> date | None:
    """A date cell: ISO (2026-11-11), or Excel's date as openpyxl writes it (with a time)."""
    text = value.strip()
    if len(text) < 10:  # noqa: PLR2004 - YYYY-MM-DD
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
