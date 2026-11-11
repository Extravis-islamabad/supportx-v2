"""Changes in a release (WP-058b S1; REQ-REL-033) over HTTP.

Real PostgreSQL with RLS:
- linking a change writes history on both records and the release lists it (AC1);
- a change already in another open release is refused, naming that release (AC2); once that
  release is closed or canceled, the change may join another;
- a viewer who may not see a change sees that a linked change exists, not its title (AC3);
- taking it out writes history on both.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_changes_api import new_change
from tests.db.test_incidents_api import CONSOLE, Org, World, role
from tests.db.test_release_templates_api import field_codes
from tests.db.test_releases_api import REL, a_release

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

HOUR, DAY = timedelta(hours=1), timedelta(days=1)


async def _change(world: World, org: Org) -> dict[str, Any]:
    made = await new_change(world, org, org.admin)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _add(
    world: World, org: Org, release: dict[str, Any], change: dict[str, Any]
) -> httpx.Response:
    return await world.call(
        "POST",
        f"{REL}/{release['id']}/changes",
        org,
        org.admin,
        json={"change_id": change["id"]},
        headers=CONSOLE,
    )


async def _history_links(world: World, org: Org, path: str) -> list[dict[str, Any]]:
    got = await world.call("GET", f"{path}/history", org, org.admin)
    return [c for entry in got.json()["items"] for c in entry["changes"] if c["field"] == "link"]


async def test_req_rel_033_ac1_a_change_in_a_release_is_on_both_records(world: World) -> None:
    a = world.a
    release, change = await a_release(world, a), await _change(world, a)
    added = await _add(world, a, release, change)
    assert added.status_code == 204, added.text
    listed = (await world.call("GET", f"{REL}/{release['id']}/changes", a, a.admin)).json()
    assert [(c["id"], c["visible"], c["display_id"]) for c in listed] == [
        (change["id"], True, change["display_id"])
    ]
    on_release = await _history_links(world, a, f"{REL}/{release['id']}")
    on_change = await _history_links(world, a, f"/changes/{change['id']}")
    assert on_release[0]["new"]["kind"] == on_change[0]["new"]["kind"] == "in_release"
    assert on_release[0]["new"]["display_id"] == change["display_id"]
    again = await _add(world, a, release, change)  # already in this one: nothing changes
    assert again.status_code == 204
    assert len((await world.call("GET", f"{REL}/{release['id']}/changes", a, a.admin)).json()) == 1
    removed = await world.call(
        "DELETE", f"{REL}/{release['id']}/changes/{change['id']}", a, a.admin, headers=CONSOLE
    )
    assert removed.status_code == 204, removed.text
    assert (await world.call("GET", f"{REL}/{release['id']}/changes", a, a.admin)).json() == []
    assert (await _history_links(world, a, f"/changes/{change['id']}"))[0]["old"][
        "kind"
    ] == "in_release"


async def test_req_rel_033_ac2_one_open_release_per_change(world: World) -> None:
    a = world.a
    first, second = await a_release(world, a), await a_release(world, a)
    change = await _change(world, a)
    assert (await _add(world, a, first, change)).status_code == 204
    refused = await _add(world, a, second, change)
    assert field_codes(refused) == {("change_id", "change_in_other_release")}
    assert refused.json()["errors"][0]["params"] == {"release": first["display_id"]}
    # Once the first release is finished, the change may join another.
    await world.sql(
        "UPDATE work_items SET status_category = 'canceled', status = 'closure_canceled',"
        " stage = 'closure', version = version + 1 WHERE id = $1",
        uuid.UUID(first["id"]),
    )
    assert (await _add(world, a, second, change)).status_code == 204


async def test_req_rel_033_ac3_a_change_you_may_not_see_shows_only_that_it_is(
    world: World,
) -> None:
    a = world.a
    release, change = await a_release(world, a), await _change(world, a)
    assert (await _add(world, a, release, change)).status_code == 204
    viewer = await role(world, a, "Release viewer only", [("releases.view", "all")])
    assigned = await world.call("PUT", f"/users/{a.tech_b}/roles/{viewer}", a, a.admin)
    assert assigned.status_code in {200, 204}, assigned.text
    await world.sql("DELETE FROM user_roles WHERE user_id = $1 AND role_id <> $2", a.tech_b, viewer)
    listed = await world.call("GET", f"{REL}/{release['id']}/changes", a, a.tech_b)
    assert listed.status_code == 200, listed.text
    [shown] = listed.json()
    assert (shown["visible"], shown["display_id"], shown["subject"]) == (False, None, None)
    assert change["subject"] not in listed.text


async def test_req_rel_027_the_release_calendar_shows_deployment_windows(world: World) -> None:
    """WP-058b S1: a release's deployment window on its calendar; the same query as changes'."""
    a, b = world.a, world.b
    release = await a_release(world, a)
    at = datetime(2031, 3, 4, 9, tzinfo=UTC)
    rows = (await world.call("GET", f"{REL}/{release['id']}/schedule", a, a.admin)).json()
    row = next(r for r in rows if r["stage"] == "deployment")
    planned = await world.call(
        "PATCH",
        f"{REL}/{release['id']}/schedule/deployment",
        a,
        a.admin,
        json={"scheduled_start": at.isoformat(), "scheduled_end": (at + HOUR).isoformat()},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert planned.status_code == 200, planned.text
    params = {"start": (at - DAY).isoformat(), "end": (at + DAY).isoformat()}
    shown = await world.call("GET", "/release-calendar", a, a.admin, params=params)
    assert shown.status_code == 200, shown.text
    [entry] = [e for e in shown.json() if e["record_id"] == release["id"]]
    assert (entry["kind"], entry["display_id"]) == ("window", release["display_id"])
    # Releases never show on the change calendar, and the other tenant sees nothing.
    changes = await world.call("GET", "/change-calendar", a, a.admin, params=params)
    assert release["id"] not in {e["record_id"] for e in changes.json()}
    other = await world.call("GET", "/release-calendar", b, b.admin, params=params)
    assert release["id"] not in {e["record_id"] for e in other.json()}
    refused = await world.call("GET", "/release-calendar", a, a.requester, params=params)
    assert refused.status_code == 403, refused.text
    too_long = await world.call(
        "GET",
        "/release-calendar",
        a,
        a.admin,
        params={"start": params["start"], "end": (at + 500 * DAY).isoformat()},
    )
    assert too_long.status_code == 422, too_long.text


async def test_a_change_that_holds_the_release_cannot_go_in_it(world: World) -> None:
    """Lane A's #386 review: release R part of change X (directly, or through R's parent) refuses
    X in R (would loop); a change that does not hold it still joins."""
    a = world.a
    parent, child = await a_release(world, a), await a_release(world, a)
    holder, other = await _change(world, a), await _change(world, a)
    made = await world.call(
        "PUT",
        f"{REL}/{child['id']}/parent",
        a,
        a.admin,
        json={"parent_id": parent["id"]},
        headers=CONSOLE,
    )
    assert made.status_code in {200, 204}, made.text
    part = await world.call(
        "POST",
        f"/changes/{holder['id']}/children",
        a,
        a.admin,
        json={"child_id": parent["id"]},
        headers=CONSOLE,
    )
    assert part.status_code in {200, 201, 204}, part.text
    for release in (parent, child):  # directly, and through the sub-release's parent
        refused = await _add(world, a, release, holder)
        assert field_codes(refused) == {("change_id", "change_would_loop")}, refused.text
    assert (await _add(world, a, child, other)).status_code == 204
