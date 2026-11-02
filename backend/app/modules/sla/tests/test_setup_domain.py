"""Calendar set-up rules and the iCalendar import, without I/O (WP-025 session 1)."""

import random
import time
from datetime import UTC, date, datetime

import pytest

from app.modules.sla.domain.calendar import HolidayPart
from app.modules.sla.domain.ical import (
    MAX_BYTES,
    MAX_EVENTS,
    MAX_LINES,
    IcalRefused,
    IcalSkip,
    parse_holidays,
)
from app.modules.sla.domain.setup import (
    HolidayDates,
    WeekPreset,
    build_calendar,
    holiday_map,
    holiday_problems,
    next_year,
    normal_week,
    preset_week,
    week_problems,
)


def _period(weekday: int, start: str, end: str) -> dict[str, object]:
    return {"weekday": weekday, "start": start, "end": end}


# --- weeks -------------------------------------------------------------------------------------


@pytest.mark.parametrize("preset", list(WeekPreset))
def test_every_preset_is_a_valid_week(preset: WeekPreset) -> None:
    assert week_problems(preset_week(preset)) == []


def test_the_sunday_to_thursday_preset_works_sunday_not_friday() -> None:
    days = {p["weekday"] for p in preset_week(WeekPreset.SUN_THU)}
    assert days == {6, 0, 1, 2, 3}


@pytest.mark.parametrize(
    ("week", "code"),
    [
        ([], "week_empty"),
        ([_period(0, "09:00", "18:00")] * 29, "week_too_many_periods"),
        ([_period(0, "9:00", "18:00")], "period_time_invalid"),
        ([_period(0, "09:60", "18:00")], "period_time_invalid"),
        ([_period(0, "24:00", "06:00")], "period_time_invalid"),
        ([_period(7, "09:00", "18:00")], "period_weekday_invalid"),
        ([{"weekday": 0, "start": "09:00"}], "period_time_invalid"),
        ([_period(0, "09:00", "13:00"), _period(0, "12:00", "18:00")], "periods_overlap"),
        # Monday night runs to 06:00 Tuesday, over Tuesday's early period.
        ([_period(0, "22:00", "06:00"), _period(1, "05:00", "09:00")], "periods_overlap"),
        # Sunday night runs into Monday morning, across the end of the week.
        ([_period(6, "22:00", "06:00"), _period(0, "05:00", "09:00")], "periods_overlap"),
    ],
)
def test_bad_weeks_are_refused_with_a_code(week: list[dict[str, object]], code: str) -> None:
    assert week_problems(week) == [code]


def test_split_shifts_and_a_period_ending_at_midnight_are_fine() -> None:
    week = [
        _period(0, "08:00", "12:00"),
        _period(0, "13:00", "17:00"),
        _period(1, "16:00", "24:00"),
        _period(2, "22:00", "06:00"),
        _period(3, "06:00", "10:00"),  # starts exactly when Wednesday's night ends
    ]
    assert week_problems(week) == []


def test_a_stored_week_is_sorted_and_written_as_hh_mm() -> None:
    week = [_period(2, "13:00", "17:00"), _period(0, "09:00", "24:00")]
    assert normal_week(week) == [_period(0, "09:00", "24:00"), _period(2, "13:00", "17:00")]


# --- holidays ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("starts", "ends", "part", "codes"),
    [
        (date(2026, 12, 25), date(2026, 12, 25), HolidayPart.FULL, []),
        (date(2026, 12, 24), date(2026, 12, 24), HolidayPart.AFTERNOON, []),
        (date(2026, 12, 25), date(2026, 12, 28), HolidayPart.FULL, []),
        (date(2026, 12, 28), date(2026, 12, 25), HolidayPart.FULL, ["holiday_range_order"]),
        (date(2026, 1, 1), date(2027, 1, 2), HolidayPart.FULL, ["holiday_range_too_long"]),
        (date(2026, 12, 24), date(2026, 12, 25), HolidayPart.MORNING, ["half_day_single_date"]),
    ],
)
def test_holiday_rules(starts: date, ends: date, part: HolidayPart, codes: list[str]) -> None:
    assert holiday_problems(starts, ends, part) == codes


def test_a_range_covers_every_day_and_a_full_day_beats_a_half_day() -> None:
    days = holiday_map(
        [
            HolidayDates(date(2026, 12, 24), date(2026, 12, 24), HolidayPart.AFTERNOON),
            HolidayDates(date(2026, 12, 24), date(2026, 12, 26)),
        ]
    )
    assert days == {
        date(2026, 12, 24): HolidayPart.FULL,
        date(2026, 12, 25): HolidayPart.FULL,
        date(2026, 12, 26): HolidayPart.FULL,
    }


