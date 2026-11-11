"""Freeze and maintenance windows over HTTP (WP-045c; REQ-CHG-073..077; ADR-042; D-156).

Real PostgreSQL with RLS. Windows are the change manager's and administrators'; a technician
reads them but never changes them. A new freeze blocks and a maintenance window warns (D-156
(a), (b)); a weekly window repeats (D-156 (c)). A change's implementation window or planned
downtime in a blocking freeze is refused (409) unless someone holding `changes.override_freeze`
at the change's scope passed its freezes with a reason (audited, in history); a group-scoped
holder never reaches another group's change (lane B's review).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_changes_api import CHG, new_change
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, role

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

WINDOWS = "/change-windows"
SOON = datetime(2027, 3, 1, 0, 0, tzinfo=UTC)  # a Monday, well ahead
H = timedelta(hours=1)


def _iso(value: datetime) -> str:
    return value.isoformat()


async def add_window(world: World, org: Org, user: uuid.UUID, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "POST",
        WINDOWS,
        org,
        user,
        json={
            "kind": "freeze",
            "name": "Quarter end",
            "starts_at": _iso(SOON),
            "ends_at": _iso(SOON + 48 * H),
            **body,
        },
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def a_window(world: World, org: Org, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    made = await add_window(world, org, org.admin, **body)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def a_group_change(world: World, org: Org) -> dict[str, Any]:
    made = await new_change(world, org, org.admin, group_id=str(org.ga))
    assert made.status_code == 201, made.text
    return dict(made.json())


async def schedule(
    world: World, org: Org, item: dict[str, Any], start: datetime, end: datetime
) -> httpx.Response:
    rows = (await world.call("GET", f"{CHG}/{item['id']}/schedule", org, org.admin)).json()
    row = next(r for r in rows if r["stage"] == "implementation")
    return await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/schedule/implementation",
        org,
        org.admin,
        json={"scheduled_start": _iso(start), "scheduled_end": _iso(end)},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )


async def test_d156_a_b_a_freeze_blocks_and_maintenance_warns_by_default(world: World) -> None:
    a = world.a
    freeze = await a_window(world, a)
    maintenance = await a_window(world, a, kind="maintenance", name="Saturday nights")
    assert (freeze["mode"], maintenance["mode"]) == ("block", "warn")
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'change.window_changed'",
        a.tenant,
    )
    assert audit[0]["n"] >= 2


async def test_a_technician_reads_windows_but_never_changes_them(world: World) -> None:
    a = world.a
    window = await a_window(world, a, name="Read only")
    listed = await world.call("GET", WINDOWS, a, a.tech_a)
    assert listed.status_code == 200, listed.text
    assert window["id"] in {w["id"] for w in listed.json()}
    refused = await add_window(world, a, a.tech_a, name="Not mine")
    assert problem(refused)[0] == 403, refused.text
    patched = await world.call(
        "PATCH",
        f"{WINDOWS}/{window['id']}",
        a,
        a.tech_a,
        json={"name": "Renamed"},
        headers={"If-Match": f'"{window["version"]}"', **CONSOLE},
    )
    assert problem(patched)[0] == 403, patched.text


async def test_windows_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    window = await a_window(world, a, name="Tenant A only")
    seen = await world.call("GET", f"{WINDOWS}/{window['id']}", b, b.admin)
    assert seen.status_code == 404, seen.text
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        rows = await session.execute(
            text("SELECT id FROM change_windows WHERE id = :w"), {"w": window["id"]}
        )
        assert rows.all() == []  # RLS: tenant B's session never sees tenant A's row
        written = await session.execute(
            text("UPDATE change_windows SET name = 'x' WHERE id = :w"), {"w": window["id"]}
        )
        assert written.rowcount == 0


async def test_a_window_checks_its_own_values(world: World) -> None:
    a = world.a
    backwards = await add_window(world, a, a.admin, ends_at=_iso(SOON - H))
    assert problem(backwards)[0] == 422, backwards.text
    week_long = await add_window(
        world, a, a.admin, repeat_weekly=True, ends_at=_iso(SOON + timedelta(days=8))
    )
    assert "longer_than_a_week" in week_long.text
    unknown_site = await add_window(world, a, a.admin, site_ids=[str(uuid.uuid4())])
    assert "site_not_found" in unknown_site.text


async def test_req_chg_077_a_blocking_freeze_refuses_the_change_s_window_with_why(
    world: World,
) -> None:
    a = world.a
    # Scoped to the change's group, so other tests' changes are never caught.
    freeze = await a_window(world, a, name="GA freeze", group_ids=[str(a.ga)])
    item = await a_group_change(world, a)
    inside = await schedule(world, a, item, SOON + 10 * H, SOON + 12 * H)
    assert problem(inside) == (409, "change_window_blocked"), inside.text
    assert inside.json()["params"]["window_id"] == freeze["id"]
    after = await schedule(world, a, item, SOON + 60 * H, SOON + 62 * H)
    assert after.status_code == 200, after.text
    # A planned downtime is the change's planned time too.
    downtime = await world.call(
        "POST",
        f"{CHG}/{item['id']}/downtimes",
        a,
        a.admin,
        json={"starts_at": _iso(SOON + H), "ends_at": _iso(SOON + 2 * H)},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert problem(downtime) == (409, "change_window_blocked"), downtime.text


async def test_d156_c_a_weekly_freeze_blocks_every_week(world: World) -> None:
    a = world.a
    await a_window(
        world,
        a,
        name="Monday mornings",
        group_ids=[str(a.ga)],
        ends_at=_iso(SOON + 6 * H),
        repeat_weekly=True,
    )
    item = await a_group_change(world, a)
    three_weeks_on = SOON + timedelta(weeks=3)
    refused = await schedule(world, a, item, three_weeks_on + H, three_weeks_on + 2 * H)
    assert problem(refused) == (409, "change_window_blocked"), refused.text
    afternoon = await schedule(world, a, item, three_weeks_on + 12 * H, three_weeks_on + 13 * H)
    assert afternoon.status_code == 200, afternoon.text


async def test_conflicts_list_the_freeze_the_maintenance_window_and_why(world: World) -> None:
    a = world.a
    sat = SOON + timedelta(days=12, hours=22)  # far from the other tests' times
    await a_window(
        world,
        a,
        kind="maintenance",
        name="GA Saturday",
        group_ids=[str(a.ga)],
        starts_at=_iso(sat),
        ends_at=_iso(sat + 6 * H),
    )
    item = await a_group_change(world, a)
    outside = await schedule(world, a, item, sat - 30 * H, sat - 29 * H)
    assert outside.status_code == 200, outside.text  # a warning only (D-156 (b))
    shown = await world.call("GET", f"{CHG}/{item['id']}/conflicts", a, a.admin)
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert body["passed_window_ids"] == []
    assert [(c["kind"], c["blocks"]) for c in body["items"]] == [("outside_maintenance", False)]


async def test_the_freeze_override_is_decided_at_its_scope_audited_and_in_history(
    world: World,
) -> None:
    """Lane B: a group-scoped holder is refused on another group's change (403 with why)."""
    a = world.a
    freeze = await a_window(
        world,
        a,
        name="Override freeze",
        group_ids=[str(a.ga)],
        starts_at=_iso(SOON + timedelta(days=20)),
        ends_at=_iso(SOON + timedelta(days=22)),
    )
    item = await a_group_change(world, a)
    group_override = await role(world, a, "Group freeze", [("changes.override_freeze", "group")])
    for tech in (a.tech_a, a.tech_b):
        given = await world.call("PUT", f"/users/{tech}/roles/{group_override}", a, a.admin)
        assert given.status_code == 204, given.text
    current = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    url = f"{CHG}/{item['id']}/freeze-override"
    headers = {"If-Match": f'"{current["version"]}"', **CONSOLE}
    other_group = await world.call(
        "POST",
        url,
        a,
        a.tech_b,
        json={"reason": "Vendor window", "window_ids": [freeze["id"]]},
        headers=headers,
    )
    # Tech B (GB) may not even see GA's change: refused either way, never allowed.
    assert problem(other_group)[0] in {403, 404}, other_group.text
    if other_group.status_code == 403:
        assert other_group.json()["params"]["reason"] == "out_of_scope"
    empty = await world.call(
        "POST",
        url,
        a,
        a.tech_a,
        json={"reason": "  ", "window_ids": [freeze["id"]]},
        headers=headers,
    )
    assert problem(empty)[0] == 422, empty.text
    # Only a live blocking freeze can be passed; a made-up one is refused.
    unknown = await world.call(
        "POST",
        url,
        a,
        a.tech_a,
        json={"reason": "Vendor", "window_ids": [str(uuid.uuid4())]},
        headers=headers,
    )
    assert "window_ids" in unknown.text, unknown.text
    passed = await world.call(
        "POST",
        url,
        a,
        a.tech_a,
        json={"reason": "Vendor only works then", "window_ids": [freeze["id"]]},
        headers=headers,
    )
    assert passed.status_code == 200, passed.text
    in_freeze = SOON + timedelta(days=20, hours=10)
    allowed = await schedule(world, a, item, in_freeze, in_freeze + H)
    assert allowed.status_code == 200, allowed.text
    shown = (await world.call("GET", f"{CHG}/{item['id']}/conflicts", a, a.admin)).json()
    assert shown["passed_window_ids"] == [freeze["id"]]
    assert [(c["kind"], c["blocks"]) for c in shown["items"]] == [("freeze", False)]
    history = await world.call("GET", f"{CHG}/{item['id']}/history", a, a.admin)
    fields = {c["field"] for e in history.json()["items"] for c in e["changes"]}
    assert "freeze_override" in fields
    audit = await world.sql(
        "SELECT outcome FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'change.freeze_override' AND object_id = $2",
        a.tenant,
        item["id"],
    )
    outcomes = {r["outcome"] for r in audit}
    assert "done" in outcomes
    assert "refused" in outcomes  # the refused attempt is audited too


