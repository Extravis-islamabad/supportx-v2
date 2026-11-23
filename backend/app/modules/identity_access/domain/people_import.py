"""Reading a people file, CSV or Excel (WP-021, REQ-ADM-003). No database here.

Limits protect the import job from oversized and "bomb" files (product owner, WP-021): the file
size, the rows, the columns and the characters per cell are capped, and an Excel file (a zip) is
checked before it is opened: entry count, total unpacked size and compression ratio. Excel is
read with openpyxl in read-only mode, values only (formulas are never evaluated). The reading
itself is app/shared/sheets.py (shared with the asset imports, WP-049b S4b); these are its limits.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum

from app.shared import sheets

MAX_FILE_BYTES = sheets.MAX_FILE_BYTES
MAX_ROWS = 5000
MAX_COLUMNS = sheets.MAX_COLUMNS
MAX_CELL_CHARS = sheets.MAX_CELL_CHARS
LIMITS = sheets.SheetLimits(max_rows=MAX_ROWS)

# Column heading (lowercase, spaces or underscores) → field. Field codes and English headings.
COLUMNS: dict[str, str] = {
    "first name": "first_name",
    "last name": "last_name",
    "display name": "display_name",
    "email": "email",
    "email address": "email",
    "employee id": "employee_id",
    "job title": "job_title",
    "phone": "phone",
    "mobile": "mobile",
    "site": "site",
    "department": "department",
    "manager": "manager",
    "manager email": "manager",
    "type": "user_type",
    "user type": "user_type",
    "vip": "vip",
    "can sign in": "can_sign_in",
    "sign in": "can_sign_in",
    "language": "locale",
    "locale": "locale",
}
TRUE_WORDS = frozenset({"yes", "y", "true", "1", "x"})
FALSE_WORDS = frozenset({"no", "n", "false", "0", ""})


class ImportFailure(StrEnum):
    """Why a whole file was refused (labels `people_import_failure.<code>`)."""

    TOO_LARGE = "file_too_large"
    NOT_READABLE = "file_not_readable"
    NOT_UTF8 = "file_not_utf8"
    UNSAFE = "file_unsafe"
    TOO_MANY_ROWS = "too_many_rows"
    TOO_MANY_COLUMNS = "too_many_columns"
    CELL_TOO_LONG = "cell_too_long"
    NO_HEADER = "no_header"
    UNKNOWN_COLUMN = "unknown_column"
    NO_NAME_COLUMN = "no_name_column"
    EMPTY = "file_empty"


class ImportRefused(Exception):
    """The file cannot be imported at all."""

    def __init__(self, failure: ImportFailure, detail: str | None = None) -> None:
        """`detail`: e.g. the unknown column's heading (shown to the admin)."""
        super().__init__(failure.value)
        self.failure = failure
        self.detail = detail


@dataclass(frozen=True)
class SheetRows:
    """The mapped header and the data rows (row numbers as in the file, header = 1)."""

    fields: list[str]
    rows: list[tuple[int, dict[str, str]]]


def file_format(file_name: str, content: bytes) -> str:
    """The file's kind, csv or xlsx: by the content (an xlsx is a zip) and the extension."""
    with _refusals():
        return sheets.file_format(file_name, content)


def flag(value: str) -> bool | None:
    """Yes/no cells; None when the cell says neither."""
    word = value.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    return None


def read_rows(file_format_code: str, content: bytes) -> SheetRows:
    """Every data row as {field: text}; refuses the whole file when a limit is crossed."""
    header: list[str] | None = None
    rows: list[tuple[int, dict[str, str]]] = []
    with _refusals():
        for number, cells in enumerate(sheets.raw_rows(file_format_code, content, LIMITS), 1):
            if header is None:
                header = _fields(cells)
                continue
            if not any(cell.strip() for cell in cells):
                continue
            values = {
                field: cells[index].strip()
                for index, field in enumerate(header)
                if field and index < len(cells)
            }
            rows.append((number, values))
    if header is None:
        raise ImportRefused(ImportFailure.NO_HEADER)
    if not rows:
        raise ImportRefused(ImportFailure.EMPTY)
    return SheetRows([f for f in header if f], rows)


@contextmanager
def _refusals() -> Iterator[None]:
    """The shared reader's refusals as this import's (the same codes)."""
    try:
        yield
    except sheets.SheetRefused as refused:
        raise ImportRefused(ImportFailure(refused.code), refused.detail) from refused


def _fields(cells: list[str]) -> list[str]:
    fields: list[str] = []
    for cell in cells:
        heading = " ".join(cell.strip().lower().replace("_", " ").split())
        if not heading:
            fields.append("")
            continue
        field = COLUMNS.get(heading)
        if field is None:
            raise ImportRefused(ImportFailure.UNKNOWN_COLUMN, cell.strip()[:100])
        fields.append(field)
    if not any(fields):
        raise ImportRefused(ImportFailure.NO_HEADER)
    if "first_name" not in fields:
        raise ImportRefused(ImportFailure.NO_NAME_COLUMN)
    return fields


def check_zip(content: bytes) -> None:
    """Refuse an xlsx whose zip could unpack to far more than it weighs (a "bomb")."""
    with _refusals():
        sheets.check_zip(content)
