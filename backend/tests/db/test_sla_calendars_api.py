"""SLA set-up over HTTP, WP-025 session 1: calendars, holiday lists, holidays (parity file 03).

The incident world of test_incidents_api.py: org A has an admin (every permission), technicians
and requesters, sites S1/S2 and groups GA/GB; org B is there for isolation. Test names cite the
requirement they prove (REQ-SLA-*, REQ-ADM-040).
"""

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules import sla
from tests.db import test_incidents_api
from tests.db.test_incidents_api import CONSOLE, Org, World, field_codes, problem

pytestmark = [pytest.mark.db, pytest.mark.valkey]
world = test_incidents_api.world  # the incident world fixture, reused

CALENDARS = "/sla/calendars"
LISTS = "/sla/holiday-lists"
TABLES = (
    "sla_calendars",
    "sla_holiday_lists",
    "sla_holidays",
    "sla_calendar_holidays",
    "sla_calendar_exceptions",
)
SUN_THU = [{"weekday": d, "start": "08:00", "end": "17:00"} for d in (6, 0, 1, 2, 3)]


def _new() -> dict[str, str]:
    return {**CONSOLE, "Idempotency-Key": str(uuid.uuid4())}


def _match(version: int) -> dict[str, str]:
    return {**CONSOLE, "If-Match": f'"{version}"'}


