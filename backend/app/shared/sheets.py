"""Reading an uploaded CSV or Excel file safely, for import jobs. No database here.

Taken out of the people import (WP-021) so every import reads files the same way (assets,
consumables and vendors from WP-049b S4b, REQ-AST-053). The limits protect the import job from
oversized and "bomb" files (product owner, WP-021): the file size, the rows, the columns and the
characters per cell are capped, and an Excel file (a zip) is checked before it is opened: entry
count, total unpacked size and compression ratio. Excel is read with openpyxl in read-only
mode, values only (formulas are never evaluated), and rows past the limit are never read.

Each import keeps WP-021's limits; only the row cap may differ by import (`SheetLimits`).
"""

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_COLUMNS = 40
MAX_CELL_CHARS = 5000
MAX_ZIP_ENTRIES = 200
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
MAX_RATIO = 100  # unpacked / packed, per entry
RATIO_FROM_BYTES = 1024  # tiny entries (empty parts) compress far better and are harmless
XLSX_MAGIC = b"PK\x03\x04"

# Why a whole file was refused: codes each import labels in its own words.
FILE_TOO_LARGE = "file_too_large"
FILE_NOT_READABLE = "file_not_readable"
FILE_NOT_UTF8 = "file_not_utf8"
FILE_UNSAFE = "file_unsafe"
FILE_EMPTY = "file_empty"
TOO_MANY_ROWS = "too_many_rows"
TOO_MANY_COLUMNS = "too_many_columns"
CELL_TOO_LONG = "cell_too_long"


class SheetRefused(Exception):
    """The file cannot be read at all: one of the codes above, and a detail (a row number)."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        """`detail`: shown to the person beside the reason (e.g. the row with a long cell)."""
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class SheetLimits:
    """The caps of one import. WP-021's values; the row cap is the import's own."""

    max_rows: int
    max_file_bytes: int = MAX_FILE_BYTES
    max_columns: int = MAX_COLUMNS
    max_cell_chars: int = MAX_CELL_CHARS


def file_format(file_name: str, content: bytes) -> str:
    """The file's kind, csv or xlsx: by the content (an xlsx is a zip) and the extension."""
    name = file_name.lower()
    if content.startswith(XLSX_MAGIC) and name.endswith(".xlsx"):
        return "xlsx"
    if name.endswith((".csv", ".txt")) and not content.startswith(XLSX_MAGIC):
        return "csv"
    raise SheetRefused(FILE_NOT_READABLE)


def raw_rows(file_format_code: str, content: bytes, limits: SheetLimits) -> Iterator[list[str]]:
    """Every row of the file as text cells (the header included), checked against `limits`.

    The data rows are counted as they come (blank rows skipped), so a file one row over the cap
    is refused without reading the rest.
    """
    if len(content) > limits.max_file_bytes:
        raise SheetRefused(FILE_TOO_LARGE)
    source = _xlsx_rows(content, limits) if file_format_code == "xlsx" else _csv_rows(content)
    data_rows = 0
    for number, cells in enumerate(source, start=1):
        if len(cells) > limits.max_columns:
            raise SheetRefused(TOO_MANY_COLUMNS)
        if any(len(cell) > limits.max_cell_chars for cell in cells):
            raise SheetRefused(CELL_TOO_LONG, str(number))
        if number > 1 and any(cell.strip() for cell in cells):
            data_rows += 1
            if data_rows > limits.max_rows:
                raise SheetRefused(TOO_MANY_ROWS)
        yield cells


def csv_rows(content: bytes) -> Iterator[list[str]]:
    """A CSV file's rows (UTF-8, with or without a BOM; comma, semicolon or tab)."""
    return _csv_rows(content)


def _csv_rows(content: bytes) -> Iterator[list[str]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SheetRefused(FILE_NOT_UTF8) from exc
    try:
        dialect = csv.Sniffer().sniff(decoded[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(decoded), dialect)
    try:
        yield from reader
    except csv.Error as exc:
        raise SheetRefused(FILE_NOT_READABLE) from exc


def check_zip(content: bytes) -> None:
    """Refuse an xlsx whose zip could unpack to far more than it weighs (a "bomb")."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise SheetRefused(FILE_NOT_READABLE) from exc
    if len(entries) > MAX_ZIP_ENTRIES:
        raise SheetRefused(FILE_UNSAFE)
    total = 0
    for entry in entries:
        total += entry.file_size
        if total > MAX_UNPACKED_BYTES:
            raise SheetRefused(FILE_UNSAFE)
        if (
            entry.file_size > MAX_RATIO * max(entry.compress_size, 1)
            and entry.file_size > RATIO_FROM_BYTES
        ):
            raise SheetRefused(FILE_UNSAFE)


def xlsx_rows(content: bytes, limits: SheetLimits) -> Iterator[list[str]]:
    """An Excel file's first sheet, after the zip check (read-only, values only)."""
    return _xlsx_rows(content, limits)


def _xlsx_rows(content: bytes, limits: SheetLimits) -> Iterator[list[str]]:
    check_zip(content)
    from openpyxl import load_workbook  # noqa: PLC0415 - only the import jobs need it

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types for a broken file
        raise SheetRefused(FILE_NOT_READABLE) from exc
    try:
        sheet = workbook.worksheets[0] if workbook.worksheets else None
        if sheet is None:
            raise SheetRefused(FILE_EMPTY)
        # Rows past the limit are never read: max_row stops openpyxl itself.
        for values in sheet.iter_rows(
            max_row=limits.max_rows + 2, max_col=limits.max_columns + 1, values_only=True
        ):
            cells = ["" if value is None else _cell(value) for value in values]
            while cells and not cells[-1]:
                cells.pop()
            yield cells
    finally:
        workbook.close()


def _cell(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # Excel stores 1001 as 1001.0 (employee IDs, phones, quantities)
    return str(value)