def test_a_morning_off_and_an_afternoon_off_on_two_lists_make_the_whole_day_off() -> None:
    day = date(2026, 11, 4)
    days = holiday_map(
        [
            HolidayDates(day, day, HolidayPart.MORNING),
            HolidayDates(day, day, HolidayPart.AFTERNOON),
        ]
    )
    assert days == {day: HolidayPart.FULL}


def test_the_same_half_day_twice_stays_a_half_day() -> None:
    day = date(2026, 11, 4)
    twice = [HolidayDates(day, day, HolidayPart.MORNING)] * 2
    assert holiday_map(twice) == {day: HolidayPart.MORNING}


def test_copy_to_next_year_keeps_the_day_and_moves_a_leap_day_to_the_28th() -> None:
    assert next_year(date(2026, 12, 25)) == date(2027, 12, 25)
    assert next_year(date(2028, 2, 29)) == date(2029, 2, 28)


def test_a_built_calendar_uses_its_holidays() -> None:
    calendar = build_calendar(
        kind="hours",
        time_zone="Asia/Karachi",
        week=preset_week(WeekPreset.MON_FRI),
        holidays=[HolidayDates(date(2026, 11, 3), date(2026, 11, 3))],
    )
    monday_five_pm = datetime(2026, 11, 2, 12, tzinfo=UTC)  # 17:00 in Karachi
    assert calendar.add(monday_five_pm, 2 * 3600) == datetime(2026, 11, 4, 5, tzinfo=UTC)


def test_an_unknown_zone_falls_back_to_utc_rather_than_failing() -> None:
    calendar = build_calendar(kind="hours", time_zone="Mars/Olympus", week=[], holidays=[])
    assert calendar.zone.key == "UTC"


def test_around_the_clock_ignores_week_and_holidays() -> None:
    calendar = build_calendar(
        kind="around_the_clock",
        time_zone="Asia/Karachi",
        week=[],
        holidays=[HolidayDates(date(2026, 11, 3), date(2026, 11, 3))],
    )
    start = datetime(2026, 11, 3, tzinfo=UTC)
    assert calendar.between(start, datetime(2026, 11, 4, tzinfo=UTC)) == 86400


# --- iCalendar import --------------------------------------------------------------------------


def _ical(*events: str) -> bytes:
    body = "".join(f"BEGIN:VEVENT\r\nUID:{i}\r\n{e}END:VEVENT\r\n" for i, e in enumerate(events))
    return (
        f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//EN\r\n{body}END:VCALENDAR\r\n".encode()
    )


def _event(name: str, start: str, end: str | None = None) -> str:
    out = f"SUMMARY:{name}\r\nDTSTART;VALUE=DATE:{start}\r\n"
    return out + (f"DTEND;VALUE=DATE:{end}\r\n" if end else "")


def test_twelve_holidays_make_twelve_entries() -> None:
    """REQ-SLA-012 AC2."""
    events = [_event(f"Holiday {m}", f"2027{m:02d}01", f"2027{m:02d}02") for m in range(1, 13)]
    result = parse_holidays(_ical(*events))
    assert len(result.holidays) == 12
    assert result.skipped == []
    assert result.holidays[0].starts_on == result.holidays[0].ends_on == date(2027, 1, 1)


def test_all_day_ends_are_exclusive_and_a_missing_end_is_one_day() -> None:
    result = parse_holidays(
        _ical(_event("Eid", "20270310", "20270313"), _event("Labour Day", "20270501"))
    )
    eid, labour = result.holidays
    assert (eid.starts_on, eid.ends_on) == (date(2027, 3, 10), date(2027, 3, 12))
    assert labour.starts_on == labour.ends_on == date(2027, 5, 1)


def test_an_end_equal_to_the_start_is_one_day() -> None:
    (only,) = parse_holidays(_ical(_event("Day", "20270101", "20270101"))).holidays
    assert only.starts_on == only.ends_on


def test_skipped_events_are_reported_with_their_reason() -> None:
    result = parse_holidays(
        _ical(
            _event("Weekly", "20270101") + "RRULE:FREQ=WEEKLY\r\n",
            "SUMMARY:No date\r\n",
            _event("", "20270101"),
            _event("Backwards", "20270105", "20270101"),
            _event("Too long", "20270101", "20290101"),
            _event("Fine", "20270101"),
        )
    )
    assert [h.name for h in result.holidays] == ["Fine"]
    assert [(s.name, s.reason) for s in result.skipped] == [
        ("Weekly", IcalSkip.REPEATING),
        ("No date", IcalSkip.NO_DATE),
        (None, IcalSkip.NO_NAME),
        ("Backwards", IcalSkip.BAD_RANGE),
        ("Too long", IcalSkip.TOO_LONG),
    ]