async def _calendar(
    world: World,
    org: Org,
    name: str = "Riyadh office",
    **extra: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    body = {"name": name, "time_zone": "Asia/Riyadh", "week": SUN_THU, **extra}
    response = await world.call("POST", CALENDARS, org, org.admin, json=body, headers=_new())
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _list(world: World, org: Org, name: str = "Pakistan") -> dict[str, Any]:
    response = await world.call("POST", LISTS, org, org.admin, json={"name": name}, headers=_new())
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _holiday(world: World, org: Org, holiday_list: dict[str, Any], **body: Any) -> Any:  # noqa: ANN401 - JSON / response
    return await world.call(
        "POST", f"{LISTS}/{holiday_list['id']}/holidays", org, org.admin, json=body, headers=_new()
    )


def _ics(*events: tuple[str, str]) -> bytes:
    body = "".join(
        f"BEGIN:VEVENT\r\nUID:{i}\r\nSUMMARY:{name}\r\nDTSTART;VALUE=DATE:{day}\r\nEND:VEVENT\r\n"
        for i, (name, day) in enumerate(events)
    )
    return (
        f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//EN\r\n{body}END:VCALENDAR\r\n".encode()
    )


# --- calendars (REQ-SLA-010) ---------------------------------------------------------------------


async def test_req_sla_010_every_tenant_has_around_the_clock_and_default_hours(
    world: World,
) -> None:
    a = world.a
    sites = (await world.call("GET", "/organization/sites", a, a.admin)).json()
    default = next(s for s in sites if s["is_default"])
    changed = await world.call(
        "PATCH",
        f"/organization/sites/{default['id']}",
        a,
        a.admin,
        json={"time_zone": "Asia/Karachi"},
        headers=_match(default["version"]),
    )
    assert changed.status_code == 200, changed.text
    listed = (await world.call("GET", CALENDARS, a, a.tech_a)).json()
    assert [c["system_key"] for c in listed] == ["around_the_clock", "operating_hours"]
    around, hours = listed
    assert around["kind"] == "around_the_clock"
    assert around["fixed"] is True
    assert around["delete_refusal"] == "system_calendar"
    # D-115 D2: Monday to Friday 09:00-18:00 in the default site's time zone.
    assert hours["time_zone"] == "Asia/Karachi"
    assert hours["week"] == [{"weekday": d, "start": "09:00", "end": "18:00"} for d in range(5)]
    # Listing again creates nothing new.
    again = (await world.call("GET", CALENDARS, a, a.admin)).json()
    assert [c["id"] for c in again] == [c["id"] for c in listed]


async def test_req_sla_010_any_week_split_shifts_and_presets(world: World) -> None:
    a = world.a
    riyadh = await _calendar(world, a)
    assert riyadh["week"] == sorted(SUN_THU, key=lambda p: p["weekday"])
    split = await _calendar(
        world,
        a,
        "Split shift",
        time_zone="Europe/London",
        week=[
            {"weekday": 0, "start": "13:00", "end": "17:00"},
            {"weekday": 0, "start": "08:00", "end": "12:00"},
            {"weekday": 4, "start": "22:00", "end": "06:00"},
        ],
    )
    assert [p["start"] for p in split["week"]] == ["08:00", "13:00", "22:00"]
    preset = await world.call(
        "POST",
        CALENDARS,
        a,
        a.admin,
        json={"name": "Saturdays too", "time_zone": "Asia/Karachi", "preset": "mon_sat"},
        headers=_new(),
    )
    assert preset.status_code == 201, preset.text
    assert {p["weekday"] for p in preset.json()["week"]} == {0, 1, 2, 3, 4, 5}


@pytest.mark.parametrize(
    ("body", "codes"),
    [
        ({"time_zone": "Mars/Olympus"}, {"time_zone": "unknown_time_zone"}),
        ({"week": []}, {"week": "week_empty"}),
        (
            {
                "week": [
                    {"weekday": 0, "start": "09:00", "end": "13:00"},
                    {"weekday": 0, "start": "12:00", "end": "18:00"},
                ]
            },
            {"week": "periods_overlap"},
        ),
        ({"labels": {"fr": "Bureau"}}, {"labels": "invalid_language"}),
        ({"holiday_list_ids": [str(uuid.uuid4())]}, {"holiday_list_ids": "holiday_list_not_found"}),
    ],
)
async def test_req_sla_010_bad_calendars_are_refused_with_codes(
    world: World, body: dict[str, Any], codes: dict[str, str]
) -> None:
    a = world.a
    full = {"name": "Bad", "time_zone": "Asia/Riyadh", "week": SUN_THU, **body}
    refused = await world.call("POST", CALENDARS, a, a.admin, json=full, headers=_new())
    assert field_codes(refused) == codes


async def test_names_are_unique_ignoring_case(world: World) -> None:
    a = world.a
    await _calendar(world, a, "Riyadh office")
    again = await world.call(
        "POST",
        CALENDARS,
        a,
        a.admin,
        json={"name": "RIYADH OFFICE", "time_zone": "Asia/Riyadh"},
        headers=_new(),
    )
    assert field_codes(again) == {"name": "name_taken"}
    # Another tenant may use the same name.
    await _calendar(world, world.b, "Riyadh office")


async def test_technicians_read_admins_change_requesters_neither(world: World) -> None:
    a = world.a
    calendar = await _calendar(world, a)
    assert (
        await world.call("GET", f"{CALENDARS}/{calendar['id']}", a, a.tech_a)
    ).status_code == 200
    viewed = (await world.call("GET", f"{CALENDARS}/{calendar['id']}", a, a.tech_a)).json()
    assert viewed["can_manage"] is False
    change = await world.call(
        "PATCH",
        f"{CALENDARS}/{calendar['id']}",
        a,
        a.tech_a,
        json={"name": "Mine"},
        headers=_match(calendar["version"]),
    )
    assert problem(change) == (403, "permission_denied")
    assert problem(await world.call("GET", CALENDARS, a, a.requester))[0] == 403


async def test_edits_need_if_match_and_a_stale_one_names_who_changed_what(world: World) -> None:
    a = world.a
    calendar = await _calendar(world, a)
    path = f"{CALENDARS}/{calendar['id']}"
    missing = await world.call("PATCH", path, a, a.admin, json={"name": "X"}, headers=CONSOLE)
    assert missing.status_code == 428
    first = await world.call(
        "PATCH",
        path,
        a,
        a.admin,
        json={"time_zone": "Asia/Karachi"},
        headers=_match(calendar["version"]),
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == calendar["version"] + 1
    stale = await world.call(
        "PATCH", path, a, a.admin, json={"name": "Late"}, headers=_match(calendar["version"])
    )
    assert problem(stale) == (409, "version_conflict")
    params = stale.json()["params"]
    assert params["changed_fields"] == "time_zone"
    assert params["changed_by"] == "Alpha Admin"
    # A save that changes nothing is no new version.
    same = await world.call(
        "PATCH",
        path,
        a,
        a.admin,
        json={"time_zone": "Asia/Karachi"},
        headers=_match(first.json()["version"]),
    )
    assert same.json()["version"] == first.json()["version"]
    history = await world.sql(
        "SELECT field, old_value, new_value, source FROM field_changes"
        " WHERE record_type = 'sla_calendar' AND record_id = $1 AND field = 'time_zone'",
        uuid.UUID(calendar["id"]),
    )
    assert [(h["field"], h["source"]) for h in history][-1] == ("time_zone", "ui")


async def test_around_the_clock_keeps_its_shape_and_system_calendars_cannot_go(
    world: World,
) -> None:
    a = world.a
    around, hours = (await world.call("GET", CALENDARS, a, a.admin)).json()
    path = f"{CALENDARS}/{around['id']}"
    reshape = await world.call(
        "PATCH", path, a, a.admin, json={"week": SUN_THU}, headers=_match(around["version"])
    )
    assert field_codes(reshape) == {"week": "system_calendar_fixed"}
    renamed = await world.call(
        "PATCH",
        path,
        a,
        a.admin,
        json={"name": "24/7", "labels": {"ar": "على مدار الساعة"}},
        headers=_match(around["version"]),
    )
    assert renamed.status_code == 200, renamed.text
    for calendar in (renamed.json(), hours):
        gone = await world.call(
            "DELETE",
            f"{CALENDARS}/{calendar['id']}",
            a,
            a.admin,
            headers=_match(calendar["version"]),
        )
        assert problem(gone) == (409, "system_calendar_required")


# --- sites and groups (REQ-SLA-013, REQ-ADM-040) ------------------------------------------------


async def test_req_adm_040_sites_and_groups_name_a_calendar_and_its_page_lists_them(
    world: World,
) -> None:
    a = world.a
    calendar = await _calendar(world, a)
    site = next(
        s
        for s in (await world.call("GET", "/organization/sites", a, a.admin)).json()
        if s["id"] == str(a.s1)
    )
    linked = await world.call(
        "PATCH",
        f"/organization/sites/{a.s1}",
        a,
        a.admin,
        json={"calendar_id": calendar["id"]},
        headers=_match(site["version"]),
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["calendar_id"] == calendar["id"]
    group = next(
        g
        for g in (await world.call("GET", "/organization/groups", a, a.admin)).json()
        if g["id"] == str(a.ga)
    )
    grouped = await world.call(
        "PATCH",
        f"/organization/groups/{a.ga}",
        a,
        a.admin,
        json={"calendar_id": calendar["id"]},
        headers=_match(group["version"]),
    )
    assert grouped.status_code == 200, grouped.text
    page = (await world.call("GET", f"{CALENDARS}/{calendar['id']}", a, a.admin)).json()
    assert [s["name"] for s in page["used_by_sites"]] == ["Alpha S1"]
    assert [g["name"] for g in page["used_by_groups"]] == ["Alpha GA"]
    assert page["delete_refusal"] == "calendar_in_use"
    # AC2: deleting a calendar in use is refused, naming its users.
    refused = await world.call(
        "DELETE", f"{CALENDARS}/{calendar['id']}", a, a.admin, headers=_match(page["version"])
    )
    assert problem(refused) == (409, "calendar_in_use")
    assert refused.json()["params"]["sites"] == "Alpha S1"
    assert refused.json()["params"]["groups"] == "Alpha GA"
    # Unlinked, it can go.
    unlinked = await world.call(
        "PATCH",
        f"/organization/sites/{a.s1}",
        a,
        a.admin,
        json={"calendar_id": None},
        headers=_match(linked.json()["version"]),
    )
    assert unlinked.status_code == 200, unlinked.text
    regroup = await world.call(
        "PATCH",
        f"/organization/groups/{a.ga}",
        a,
        a.admin,
        json={"calendar_id": None},
        headers=_match(grouped.json()["version"]),
    )
    assert regroup.status_code == 200, regroup.text
    gone = await world.call(
        "DELETE", f"{CALENDARS}/{calendar['id']}", a, a.admin, headers=_match(page["version"])
    )
    assert gone.status_code == 204, gone.text
    assert problem(await world.call("GET", f"{CALENDARS}/{calendar['id']}", a, a.admin)) == (
        404,
        "calendar_not_found",
    )


async def test_a_site_cannot_name_another_tenants_or_a_deleted_calendar(world: World) -> None:
    a, b = world.a, world.b
    theirs = await _calendar(world, b)
    gone = await _calendar(world, a, "Old hours")
    deleted = await world.call(
        "DELETE", f"{CALENDARS}/{gone['id']}", a, a.admin, headers=_match(gone["version"])
    )
    assert deleted.status_code == 204
    site = next(
        s
        for s in (await world.call("GET", "/organization/sites", a, a.admin)).json()
        if s["id"] == str(a.s1)
    )
    for calendar_id in (theirs["id"], gone["id"], str(uuid.uuid4())):
        refused = await world.call(
            "PATCH",
            f"/organization/sites/{a.s1}",
            a,
            a.admin,
            json={"calendar_id": calendar_id},
            headers=_match(site["version"]),
        )
        assert field_codes(refused) == {"calendar_id": "calendar_not_found"}


# --- holidays (REQ-SLA-012) ----------------------------------------------------------------------


async def test_req_sla_012_holidays_dates_ranges_and_half_days(world: World) -> None:
    a = world.a
    holidays = await _list(world, a)
    day = await _holiday(world, a, holidays, name="Pakistan Day", starts_on="2026-03-23")
    assert day.status_code == 201, day.text
    assert day.json()["ends_on"] == "2026-03-23"
    assert day.json()["part"] == "full"
    eid = await _holiday(
        world, a, holidays, name="Eid ul-Fitr", starts_on="2026-03-20", ends_on="2026-03-22"
    )
    assert eid.status_code == 201, eid.text
    half = await _holiday(
        world, a, holidays, name="Christmas Eve", starts_on="2026-12-24", part="afternoon"
    )
    assert half.status_code == 201, half.text
    long_half = await _holiday(
        world, a, holidays, name="Bad", starts_on="2026-12-24", ends_on="2026-12-25", part="morning"
    )
    assert field_codes(long_half) == {"part": "half_day_single_date"}
    backwards = await _holiday(
        world, a, holidays, name="Bad", starts_on="2026-12-25", ends_on="2026-12-24"
    )
    assert field_codes(backwards) == {"ends_on": "holiday_range_order"}
    listed = await world.call("GET", f"{LISTS}/{holidays['id']}/holidays?year=2026", a, a.tech_a)
    assert [h["name"] for h in listed.json()] == ["Eid ul-Fitr", "Pakistan Day", "Christmas Eve"]
    summary = (await world.call("GET", f"{LISTS}/{holidays['id']}", a, a.admin)).json()
    assert summary["holiday_count"] == 3


async def test_req_sla_012_ac1_a_holiday_removes_the_day_from_every_calendar_it_is_on(
    world: World,
) -> None:
    a = world.a
    holidays = await _list(world, a)
    added = await _holiday(world, a, holidays, name="Day off", starts_on="2026-11-03")  # a Tuesday
    assert added.status_code == 201
    first = await _calendar(
        world, a, "Karachi", time_zone="Asia/Karachi", preset="mon_fri", week=None
    )
    second = await _calendar(
        world, a, "Lahore", time_zone="Asia/Karachi", preset="mon_fri", week=None
    )
    for calendar in (first, second):
        attached = await world.call(
            "PATCH",
            f"{CALENDARS}/{calendar['id']}",
            a,
            a.admin,
            json={"holiday_list_ids": [holidays["id"]]},
            headers=_match(calendar["version"]),
        )
        assert attached.status_code == 200, attached.text
        assert attached.json()["holiday_list_ids"] == [holidays["id"]]
    monday_five_pm = datetime(2026, 11, 2, 12, tzinfo=UTC)  # 17:00 in Karachi
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        for calendar in (first, second):
            maths = await sla.calendar_for_maths(session, uuid.UUID(calendar["id"]))
            # One hour on Monday, Tuesday is off, one hour on Wednesday.
            due = maths.add(monday_five_pm, 2 * 3600)
            assert due == datetime(2026, 11, 4, 5, tzinfo=UTC)
    listed = (await world.call("GET", LISTS, a, a.admin)).json()
    assert sorted(listed[0]["calendar_ids"]) == sorted([first["id"], second["id"]])


async def test_req_sla_012_ac2_import_twelve_and_report_skips_and_duplicates(world: World) -> None:
    a = world.a
    holidays = await _list(world, a)
    months = [(f"Holiday {m}", f"2027{m:02d}01") for m in range(1, 13)]
    weekly = _ics(*months).replace(
        b"END:VCALENDAR",
        b"BEGIN:VEVENT\r\nUID:w\r\nSUMMARY:Weekly\r\nDTSTART;VALUE=DATE:20270101\r\n"
        b"RRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\nEND:VCALENDAR",
    )
    path = f"{LISTS}/{holidays['id']}/import"
    imported = await world.call(
        "POST",
        path,
        a,
        a.admin,
        content=weekly,
        headers={**_new(), "Content-Type": "text/calendar"},
    )
    assert imported.status_code == 201, imported.text
    assert len(imported.json()["created"]) == 12
    assert imported.json()["skipped"] == [{"name": "Weekly", "reason": "repeating"}]
    origins = {h["origin"] for h in imported.json()["created"]}
    assert origins == {"import"}
    again = await world.call(
        "POST",
        path,
        a,
        a.admin,
        content=_ics(*months[:2]),
        headers={**_new(), "Content-Type": "text/calendar"},
    )
    assert again.status_code == 201, again.text
    assert again.json()["created"] == []
    assert [s["reason"] for s in again.json()["skipped"]] == ["duplicate", "duplicate"]
    broken = await world.call(
        "POST",
        path,
        a,
        a.admin,
        content=b"not a calendar",
        headers={**_new(), "Content-Type": "text/calendar"},
    )
    assert field_codes(broken) == {"file": "ical_invalid"}
    technician = await world.call(
        "POST", path, a, a.tech_a, content=_ics(("X", "20270101")), headers=_new()
    )
    assert problem(technician) == (403, "permission_denied")


async def test_req_sla_012_ac3_copy_to_next_year_flags_each_for_review(world: World) -> None:
    a = world.a
    holidays = await _list(world, a)
    for name, day in (("Labour Day", "2026-05-01"), ("Eid", "2026-03-20")):
        assert (await _holiday(world, a, holidays, name=name, starts_on=day)).status_code == 201
    await _holiday(world, a, holidays, name="Next year already", starts_on="2027-01-01")
    copied = await world.call(
        "POST",
        f"{LISTS}/{holidays['id']}/copy-year",
        a,
        a.admin,
        json={"year": 2026},
        headers=_new(),
    )
    assert copied.status_code == 201, copied.text
    created = copied.json()["created"]
    assert [(h["name"], h["starts_on"], h["needs_review"]) for h in created] == [
        ("Eid", "2027-03-20", True),
        ("Labour Day", "2027-05-01", True),
    ]
    twice = await world.call(
        "POST",
        f"{LISTS}/{holidays['id']}/copy-year",
        a,
        a.admin,
        json={"year": 2026},
        headers=_new(),
    )
    assert [s["reason"] for s in twice.json()["skipped"]] == ["duplicate", "duplicate"]
    # Saving the corrected date clears the flag.
    eid = created[0]
    fixed = await world.call(
        "PATCH",
        f"{LISTS}/{holidays['id']}/holidays/{eid['id']}",
        a,
        a.admin,
        json={"starts_on": "2027-03-10"},
        headers=_match(eid["version"]),
    )
    assert fixed.status_code == 200, fixed.text
    assert (fixed.json()["starts_on"], fixed.json()["ends_on"]) == ("2027-03-10", "2027-03-10")
    assert fixed.json()["needs_review"] is False


async def test_deleting_a_list_detaches_it_from_its_calendars(world: World) -> None:
    a = world.a
    holidays = await _list(world, a)
    calendar = await _calendar(world, a, holiday_list_ids=[holidays["id"]])
    assert calendar["holiday_list_ids"] == [holidays["id"]]
    gone = await world.call(
        "DELETE", f"{LISTS}/{holidays['id']}", a, a.admin, headers=_match(holidays["version"])
    )
    assert gone.status_code == 204, gone.text
    after = (await world.call("GET", f"{CALENDARS}/{calendar['id']}", a, a.admin)).json()
    assert after["holiday_list_ids"] == []
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = 'sla.holiday_list.deleted'"
        " AND tenant_id = $1",
        a.tenant,
    )
    assert len(events) == 1


async def test_every_change_writes_its_event_to_the_outbox(world: World) -> None:
    a = world.a
    await _calendar(world, a)
    holidays = await _list(world, a)
    await _holiday(world, a, holidays, name="Day", starts_on="2026-11-03")
    rows = await world.sql(
        "SELECT event_type FROM outbox_events WHERE tenant_id = $1 AND event_type LIKE 'sla.%'"
        " ORDER BY id",
        a.tenant,
    )
    assert [r["event_type"] for r in rows] == [
        "sla.calendar.saved",
        "sla.holiday_list.saved",
        "sla.holiday_list.saved",
    ]


# --- RLS: every new table -------------------------------------------------------------------------


async def test_sla_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    holidays = await _list(world, a)
    await _holiday(world, a, holidays, name="Day", starts_on="2026-11-03")
    calendar = await _calendar(world, a, holiday_list_ids=[holidays["id"]])
    special = await world.call(
        "POST",
        f"{CALENDARS}/{calendar['id']}/special-hours",
        a,
        a.admin,
        json={"name": "Ramadan", "starts_on": "2027-02-08", "ends_on": "2027-03-09", "week": []},
        headers=_new(),
    )
    assert special.status_code == 201, special.text
    # B cannot add special hours to A's calendar.
    theirs = await world.call(
        "POST",
        f"{CALENDARS}/{calendar['id']}/special-hours",
        b,
        b.admin,
        json={"name": "X", "starts_on": "2027-01-01", "ends_on": "2027-01-02"},
        headers=_new(),
    )
    assert problem(theirs) == (404, "calendar_not_found")
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in TABLES:
            count = await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed names
                {"a": a.tenant},
            )
            assert count == 0, table
        for statement in (
            "UPDATE sla_calendars SET name = 'x'",
            "UPDATE sla_holiday_lists SET name = 'x'",
            "UPDATE sla_holidays SET name = 'x'",
            "UPDATE sla_calendar_exceptions SET name = 'x'",
            "DELETE FROM sla_calendar_holidays",
        ):
            assert (await session.execute(text(statement))).rowcount == 0, statement
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO sla_holiday_lists (id, tenant_id, name) VALUES (:id, :other, 'x')"
                ),
                {"id": uuid.uuid4(), "other": a.tenant},
            )
    assert problem(await world.call("GET", f"{CALENDARS}/{calendar['id']}", b, b.admin)) == (
        404,
        "calendar_not_found",
    )
    assert problem(await world.call("GET", f"{LISTS}/{holidays['id']}", b, b.admin)) == (
        404,
        "holiday_list_not_found",
    )
    # B cannot attach A's list to its own calendar.
    own = await _calendar(world, b)
    attach = await world.call(
        "PATCH",
        f"{CALENDARS}/{own['id']}",
        b,
        b.admin,
        json={"holiday_list_ids": [holidays["id"]]},
        headers=_match(own["version"]),
    )
    assert field_codes(attach) == {"holiday_list_ids": "holiday_list_not_found"}
    assert all(
        c["id"] != calendar["id"] for c in (await world.call("GET", CALENDARS, b, b.admin)).json()
    )


