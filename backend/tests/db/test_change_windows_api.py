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
    assert body["overridden"] is False
    assert [(c["kind"], c["blocks"]) for c in body["items"]] == [("outside_maintenance", False)]


async def test_the_freeze_override_is_decided_at_its_scope_audited_and_in_history(
    world: World,
) -> None:
    """Lane B: a group-scoped holder is refused on another group's change (403 with why)."""
    a = world.a
    await a_window(
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
        "POST", url, a, a.tech_b, json={"reason": "Vendor window"}, headers=headers
    )
    # Tech B (GB) may not even see GA's change: refused either way, never allowed.
    assert problem(other_group)[0] in {403, 404}, other_group.text
    if other_group.status_code == 403:
        assert other_group.json()["params"]["reason"] == "out_of_scope"
    empty = await world.call("POST", url, a, a.tech_a, json={"reason": "  "}, headers=headers)
    assert problem(empty)[0] == 422, empty.text
    passed = await world.call(
        "POST", url, a, a.tech_a, json={"reason": "Vendor only works then"}, headers=headers
    )
    assert passed.status_code == 200, passed.text
    in_freeze = SOON + timedelta(days=20, hours=10)
    allowed = await schedule(world, a, item, in_freeze, in_freeze + H)
    assert allowed.status_code == 200, allowed.text
    shown = (await world.call("GET", f"{CHG}/{item['id']}/conflicts", a, a.admin)).json()
    assert shown["overridden"] is True
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
        json={"reason": "Please"},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert problem(refused) == (403, "permission_denied"), refused.text
    assert refused.json()["params"]["reason"] == "no_permission"