def test_a_timed_event_counts_by_its_dates() -> None:
    timed = "SUMMARY:Timed\r\nDTSTART:20271225T090000Z\r\nDTEND:20271226T000000Z\r\n"
    (only,) = parse_holidays(_ical(timed)).holidays
    assert only.starts_on == only.ends_on == date(2027, 12, 25)


def test_names_are_one_line_and_cut_to_200() -> None:
    (only,) = parse_holidays(_ical(_event("A" * 300, "20270101"))).holidays
    assert only.name == "A" * 200


def test_more_than_the_event_limit_is_skipped_not_imported() -> None:
    events = [_event(f"H{i}", "20270101") for i in range(MAX_EVENTS + 3)]
    result = parse_holidays(_ical(*events))
    assert len(result.holidays) == MAX_EVENTS
    assert {s.reason for s in result.skipped} == {IcalSkip.TOO_MANY}


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"x" * (MAX_BYTES + 1), "ical_too_large"),
        (b"\n" * MAX_LINES, "ical_too_many_lines"),
        (b"\xff\xfe\x00", "ical_not_utf8"),
        (b"not a calendar", "ical_invalid"),
        (b"", "ical_invalid"),
    ],
)
def test_unusable_files_are_refused_with_a_code(data: bytes, code: str) -> None:
    with pytest.raises(IcalRefused) as refused:
        parse_holidays(data)
    assert refused.value.code == code