async def test_hostile_ical_uploads_answer_201_or_422_never_500(world: World) -> None:
    """D-115: imported files are untrusted. Every upload ends in a result or a problem code."""
    a = world.a
    holidays = await _list(world, a)
    path = f"{LISTS}/{holidays['id']}/import"
    good = _ics(("Eid", "20270310"), ("Labour Day", "20270501"))
    rng = random.Random(4044)  # noqa: S311 - seeded fuzz input, not security
    uploads = [
        good[:50],
        good.decode().encode("utf-16"),
        b"\x00" * 500,
        good.replace(b"20270310", b"20271340"),
        good.replace(b"END:VEVENT", b"RRULE:FREQ=DAILY\r\nEND:VEVENT"),
        b"x" * (1_000_001),
    ]
    for _ in range(40):
        mutated = bytearray(good)
        for _ in range(rng.randint(1, 10)):
            mutated[rng.randrange(len(mutated))] = rng.randrange(256)
        uploads.append(bytes(mutated))
    for data in uploads:
        answer = await world.call(
            "POST",
            path,
            a,
            a.admin,
            content=data,
            headers={**_new(), "Content-Type": "text/calendar"},
        )
        assert answer.status_code in {201, 422}, (answer.status_code, answer.text[:200])
        if answer.status_code == 422:
            body = answer.json()
            assert body["code"] in {"validation_failed", "ical_too_large"}
            assert "Traceback" not in answer.text


