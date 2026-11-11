"""A release's schedule guard, conflicts and acks over HTTP (WP-058b S2; REQ-REL-040, -041).

Real PostgreSQL with RLS, ADR-042 addendum A:
- a deployment window or planned downtime in a blocking freeze is refused (409, naming it) on
  every path, an emergency release too; the release's own override passes only its freezes;
- a release always warns outside maintenance, whatever the change type's setting;
- changes and releases meet across types on the same group, site, service or CI, named by ID
  and type only; two releases sharing a role holder are booked twice (warn);
- moving one side clears the conflict on both; an ack holds for its conflict as it is, lapses
  when either side moves, and a block is never acked.
Each test plans its own year, so one test's windows never meet another's.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_change_windows_api import a_window, schedule
from tests.db.test_changes_api import CHG, new_change
from tests.db.test_incidents_api import CONSOLE, Org, World, problem
from tests.db.test_release_templates_api import field_codes
from tests.db.test_releases_api import REL, new_release

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

H = timedelta(hours=1)


async def _release(world: World, org: Org, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    made = await new_release(world, org, org.admin, **body)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def deploy(
    world: World, org: Org, item: dict[str, Any], start: datetime, end: datetime
) -> httpx.Response:
    rows = (await world.call("GET", f"{REL}/{item['id']}/schedule", org, org.admin)).json()
    row = next(r for r in rows if r["stage"] == "deployment")
    return await world.call(
        "PATCH",
        f"{REL}/{item['id']}/schedule/deployment",
        org,
        org.admin,
        json={"scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )


async def _conflicts(world: World, org: Org, item: dict[str, Any]) -> list[dict[str, Any]]:
    got = await world.call("GET", f"{REL}/{item['id']}/conflicts", org, org.admin)
    assert got.status_code == 200, got.text
    return list(got.json()["items"])


async def _version(world: World, org: Org, item: dict[str, Any]) -> int:
    return int((await world.call("GET", f"{REL}/{item['id']}", org, org.admin)).json()["version"])


async def test_req_rel_040_ac1_a_blocking_freeze_refuses_a_deployment_on_every_path(
    world: World,
) -> None:
    a = world.a
    at = datetime(2031, 2, 3, 9, tzinfo=UTC)
    freeze = await a_window(
        world,
        a,
        name="Quarter close",
        group_ids=[str(a.ga)],
        starts_at=at.isoformat(),
        ends_at=(at + 48 * H).isoformat(),
    )
    release = await _release(world, a, group_id=str(a.ga))
    refused = await deploy(world, a, release, at + H, at + 2 * H)
    assert problem(refused) == (409, "change_window_blocked"), refused.text
    assert refused.json()["params"]["window_ids"] == freeze["id"]
    downtime = await world.call(
        "POST",
        f"{REL}/{release['id']}/downtimes",
        a,
        a.admin,
        json={"starts_at": (at + H).isoformat(), "ends_at": (at + 2 * H).isoformat()},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert problem(downtime) == (409, "change_window_blocked"), downtime.text
    # An emergency release is refused too (the change's "marked, not refused" is change-only).
    await world.sql(
        "UPDATE work_items SET stage_path = 'emergency' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(release["id"]),
    )
    again = await deploy(world, a, release, at + H, at + 2 * H)
    assert problem(again) == (409, "change_window_blocked"), again.text
    # The release's override passes that freeze only; a later one still refuses.
    passed = await world.call(
        "POST",
        f"{REL}/{release['id']}/freeze-override",
        a,
        a.admin,
        json={"reason": "Payroll must go out", "window_ids": [freeze["id"]]},
        headers={"If-Match": f'"{await _version(world, a, release)}"', **CONSOLE},
    )
    assert passed.status_code == 200, passed.text
    allowed = await deploy(world, a, release, at + H, at + 2 * H)
    assert allowed.status_code == 200, allowed.text
    later = await a_window(
        world,
        a,
        name="Audit week",
        group_ids=[str(a.ga)],
        starts_at=(at + 30 * H).isoformat(),
        ends_at=(at + 40 * H).isoformat(),
    )
    still = await deploy(world, a, release, at + 31 * H, at + 32 * H)
    assert problem(still) == (409, "change_window_blocked"), still.text
    assert still.json()["params"]["window_ids"] == later["id"]


async def test_a_release_warns_outside_maintenance_whatever_the_change_setting(
    world: World,
) -> None:
    a = world.a
    at = datetime(2032, 3, 1, 1, tzinfo=UTC)
    await a_window(
        world,
        a,
        kind="maintenance",
        name="Sunday night",
        group_ids=[str(a.gb)],
        starts_at=at.isoformat(),
        ends_at=(at + 4 * H).isoformat(),
    )
    current = (await world.call("GET", f"{CHG}/settings", a, a.admin)).json()
    on = await world.call(
        "PATCH",
        f"{CHG}/settings",
        a,
        a.admin,
        json={"outside_maintenance_blocks": True},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert on.status_code == 200, on.text
    try:
        release = await _release(world, a, group_id=str(a.gb))
        outside = at + 30 * H
        warned = await deploy(world, a, release, outside, outside + H)
        assert warned.status_code == 200, warned.text
        kinds = {(c["kind"], c["blocks"]) for c in await _conflicts(world, a, release)}
        assert ("outside_maintenance", False) in kinds
    finally:
        current = (await world.call("GET", f"{CHG}/settings", a, a.admin)).json()
        await world.call(
            "PATCH",
            f"{CHG}/settings",
            a,
            a.admin,
            json={"outside_maintenance_blocks": False},
            headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
        )


async def test_req_rel_041_ac1_ac2_releases_and_changes_meet_and_part_live(world: World) -> None:
    a = world.a
    at = datetime(2033, 4, 5, 9, tzinfo=UTC)
    first = await _release(world, a, group_id=str(a.ga), subject="Secret payroll cut-over")
    second = await _release(world, a, group_id=str(a.ga))
    change = await new_change(world, a, a.admin, group_id=str(a.ga))
    assert change.status_code == 201, change.text
    item = change.json()
    assert (await deploy(world, a, first, at, at + 2 * H)).status_code == 200
    assert (await deploy(world, a, second, at + H, at + 3 * H)).status_code == 200
    assert (await schedule(world, a, item, at + H, at + 2 * H)).status_code == 200
    on_second = await world.call("GET", f"{REL}/{second['id']}/conflicts", a, a.admin)
    met = {(c["kind"], c["record_id"], c["record_type"]) for c in on_second.json()["items"]}
    assert ("overlap", first["id"], "release") in met
    assert ("overlap", item["id"], "change") in met
    assert "Secret payroll" not in on_second.text  # named by ID and type only
    on_change = (await world.call("GET", f"{CHG}/{item['id']}/conflicts", a, a.admin)).json()
    assert {(c["record_id"], c["record_type"]) for c in on_change["items"]} >= {
        (first["id"], "release"),
        (second["id"], "release"),
    }
    # Moving the first release away clears the overlap on both sides.
    assert (await deploy(world, a, first, at + 100 * H, at + 101 * H)).status_code == 200
    gone = {c["record_id"] for c in await _conflicts(world, a, second)}
    assert first["id"] not in gone
    assert second["id"] not in {c["record_id"] for c in await _conflicts(world, a, first)}


async def test_req_rel_041_a_shared_ci_and_a_double_booked_manager_conflict(world: World) -> None:
    a = world.a
    at = datetime(2034, 5, 6, 9, tzinfo=UTC)
    ci = str(uuid.uuid4())
    one = await _release(world, a, group_id=str(a.ga))
    two = await _release(world, a, group_id=str(a.gb))
    for release in (one, two):
        assert (await deploy(world, a, release, at, at + 2 * H)).status_code == 200
    # Different groups and no site (they took the requester's): nothing meets yet.
    await world.sql(
        "UPDATE work_items SET site_id = NULL WHERE tenant_id = $1 AND id = ANY($2::uuid[])",
        a.tenant,
        [uuid.UUID(one["id"]), uuid.UUID(two["id"])],
    )
    assert [c for c in await _conflicts(world, a, one) if c["kind"] == "overlap"] == []
    for release in (one, two):
        made = await world.call(
            "POST",
            f"{REL}/{release['id']}/downtimes",
            a,
            a.admin,
            json={
                "starts_at": (at + H).isoformat(),
                "ends_at": (at + 2 * H).isoformat(),
                "ci_ids": [ci],
            },
            headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
        )
        assert made.status_code == 201, made.text
    assert two["id"] in {
        c["record_id"] for c in await _conflicts(world, a, one) if c["kind"] == "overlap"
    }
    for release in (one, two):
        await world.sql(
            "INSERT INTO work_item_release_details (tenant_id, work_item_id, release_manager_id)"
            " VALUES ($1, $2, $3) ON CONFLICT (tenant_id, work_item_id)"
            " DO UPDATE SET release_manager_id = EXCLUDED.release_manager_id",
            a.tenant,
            uuid.UUID(release["id"]),
            a.tech_a,
        )
    booked = [c for c in await _conflicts(world, a, one) if c["kind"] == "role_booked"]
    assert {(c["record_id"], c["record_type"], c["blocks"]) for c in booked} >= {
        (two["id"], "release", False)
    }


async def test_req_rel_041_ac3_an_ack_holds_for_its_conflict_and_lapses_when_it_moves(
    world: World,
) -> None:
    a = world.a
    at = datetime(2035, 6, 7, 9, tzinfo=UTC)
    mine = await _release(world, a, group_id=str(a.ga))
    theirs = await _release(world, a, group_id=str(a.ga))
    assert (await deploy(world, a, mine, at, at + 2 * H)).status_code == 200
    assert (await deploy(world, a, theirs, at + H, at + 3 * H)).status_code == 200
    [overlap] = [c for c in await _conflicts(world, a, mine) if c["record_id"] == theirs["id"]]

    async def ack(key: str, reason: str = "Same team, agreed") -> httpx.Response:
        return await world.call(
            "POST",
            f"{REL}/{mine['id']}/conflicts/acks",
            a,
            a.admin,
            json={"key": key, "reason": reason},
            headers={"If-Match": f'"{await _version(world, a, mine)}"', **CONSOLE},
        )

    assert field_codes(await ack("overlap:nothing:here")) == {("key", "conflict_not_found")}
    assert problem(await ack(overlap["key"], "  "))[0] == 422
    done = await ack(overlap["key"])
    assert done.status_code == 200, done.text
    [shown] = [c for c in await _conflicts(world, a, mine) if c["record_id"] == theirs["id"]]
    assert shown["ack"]["reason"] == "Same team, agreed"
    assert shown["ack"]["acked_by"] == str(a.admin)
    history = await world.call("GET", f"{REL}/{mine['id']}/history", a, a.admin)
    assert "conflict_acknowledged" in {
        c["field"] for e in history.json()["items"] for c in e["changes"]
    }
    audit = await world.sql(
        "SELECT outcome FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'release.conflict_acknowledged' AND object_id = $2",
        a.tenant,
        mine["id"],
    )
    assert "done" in {r["outcome"] for r in audit}
    # The other side moves (still overlapping): a new conflict, never the old ack.
    assert (await deploy(world, a, theirs, at + H, at + 4 * H)).status_code == 200
    [moved] = [c for c in await _conflicts(world, a, mine) if c["record_id"] == theirs["id"]]
    assert moved["key"] != overlap["key"]
    assert moved["ack"] is None
    # And back to the same times: still a new conflict (the version moved on).
    assert (await deploy(world, a, theirs, at + H, at + 3 * H)).status_code == 200
    [back] = [c for c in await _conflicts(world, a, mine) if c["record_id"] == theirs["id"]]
    assert back["ack"] is None
    # A block is never acknowledged.
    freeze = await a_window(
        world,
        a,
        name="Late freeze",
        group_ids=[str(a.ga)],
        starts_at=(at - H).isoformat(),
        ends_at=(at + 10 * H).isoformat(),
    )
    [block] = [c for c in await _conflicts(world, a, mine) if c["window_id"] == freeze["id"]]
    assert block["blocks"] is True
    assert field_codes(await ack(block["key"])) == {("key", "conflict_blocks")}