def test_fuzz_never_raises_anything_but_a_refusal() -> None:
    """Imported files are untrusted (D-115): corrupted input is refused or read, never a crash."""
    seed = _ical(_event("Eid", "20270310", "20270313"), _event("Labour Day", "20270501"))
    rng = random.Random(25)  # noqa: S311 - seeded fuzz input, not security
    for _ in range(2000):
        data = bytearray(seed)
        for _ in range(rng.randint(1, 12)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        try:
            result = parse_holidays(bytes(data))
        except IcalRefused:
            continue
        for holiday in result.holidays:
            assert holiday.ends_on >= holiday.starts_on


# --- iCalendar fuzz: structured hostile input (D-115: imported files are untrusted) ------------

_HOSTILE = [
    # truncated: the file stops mid-event, mid-line, mid-property
    _ical(_event("Eid", "20270310", "20270313"))[:60],
    _ical(_event("Eid", "20270310", "20270313"))[:-20],
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Open",
    # a huge folded line: one property continued over thousands of lines
    _ical(
        "SUMMARY:"
        + "x" * 70
        + "".join("\r\n " + "y" * 70 for _ in range(5000))
        + "\r\n"
        + "DTSTART;VALUE=DATE:20270101\r\n"
    ),
    # one enormous unfolded line
    _ical(f"SUMMARY:{'z' * 900_000}\r\nDTSTART;VALUE=DATE:20270101\r\n"),
    # bad dates
    _ical(_event("Feb 30", "20270230")),
    _ical(_event("Month 13", "20271301")),
    _ical(_event("Words", "tomorrow")),
    _ical("SUMMARY:Timed bad\r\nDTSTART:20270101T256100Z\r\n"),
    _ical("SUMMARY:Year 0\r\nDTSTART;VALUE=DATE:00000101\r\n"),
    _ical("SUMMARY:Far\r\nDTSTART;VALUE=DATE:99991231\r\nDTEND;VALUE=DATE:99991231\r\n"),
    _ical("SUMMARY:Bad zone\r\nDTSTART;TZID=Mars/Olympus:20270101T090000\r\n"),
    # recurrence rules, valid and not
    _ical(_event("Daily", "20270101") + "RRULE:FREQ=DAILY;COUNT=100000\r\n"),
    _ical(_event("Broken rule", "20270101") + "RRULE:FREQ=;;;INTERVAL=-1\r\n"),
    _ical(_event("Rdate", "20270101") + "RDATE;VALUE=DATE:20270102,20270103\r\n"),
    # wrong encodings
    _ical(_event("Eid", "20270310")).decode().encode("utf-16"),
    "BEGIN:VCALENDAR\r\nSUMMARY:Café\r\nEND:VCALENDAR\r\n".encode("latin-1"),
    b"\xef\xbb\xbf" + _ical(_event("BOM", "20270101")),
    b"\x00" * 1000,
    # nesting and structure abuse
    b"BEGIN:VCALENDAR\r\n" * 2000 + b"END:VCALENDAR\r\n" * 2000,
    _ical(
        "BEGIN:VALARM\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nSUMMARY:Alarm\r\nDTSTART;VALUE=DATE:20270101\r\n"
    ),
    b"BEGIN:VEVENT\r\nSUMMARY:No calendar\r\nDTSTART;VALUE=DATE:20270101\r\nEND:VEVENT\r\n",
    b"END:VCALENDAR\r\nBEGIN:VCALENDAR\r\n",
]


@pytest.mark.parametrize("data", _HOSTILE, ids=[f"hostile-{i}" for i in range(len(_HOSTILE))])
def test_hostile_files_end_in_a_code_or_a_valid_result_quickly(data: bytes) -> None:
    started = time.monotonic()
    try:
        result = parse_holidays(data)
    except IcalRefused as refused:
        assert refused.code.startswith("ical_")  # noqa: PT017 - either outcome is allowed here
    else:
        for holiday in result.holidays:
            assert 1 <= len(holiday.name) <= 200
            assert holiday.starts_on <= holiday.ends_on
            assert (holiday.ends_on - holiday.starts_on).days < 366
        assert all(isinstance(s.reason, IcalSkip) for s in result.skipped)
    assert time.monotonic() - started < 5, "an import must never hang"


def test_fuzz_line_level_mutations_never_crash() -> None:
    """Lines dropped, duplicated, swapped and cut, over many seeded rounds."""
    lines = _ical(
        _event("Eid", "20270310", "20270313"),
        _event("Labour Day", "20270501"),
        "SUMMARY:Timed\r\nDTSTART:20271225T090000Z\r\nDTEND:20271226T000000Z\r\n",
    ).split(b"\r\n")
    rng = random.Random(1025)  # noqa: S311 - seeded fuzz input, not security
    for _ in range(1500):
        mutated = list(lines)
        for _ in range(rng.randint(1, 6)):
            i = rng.randrange(len(mutated))
            choice = rng.randrange(4)
            if choice == 0:
                del mutated[i]
            elif choice == 1:
                mutated.insert(i, mutated[i])
            elif choice == 2:
                j = rng.randrange(len(mutated))
                mutated[i], mutated[j] = mutated[j], mutated[i]
            else:
                mutated[i] = mutated[i][: rng.randrange(len(mutated[i]) + 1)]
            if not mutated:
                break
        try:
            result = parse_holidays(b"\r\n".join(mutated))
        except IcalRefused:
            continue
        for holiday in result.holidays:
            assert holiday.starts_on <= holiday.ends_on


# --- special date-range hours ------------------------------------------------------------------


def test_special_hours_ranges_never_overlap_and_are_checked() -> None:
    from app.modules.sla.domain.calendar import Period, SpecialHours, special_hours_problems  # noqa: PLC0415

    ramadan = SpecialHours(date(2027, 2, 8), date(2027, 3, 9), (Period(0, 540, 840),))
    eid_week = SpecialHours(date(2027, 3, 9), date(2027, 3, 12), ())
    later = SpecialHours(date(2027, 3, 10), date(2027, 3, 12), ())
    assert special_hours_problems([ramadan, later]) == []
    assert special_hours_problems([ramadan, eid_week]) == ["exception_ranges_overlap"]
    backwards = SpecialHours(date(2027, 3, 9), date(2027, 2, 8), ())
    assert special_hours_problems([backwards]) == ["exception_range_order"]
    too_long = SpecialHours(date(2027, 1, 1), date(2028, 1, 2), ())
    assert special_hours_problems([too_long]) == ["exception_range_too_long"]
    clash = SpecialHours(
        date(2027, 2, 8), date(2027, 2, 9), (Period(0, 540, 840), Period(0, 600, 660))
    )
    assert special_hours_problems([clash]) == ["periods_overlap"]


def test_a_built_calendar_uses_its_special_hours() -> None:
    from app.modules.sla.domain.setup import SpecialRange  # noqa: PLC0415

    calendar = build_calendar(
        kind="hours",
        time_zone="UTC",
        week=preset_week(WeekPreset.MON_FRI),
        holidays=[],
        special=[
            SpecialRange(
                date(2027, 2, 8),
                date(2027, 2, 12),
                [{"weekday": d, "start": "09:00", "end": "14:00"} for d in range(5)],
            )
        ],
    )
    monday = datetime(2027, 2, 8, 0, tzinfo=UTC)
    assert calendar.between(monday, datetime(2027, 2, 9, tzinfo=UTC)) == 5 * 3600