async def test_rls_sites_and_groups_cannot_point_at_another_tenants_calendar(world: World) -> None:
    """The calendar links on sites and support groups are same-tenant in the database too."""
    a, b = world.a, world.b
    theirs = await _calendar(world, a)
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table, row in (("sites", b.s1), ("support_groups", b.ga)):
            with pytest.raises(Exception, match="foreign key"):
                async with session.begin_nested():
                    await session.execute(
                        text(f"UPDATE {table} SET calendar_id = :c WHERE id = :id"),  # noqa: S608 - fixed names
                        {"c": uuid.UUID(theirs["id"]), "id": row},
                    )
        # B cannot even see which of A's sites or groups use a calendar.
        for table in ("sites", "support_groups"):
            seen = await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed names
                {"a": a.tenant},
            )
            assert seen == 0, table


# --- special date-range hours (product owner, 2026-11-02) ----------------------------------------

RAMADAN_WEEK = [
    *({"weekday": d, "start": "09:00", "end": "14:00"} for d in range(4)),
    {"weekday": 4, "start": "09:00", "end": "12:30"},
    {"weekday": 4, "start": "14:00", "end": "15:00"},  # after Friday prayer
]


async def _special(world: World, org: Org, calendar: dict[str, Any], **body: Any) -> Any:  # noqa: ANN401 - JSON / response
    return await world.call(
        "POST",
        f"{CALENDARS}/{calendar['id']}/special-hours",
        org,
        org.admin,
        json=body,
        headers=_new(),
    )


