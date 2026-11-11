"""D-155: one way for every export to write dates."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.shared.export_dates import csv_datetime, wall_clock, zoned_header

KARACHI = ZoneInfo("Asia/Karachi")


def test_csv_is_iso_8601_in_the_export_zone_whatever_the_screen_format() -> None:
    at = datetime(2026, 11, 10, 6, 35, tzinfo=UTC)
    assert csv_datetime(at, KARACHI) == "2026-11-10 11:35"
    assert csv_datetime(datetime(2026, 11, 10, 11, 35)) == "2026-11-10 11:35"  # noqa: DTZ001 - already wall clock


def test_a_sheet_gets_the_zones_wall_clock_and_no_zone() -> None:
    shown = wall_clock(datetime(2026, 11, 10, 23, 30, tzinfo=UTC), KARACHI)
    assert shown == datetime(2026, 11, 11, 4, 30)  # noqa: DTZ001 - what a spreadsheet holds
    assert shown.tzinfo is None
    # A timestamp without a zone is the database's UTC.
    assert wall_clock(datetime(2026, 11, 10, 6, 35), KARACHI).hour == 11  # noqa: DTZ001 - UTC as stored


def test_the_zone_is_named_in_the_date_columns_header() -> None:
    assert zoned_header("Created", "Asia/Karachi") == "Created (Asia/Karachi)"
