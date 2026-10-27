"""What an export contains, independent of the file format (REQ-RPT-058).

A report export is a list of sheets; each sheet has header lines (title, who ran it, when, the
time zone, the filters in words), labelled columns, rows of typed values and an optional totals
row. The writers (infra/writers.py) turn it into CSV, XLSX or PDF. Values are already words
(labels, names): no code ever reaches a file (rule d).

Formula injection (D-100, added): a spreadsheet runs a cell that starts with `=`, `+`, `-`, `@`,
a tab or a carriage return as a formula, so record text such as a subject "=HYPERLINK(...)"
could act when a colleague opens the file. Every text value is neutralised by `safe_text` before
any writer sees it; numbers and dates are written as numbers and dates, never as text.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


class CellKind(StrEnum):
    """How a column's values are written."""

    TEXT = "text"
    NUMBER = "number"
    PERCENT = "percent"  # 0-100 in the data; written as a fraction with a percent format
    HOURS = "hours"  # durations, written as hours with two decimals
    DATETIME = "datetime"  # wall-clock time in the export's time zone


Value = str | int | float | datetime | None


def safe_text(value: str) -> str:
    """The text with a leading apostrophe if a spreadsheet would read it as a formula."""
    return f"'{value}" if value.startswith(FORMULA_STARTS) else value


@dataclass(frozen=True)
class Column:
    """One column: its translated header and how its values are written."""

    header: str
    kind: CellKind = CellKind.TEXT


@dataclass
class Sheet:
    """One table of an export."""

    name: str
    columns: list[Column]
    rows: list[list[Value]] = field(default_factory=list)
    totals: list[Value] | None = None
    # Lines above the table: title, run by, run at, time zone, filters in words (REQ-RPT-050).
    header_lines: list[str] = field(default_factory=list)

    def add(self, row: list[Value]) -> None:
        """Add a row; text cells are neutralised here, once, for every format."""
        self.rows.append([safe_text(v) if isinstance(v, str) else v for v in row])


@dataclass
class ExportDocument:
    """Everything one export file contains."""

    title: str
    language: str
    rtl: bool
    sheets: list[Sheet]
    # The chart of the first sheet as SVG (PDF only), drawn by the server-side chart renderer.
    chart_svg: str | None = None

    def __post_init__(self) -> None:
        """Header lines are text too: neutralise them like cells."""
        self.title = safe_text(self.title)
        for sheet in self.sheets:
            sheet.name = safe_text(sheet.name)
            sheet.header_lines = [safe_text(line) for line in sheet.header_lines]
            sheet.columns = [Column(safe_text(c.header), c.kind) for c in sheet.columns]
            if sheet.totals is not None:
                sheet.totals = [safe_text(v) if isinstance(v, str) else v for v in sheet.totals]


@dataclass(frozen=True)
class PdfInput:
    """Everything a PDF shows, already in words."""

    title: str
    language: str
    rtl: bool
    header_lines: list[str]
    columns: list[Column]
    rows: list[list[Value]]
    totals: list[Value] | None
    chart: "ChartData | None"
    records_columns: list[Column]
    records: list[list[Value]]
    records_cut: bool


@dataclass(frozen=True)
class ChartData:
    """A chart of the summary: categories and the first measure, in words."""

    kind: str
    categories: list[str]
    values: list[float | None]
    series_name: str