async def test_special_hours_replace_the_week_for_their_dates_and_holidays_still_win(
    world: World,
) -> None:
    a = world.a
    holidays = await _list(world, a)
    assert (
        await _holiday(world, a, holidays, name="Day off", starts_on="2027-03-01")
    ).status_code == 201
    calendar = await _calendar(
        world,
        a,
        "Karachi",
        time_zone="Asia/Karachi",
        preset="mon_fri",
        week=None,
        holiday_list_ids=[holidays["id"]],
    )
    added = await _special(
        world,
        a,
        calendar,
        name="Ramadan",
        starts_on="2027-02-08",
        ends_on="2027-03-09",
        week=RAMADAN_WEEK,
    )
    assert added.status_code == 201, added.text
    page = (await world.call("GET", f"{CALENDARS}/{calendar['id']}", a, a.tech_a)).json()
    assert [x["name"] for x in page["special_hours"]] == ["Ramadan"]
    assert len(page["special_hours"][0]["week"]) == 6
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        maths = await sla.calendar_for_maths(session, uuid.UUID(calendar["id"]))
    karachi = ZoneInfo("Asia/Karachi")
    friday = datetime(2027, 2, 12, tzinfo=karachi)
    assert maths.between(friday, friday + timedelta(days=1)) == int(4.5 * 3600)  # the break
    holiday = datetime(2027, 3, 1, tzinfo=karachi)
    assert maths.between(holiday, holiday + timedelta(days=1)) == 0  # holiday > range
    # An SLA that starts before the range (Friday 16:00) ends inside it (Monday 11:00).
    due = maths.add(datetime(2027, 2, 5, 16, tzinfo=karachi), 4 * 3600)
    assert due == datetime(2027, 2, 8, 11, tzinfo=karachi)


