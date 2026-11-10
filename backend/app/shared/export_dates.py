"""How every export writes a date and time (D-155, the product owner 2026-11-10).

- CSV: ISO 8601, `2026-11-10 11:35`, the wall-clock time of the export's zone, whatever format
  the person reads on screen;
- Excel: a real date cell (a typed datetime with a display format), never text, so a
  spreadsheet sorts and filters it;
- the zone is named in each date column's header, e.g. "Created (Asia/Karachi)".

Spreadsheets hold no zones, so values are turned into the export zone's wall-clock time here.
Every exporter writes its dates through these functions, so the rule lives in one place.
"""

from datetime import UTC, datetime, tzinfo

CSV_DATETIME = "%Y-%m-%d %H:%M"
EXCEL_DATETIME_FORMAT = "yyyy-mm-dd hh:mm"


def wall_clock(value: datetime, zone: tzinfo) -> datetime:
    """`value` as the export zone's clock shows it, without a zone (what a sheet can hold).

    A value without a zone is taken to be UTC, as the database stores every timestamp.
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(zone).replace(tzinfo=None)


def csv_datetime(value: datetime, zone: tzinfo | None = None) -> str:
    """ISO 8601 date and time for a CSV cell; with `zone`, in that zone's wall-clock time."""
    shown = wall_clock(value, zone) if zone is not None else value
    return shown.strftime(CSV_DATETIME)


def zoned_header(header: str, zone: str) -> str:
    """A date column's header naming its zone: "Created (Asia/Karachi)"."""
    return f"{header} ({zone})"