async def test_a_technician_without_the_permission_cannot_pass_a_freeze(world: World) -> None:
    a = world.a
    item = await a_group_change(world, a)
    current = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    refused = await world.call(
        "POST",
        f"{CHG}/{item['id']}/freeze-override",
        a,
        a.tech_c,  # GA and GB, a plain technician
        json={"reason": "Please", "window_ids": [str(uuid.uuid4())]},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert problem(refused) == (403, "permission_denied"), refused.text
    assert refused.json()["params"]["reason"] == "no_permission"


async def test_an_override_passes_only_its_freezes_never_a_later_one(world: World) -> None:
    """Lane B's review of #376: passing freeze A at T1 never lets anyone move the change into
    freeze B at T2; that needs its own override.
    """
    a = world.a
    first = await a_window(
        world,
        a,
        name="First freeze",
        group_ids=[str(a.ga)],
        starts_at=_iso(SOON + timedelta(days=30)),
        ends_at=_iso(SOON + timedelta(days=31)),
    )
    item = await a_group_change(world, a)
    t1 = SOON + timedelta(days=30, hours=2)
    refused = await schedule(world, a, item, t1, t1 + H)
    assert problem(refused) == (409, "change_window_blocked"), refused.text
    assert refused.json()["params"]["window_ids"] == first["id"]
    current = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    passed = await world.call(
        "POST",
        f"{CHG}/{item['id']}/freeze-override",
        a,
        a.admin,
        json={"reason": "Board approved", "window_ids": [first["id"]]},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert passed.status_code == 200, passed.text
    assert (await schedule(world, a, item, t1, t1 + H)).status_code == 200
    # A second freeze, added later: a technician of the change's group moves it there.
    later = await a_window(
        world,
        a,
        name="Later freeze",
        group_ids=[str(a.ga)],
        starts_at=_iso(SOON + timedelta(days=40)),
        ends_at=_iso(SOON + timedelta(days=41)),
    )
    t2 = SOON + timedelta(days=40, hours=2)
    rows = (await world.call("GET", f"{CHG}/{item['id']}/schedule", a, a.tech_a)).json()
    row = next(r for r in rows if r["stage"] == "implementation")
    moved = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/schedule/implementation",
        a,
        a.tech_a,
        json={"scheduled_start": _iso(t2), "scheduled_end": _iso(t2 + H)},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert problem(moved) == (409, "change_window_blocked"), moved.text
    assert moved.json()["params"]["window_ids"] == later["id"]


async def test_d156_a_first_sunday_freeze_blocks_that_sunday_every_month(world: World) -> None:
    """Monthly windows (D-156): "first Sunday, 02:00-06:00" blocks the first Sunday of every
    month and no other Sunday."""
    from app.modules.work_items.domain.change_windows import nth_weekday  # noqa: PLC0415

    a = world.a
    later = SOON + timedelta(days=200)  # far from the other tests' times
    day = nth_weekday(later.year, later.month, 1, 6)
    assert day is not None
    first = datetime(day.year, day.month, day.day, 2, 0, tzinfo=UTC)
    made = await a_window(
        world,
        a,
        name="First Sunday",
        group_ids=[str(a.gb)],
        starts_at=_iso(first),
        ends_at=_iso(first + 4 * H),
        repeat="monthly",
        repeat_week=1,
        repeat_weekday=6,
    )
    assert (made["repeat"], made["repeat_week"], made["repeat_weekday"]) == ("monthly", 1, 6)
    assert made["repeat_weekly"] is False
    change = await new_change(world, a, a.admin, group_id=str(a.gb))
    assert change.status_code == 201, change.text
    item = change.json()
    three_on = first.month + 3
    year, month = first.year + (three_on - 1) // 12, (three_on - 1) % 12 + 1
    sunday = nth_weekday(year, month, 1, 6)
    second = nth_weekday(year, month, 2, 6)
    assert sunday is not None
    assert second is not None
    at = datetime(sunday.year, sunday.month, sunday.day, 3, 0, tzinfo=UTC)
    refused = await schedule(world, a, item, at, at + H)
    assert problem(refused) == (409, "change_window_blocked"), refused.text
    other = datetime(second.year, second.month, second.day, 3, 0, tzinfo=UTC)
    fine = await schedule(world, a, item, other, other + H)
    assert fine.status_code == 200, fine.text


async def test_d156_an_old_client_s_weekly_flag_still_makes_a_weekly_window(world: World) -> None:
    made = await a_window(
        world, world.a, name="Old client", ends_at=_iso(SOON + 2 * H), repeat_weekly=True
    )
    assert (made["repeat"], made["repeat_weekly"]) == ("weekly", True)


async def test_d156_the_tenant_can_make_outside_maintenance_block(world: World) -> None:
    """D-156: off by default (warn); on, a change outside every maintenance window is refused;
    the switch is audited and only changes have it."""
    b = world.b  # its own tenant, so the switch never reaches the other tests
    sunday = SOON + timedelta(days=6, hours=1)
    await a_window(
        world,
        b,
        kind="maintenance",
        name="Sunday night",
        group_ids=[str(b.gb)],
        starts_at=_iso(sunday),
        ends_at=_iso(sunday + 4 * H),
        repeat="weekly",
    )
    change = await new_change(world, b, b.admin, group_id=str(b.gb))
    assert change.status_code == 201, change.text
    item = change.json()
    tuesday = SOON + timedelta(days=8, hours=10)
    warned = await schedule(world, b, item, tuesday, tuesday + H)
    assert warned.status_code == 200, warned.text  # the default: a warning, not a refusal

    async def switch(path: str, *, on: bool) -> int:
        current = (await world.call("GET", f"{path}/settings", b, b.admin)).json()
        changed = await world.call(
            "PATCH",
            f"{path}/settings",
            b,
            b.admin,
            json={"outside_maintenance_blocks": on},
            headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
        )
        return changed.status_code

    assert await switch("/incidents", on=True) == 422  # changes only
    assert await switch(CHG, on=True) == 200
    try:
        refused = await schedule(world, b, item, tuesday + timedelta(weeks=1), tuesday + 9 * 24 * H)
        assert problem(refused) == (409, "change_window_blocked"), refused.text
        inside = await schedule(
            world,
            b,
            item,
            sunday + timedelta(weeks=2, hours=1),
            sunday + timedelta(weeks=2, hours=2),
        )
        assert inside.status_code == 200, inside.text
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            logged = await session.scalar(
                text(
                    "SELECT count(*) FROM audit_entries WHERE action = 'change.settings_changed' "
                    "AND details::text LIKE '%outside_maintenance_blocks%'"
                )
            )
        assert logged == 1
    finally:
        assert await switch(CHG, on=False) == 200


async def test_the_calendar_lists_the_changes_you_may_see_in_a_range(world: World) -> None:
    """WP-045c S3: implementation windows and planned downtimes in [start, end), visible only."""
    a = world.a
    item = await a_group_change(world, a)
    at = SOON + timedelta(days=60, hours=9)
    assert (await schedule(world, a, item, at, at + 2 * H)).status_code == 200
    downtime = await world.call(
        "POST",
        f"{CHG}/{item['id']}/downtimes",
        a,
        a.admin,
        json={"starts_at": _iso(at + H), "ends_at": _iso(at + 90 * timedelta(minutes=1))},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert downtime.status_code == 201, downtime.text
    params = {"start": _iso(SOON + timedelta(days=59)), "end": _iso(SOON + timedelta(days=61))}
    shown = await world.call("GET", "/change-calendar", a, a.tech_a, params=params)
    assert shown.status_code == 200, shown.text
    mine = [e for e in shown.json() if e["record_id"] == item["id"]]
    assert sorted(e["kind"] for e in mine) == ["downtime", "window"]
    assert {e["display_id"] for e in mine} == {item["display_id"]}
    # Without changes.view (a requester) there is no calendar at all.
    refused = await world.call("GET", "/change-calendar", a, a.requester, params=params)
    assert problem(refused)[0] == 403, refused.text
    # "Mine": only the changes you hold (nobody holds this one).
    held = await world.call(
        "GET", "/change-calendar", a, a.tech_a, params={**params, "mine": "true"}
    )
    assert item["id"] not in {e["record_id"] for e in held.json()}
    elsewhere = await world.call(
        "GET",
        "/change-calendar",
        a,
        a.tech_a,
        params={"start": _iso(SOON + timedelta(days=70)), "end": _iso(SOON + timedelta(days=71))},
    )
    assert item["id"] not in {e["record_id"] for e in elsewhere.json()}
    too_long = await world.call(
        "GET",
        "/change-calendar",
        a,
        a.tech_a,
        params={"start": _iso(SOON), "end": _iso(SOON + timedelta(days=500))},
    )
    assert problem(too_long)[0] == 422, too_long.text


# --- D-156: an emergency change in a freeze goes through its emergency CAB ----------------------


async def _emergency(world: World, org: Org) -> dict[str, Any]:
    made = await new_change(world, org, org.admin, change_type="emergency", group_id=str(org.gb))
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _to_cab(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    from tests.db.test_changes_api import _approve_pending, move  # noqa: PLC0415 - helpers

    raised = await move(
        world, org, await _fresh(world, org, item), "submission_awaiting_acceptance"
    )
    assert raised.status_code == 200, raised.text
    at_cab = await _approve_pending(world, org, raised.json())
    assert at_cab["status"] == "cab_awaiting", at_cab
    return at_cab


async def _fresh(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    return dict((await world.call("GET", f"{CHG}/{item['id']}", org, org.admin)).json())


async def _cab_decision(
    world: World, org: Org, item: dict[str, Any], comment: str | None
) -> httpx.Response:
    rows = (await world.call("GET", f"{CHG}/{item['id']}/approvals", org, org.admin)).json()
    [entry] = [r for r in rows["items"] if r["state"] == "pending"]
    return await world.call(
        "POST",
        f"{CHG}/{item['id']}/approvals/{entry['id']}/decision",
        org,
        org.admin,
        json={"decision": "approve", **({"comment": comment} if comment else {})},
        headers={"If-Match": f'"{entry["version"]}"', **CONSOLE},
    )


async def _start(world: World, org: Org, item: dict[str, Any]) -> httpx.Response:
    from tests.db.test_changes_api import move  # noqa: PLC0415 - shared helper

    return await move(world, org, await _fresh(world, org, item), "implementation_in_progress")


FROZEN = SOON + timedelta(days=300)  # far from the other tests' times


async def _freeze_gb(world: World, org: Org, name: str, start: datetime) -> dict[str, Any]:
    return await a_window(
        world,
        org,
        name=name,
        group_ids=[str(org.gb)],
        starts_at=_iso(start),
        ends_at=_iso(start + 48 * H),
    )


async def test_d156_an_emergency_change_in_a_freeze_is_saved_and_its_cab_passes_it(
    world: World,
) -> None:
    """Saved, not refused; the emergency CAB approving it needs a reason, which stamps the
    change (audited, in its history); then its work may start."""
    a = world.a
    start = FROZEN
    await _freeze_gb(world, a, "Year end (emergency)", start)
    item = await _emergency(world, a)
    saved = await schedule(world, a, item, start + H, start + 3 * H)
    assert saved.status_code == 200, saved.text  # marked, never refused
    conflicts = (await world.call("GET", f"{CHG}/{item['id']}/conflicts", a, a.admin)).json()
    assert [c["kind"] for c in conflicts["items"] if c["blocks"]] == ["freeze"]
    at_cab = await _to_cab(world, a, item)
    bare = await _cab_decision(world, a, at_cab, None)
    assert bare.status_code == 422, bare.text
    assert ("body.comment", "reason_required") in {
        (e["field"], e["code"]) for e in bare.json()["errors"]
    }
    passed = await _cab_decision(world, a, at_cab, "Outage fix: the bank's cut-over")
    assert passed.status_code == 200, passed.text
    now = await _fresh(world, a, item)
    assert now["stage"] == "implementation", now
    (row,) = await world.sql(
        "SELECT freeze_cab_passed_at, freeze_cab_passed_by FROM work_item_change_details"
        " WHERE work_item_id = $1",
        uuid.UUID(item["id"]),
    )
    assert row["freeze_cab_passed_at"] is not None
    assert row["freeze_cab_passed_by"] == a.admin
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        logged = await session.scalar(
            text(
                "SELECT count(*) FROM audit_entries WHERE action = 'change.freeze_passed_by_cab'"
                " AND object_id = :id"
            ),
            {"id": item["id"]},
        )
    assert logged == 1
    history = (await world.call("GET", f"{CHG}/{item['id']}/history", a, a.admin)).json()
    assert any(c["field"] == "freeze_passed_by_cab" for h in history["items"] for c in h["changes"])
    started = await _start(world, a, item)
    assert started.status_code == 200, started.text


async def test_d156_without_its_cab_s_pass_an_emergency_change_does_not_start_in_a_freeze(
    world: World,
) -> None:
    """Approved before the freeze came: starting the work in it is refused, with why, until
    the change manager's override lets it go."""
    a = world.a
    start = FROZEN + timedelta(days=10)
    item = await _emergency(world, a)
    assert (await schedule(world, a, item, start + H, start + 3 * H)).status_code == 200
    at_cab = await _to_cab(world, a, item)
    assert (await _cab_decision(world, a, at_cab, None)).status_code == 200  # no freeze yet
    freeze = await _freeze_gb(world, a, "Late freeze", start)
    refused = await _start(world, a, item)
    assert problem(refused) == (409, "stage_move_refused"), refused.text
    assert refused.json()["params"]["reason"] == "freeze_needs_emergency_cab"
    now = await _fresh(world, a, item)
    overridden = await world.call(
        "POST",
        f"{CHG}/{item['id']}/freeze-override",
        a,
        a.admin,
        json={"reason": "Signed off by the director", "window_ids": [freeze["id"]]},
        headers={"If-Match": f'"{now["version"]}"', **CONSOLE},
    )
    assert overridden.status_code == 200, overridden.text
    started = await _start(world, a, item)
    assert started.status_code == 200, started.text


async def test_d156_a_normal_change_in_a_freeze_is_still_refused(world: World) -> None:
    a = world.a
    start = FROZEN + timedelta(days=20)
    await _freeze_gb(world, a, "Normal freeze", start)
    made = await new_change(world, a, a.admin, group_id=str(a.gb))
    assert made.status_code == 201, made.text
    refused = await schedule(world, a, made.json(), start + H, start + 3 * H)
    assert problem(refused) == (409, "change_window_blocked"), refused.text