async def test_special_hours_ranges_of_one_calendar_never_overlap(world: World) -> None:
    a = world.a
    calendar = await _calendar(world, a)
    first = await _special(
        world, a, calendar, name="Ramadan", starts_on="2027-02-08", ends_on="2027-03-09", week=[]
    )
    assert first.status_code == 201, first.text
    clash = await _special(
        world, a, calendar, name="Eid week", starts_on="2027-03-09", ends_on="2027-03-12", week=[]
    )
    assert field_codes(clash) == {"starts_on": "exception_ranges_overlap"}
    backwards = await _special(
        world, a, calendar, name="Bad", starts_on="2027-04-09", ends_on="2027-04-01", week=[]
    )
    assert field_codes(backwards) == {"ends_on": "exception_range_order"}
    # The same dates on another calendar are fine.
    other = await _calendar(world, a, "Other office")
    assert (
        await _special(
            world, a, other, name="Ramadan", starts_on="2027-02-08", ends_on="2027-03-09"
        )
    ).status_code == 201


async def test_special_hours_edits_need_if_match_and_around_the_clock_has_none(
    world: World,
) -> None:
    a = world.a
    calendar = await _calendar(world, a)
    row = (
        await _special(
            world, a, calendar, name="Ramadan", starts_on="2027-02-08", ends_on="2027-03-09"
        )
    ).json()
    path = f"{CALENDARS}/{calendar['id']}/special-hours/{row['id']}"
    changed = await world.call(
        "PATCH", path, a, a.admin, json={"ends_on": "2027-03-10"}, headers=_match(row["version"])
    )
    assert changed.status_code == 200, changed.text
    stale = await world.call(
        "PATCH", path, a, a.admin, json={"name": "Late"}, headers=_match(row["version"])
    )
    assert problem(stale) == (409, "version_conflict")
    technician = await world.call(
        "DELETE", path, a, a.tech_a, headers=_match(changed.json()["version"])
    )
    assert problem(technician) == (403, "permission_denied")
    gone = await world.call("DELETE", path, a, a.admin, headers=_match(changed.json()["version"]))
    assert gone.status_code == 204, gone.text
    around = (await world.call("GET", CALENDARS, a, a.admin)).json()[0]
    refused = await _special(
        world, a, around, name="X", starts_on="2027-02-08", ends_on="2027-02-09"
    )
    assert field_codes(refused) == {"calendar_id": "system_calendar_fixed"}
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'sla.special_hours_changed'",
        a.tenant,
    )
    assert audit[0]["n"] >= 2
