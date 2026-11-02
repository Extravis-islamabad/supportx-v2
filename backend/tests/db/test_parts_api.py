"""Tasks, worklogs and links over HTTP (WP-020e; REQ-INC-067, 072, 084).

Real PostgreSQL, the incidents test world. Each test names the requirement and criterion.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.test_incidents_api import BASE, Org, World, field_codes, incidents_world, problem
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(migrated_db) as built:
        yield built


async def add_task(
    world: World, org: Org, user: uuid.UUID, item: dict[str, Any], **body: object
) -> httpx.Response:
    return await world.call("POST", f"{BASE}/{item['id']}/tasks", org, user, json=body)


async def tasks(world: World, org: Org, user: uuid.UUID, item: dict[str, Any]) -> dict[str, Any]:
    found = await world.call("GET", f"{BASE}/{item['id']}/tasks", org, user)
    assert found.status_code == 200, found.text
    return dict(found.json())


def fields(entries: list[dict[str, Any]]) -> list[str]:
    return [c["field"] for e in entries for c in e["changes"]]


# --- tasks (REQ-INC-072) --------------------------------------------------------------------------


async def test_req_inc_072_ac1_tasks_count_done_over_total_with_history(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    first = await add_task(
        world, a, a.tech_a, item, title="Check the cable", owner_id=str(a.tech_a)
    )
    assert first.status_code == 201, first.text
    await add_task(world, a, a.tech_a, item, title="Swap the printer", status="done")
    await add_task(world, a, a.tech_a, item, title="Not needed", status="canceled")
    found = await tasks(world, a, a.tech_a, item)
    assert (found["done"], found["total"]) == (1, 2)  # canceled ones do not count
    assert [t["title"] for t in found["items"]] == [
        "Check the cable",
        "Swap the printer",
        "Not needed",
    ]
    assert "task" in fields(await world.history(a, item))
    # Only someone who may edit the record adds tasks.
    refused = await add_task(world, a, a.tech_b, item, title="Elsewhere")
    assert refused.status_code == 404, refused.text  # tech_b cannot see GA's record at all
    # This tenant only: in one process other tests write part events to the same database.
    events = await world.sql(
        "SELECT count(*) AS n FROM outbox_events"
        " WHERE event_type = 'work_items.part.changed' AND tenant_id = $1",
        a.tenant,
    )
    assert events[0]["n"] == 3


async def test_req_inc_072_ac2_reordering_is_saved(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    for title in ("One", "Two", "Three"):
        await add_task(world, a, a.admin, item, title=title)
    third = (await tasks(world, a, a.admin, item))["items"][2]
    moved = await world.call(
        "POST",
        f"{BASE}/{item['id']}/tasks/{third['id']}/move",
        a,
        a.admin,
        json={"direction": "up"},
    )
    assert moved.status_code == 200, moved.text
    assert [t["title"] for t in (await tasks(world, a, a.tech_a, item))["items"]] == [
        "One",
        "Three",
        "Two",
    ]
    first = (await tasks(world, a, a.admin, item))["items"][0]
    stuck = await world.call(
        "POST",
        f"{BASE}/{item['id']}/tasks/{first['id']}/move",
        a,
        a.admin,
        json={"direction": "up"},
    )
    assert field_codes(stuck) == {"by": "out_of_range"}


async def _task_owner_access(world: World, org: Org, *, on: bool) -> None:
    current = (await world.call("GET", f"{BASE}/settings", org, org.admin)).json()
    changed = await world.call(
        "PATCH",
        f"{BASE}/settings/closure",
        org,
        org.admin,
        json={"task_owner_access": on},
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["closure"]["task_owner_access"] is on


async def test_req_inc_072_ac3_task_only_owner_updates_the_task_never_sees_notes(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))  # tech_b cannot see GA's records
    await world.call(
        "POST",
        f"{BASE}/{item['id']}/conversation",
        a,
        a.admin,
        json={"kind": "note", "visibility": "private", "body": "<p>Secret</p>"},
    )
    task = (
        await add_task(world, a, a.admin, item, title="Ship a toner", owner_id=str(a.tech_b))
    ).json()
    path = f"{BASE}/{item['id']}/tasks/{task['id']}"
    # Off by default: the owner is as far away as anyone else.
    blocked = await world.call(
        "PATCH", path, a, a.tech_b, json={"status": "done"}, headers={"If-Match": '"1"'}
    )
    assert problem(blocked) == (404, "work_item_not_found")
    assert (await world.call("GET", f"{BASE}/my-tasks", a, a.tech_b)).json() == []
    await _task_owner_access(world, a, on=True)
    mine = (await world.call("GET", f"{BASE}/my-tasks", a, a.tech_b)).json()
    assert [(m["display_id"], m["task"]["title"]) for m in mine] == [
        (item["display_id"], "Ship a toner")
    ]
    done = await world.call(
        "PATCH", path, a, a.tech_b, json={"status": "done"}, headers={"If-Match": '"1"'}
    )
    assert done.status_code == 200, done.text
    assert done.json()["done_at"] is not None
    retitled = await world.call(
        "PATCH", path, a, a.tech_b, json={"title": "Mine now"}, headers={"If-Match": '"2"'}
    )
    assert problem(retitled) == (403, "permission_denied")
    # Never the record, its conversation or its notes.
    assert (await world.get(a, a.tech_b, item)).status_code == 404
    notes = await world.call("GET", f"{BASE}/{item['id']}/conversation", a, a.tech_b)
    assert notes.status_code == 404


async def test_open_tasks_are_open_work_when_resolving(world: World) -> None:
    """WP-020f port: an open task asks for a confirmation (warn by default)."""
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    await add_task(world, a, a.admin, item, title="Call the vendor")
    warned = await world.act(a, a.admin, item, "resolve", resolution="<p>Done</p>")
    assert problem(warned) == (409, "open_work_unconfirmed")
    assert "Call the vendor" in str(warned.json()["params"])
    item = (await world.get(a, a.admin, item)).json()
    confirmed = await world.act(
        a, a.admin, item, "resolve", resolution="<p>Done</p>", confirm_open_work=True
    )
    assert confirmed.status_code == 200, confirmed.text


# --- worklogs (REQ-INC-067) -----------------------------------------------------------------------


async def log(
    world: World, org: Org, user: uuid.UUID, item: dict[str, Any], **body: object
) -> httpx.Response:
    return await world.call("POST", f"{BASE}/{item['id']}/worklogs", org, user, json=body)


async def test_req_inc_067_ac1_end_before_start_is_refused(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    refused = await log(
        world,
        a,
        a.tech_a,
        item,
        worklog_type="fix",
        started_at="2026-10-28T10:00:00Z",
        ended_at="2026-10-28T09:00:00Z",
    )
    assert field_codes(refused) == {"ended_at": "end_before_start"}
    no_start = await log(world, a, a.tech_a, item, worklog_type="fix", minutes=30)
    assert field_codes(no_start) == {"started_at": "required"}
    mismatch = await log(
        world,
        a,
        a.tech_a,
        item,
        worklog_type="fix",
        started_at="2026-10-28T10:00:00Z",
        ended_at="2026-10-28T11:00:00Z",
        minutes=30,
    )
    assert field_codes(mismatch) == {"minutes": "duration_mismatch"}


async def test_req_inc_067_ac2_ac3_times_fill_each_other_and_totals_add_up(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    by_duration = await log(
        world, a, a.tech_a, item, worklog_type="fix", started_at="2026-10-28T10:00:00Z", minutes=45
    )
    assert by_duration.status_code == 201, by_duration.text
    assert by_duration.json()["ended_at"].startswith("2026-10-28T10:45")
    by_end = await log(
        world,
        a,
        a.tech_a,
        item,
        worklog_type="travel",
        started_at="2026-10-28T12:00:00Z",
        ended_at="2026-10-28T13:30:00Z",
    )
    assert by_end.json()["minutes"] == 90
    await log(
        world,
        a,
        a.admin,
        item,
        owner_id=str(a.tech_c),
        worklog_type="fix",
        started_at="2026-10-28T14:00:00Z",
        minutes=15,
    )
    found = (await world.call("GET", f"{BASE}/{item['id']}/worklogs", a, a.tech_a)).json()
    assert found["minutes"] == 150
    assert {t["key"]: t["minutes"] for t in found["by_owner"]} == {
        str(a.tech_a): 135,
        str(a.tech_c): 15,
    }
    assert {t["key"]: t["minutes"] for t in found["by_type"]} == {"fix": 60, "travel": 90}
    # A new duration moves the end (AC2, the other way round).
    changed = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}/worklogs/{by_end.json()['id']}",
        a,
        a.tech_a,
        json={"minutes": 30},
        headers={"If-Match": '"1"'},
    )
    assert changed.json()["ended_at"].startswith("2026-10-28T12:30")
    assert "worklog" in fields(await world.history(a, item))


# --- links (REQ-INC-084) --------------------------------------------------------------------------


async def links(world: World, org: Org, user: uuid.UUID, item: dict[str, Any]) -> list[Any]:
    found = await world.call("GET", f"{BASE}/{item['id']}/links", org, user)
    assert found.status_code == 200, found.text
    return list(found.json())


async def test_req_inc_084_ac1_ac2_links_show_and_go_on_both_sides_with_history(
    world: World,
) -> None:
    a = world.a
    first = await world.create(a, a.admin, group_id=str(a.ga))
    second = await world.create(a, a.admin, group_id=str(a.ga))
    made = await world.call(
        "POST",
        f"{BASE}/{second['id']}/links",
        a,
        a.tech_a,
        json={"other_id": first["id"], "comment": "Same printer"},
    )
    assert made.status_code == 201, made.text
    on_first = await links(world, a, a.tech_a, first)
    on_second = await links(world, a, a.tech_a, second)
    assert [(link["other_id"], link["relation"]) for link in on_first] == [
        (second["id"], "related")
    ]
    assert on_second[0]["other_display_id"] == first["display_id"]
    for item in (first, second):  # AC1: history on both
        assert "link" in fields(await world.history(a, item))
    again = await world.call(
        "POST", f"{BASE}/{first['id']}/links", a, a.tech_a, json={"other_id": second["id"]}
    )
    assert field_codes(again) == {"other_id": "already_linked"}
    itself = await world.call(
        "POST", f"{BASE}/{first['id']}/links", a, a.tech_a, json={"other_id": first["id"]}
    )
    assert field_codes(itself) == {"other_id": "cannot_link_itself"}
    # AC2: removed from one side, gone from both, both histories say so.
    removed = await world.call(
        "DELETE",
        f"{BASE}/{first['id']}/links/{on_first[0]['id']}",
        a,
        a.tech_a,
        headers={"If-Match": '"1"'},
    )
    assert removed.status_code == 204, removed.text
    assert await links(world, a, a.tech_a, second) == []
    for item in (first, second):
        kinds = [e["kind"] for e in await world.history(a, item)]
        assert kinds[0] == "child_removed"


async def test_req_inc_084_ac3_a_link_to_a_record_you_cannot_see_hides_it(world: World) -> None:
    a = world.a
    mine = await world.create(a, a.admin, group_id=str(a.ga))
    theirs = await world.create(a, a.admin, group_id=str(a.gb), subject="Board pay rise")
    await world.call(
        "POST", f"{BASE}/{mine['id']}/links", a, a.admin, json={"other_id": theirs["id"]}
    )
    seen = await links(world, a, a.tech_a, mine)
    assert len(seen) == 1  # the link exists
    assert (seen[0]["other_id"], seen[0]["other_display_id"], seen[0]["other_subject"]) == (
        None,
        None,
        None,
    )
    # To make a link, both records must be visible.
    other = await world.create(a, a.admin, group_id=str(a.ga))
    refused = await world.call(
        "POST", f"{BASE}/{other['id']}/links", a, a.tech_a, json={"other_id": theirs["id"]}
    )
    assert field_codes(refused) == {"other_id": "record_not_found"}


# --- tenant isolation (CLAUDE.md rule a) ----------------------------------------------------------


async def test_new_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    item = await world.create(a, a.admin, group_id=str(a.ga))
    other = await world.create(a, a.admin, group_id=str(a.ga))
    await add_task(world, a, a.admin, item, title="T")
    await log(
        world, a, a.admin, item, worklog_type="fix", started_at="2026-10-28T10:00:00Z", minutes=5
    )
    await world.call(
        "POST", f"{BASE}/{item['id']}/links", a, a.admin, json={"other_id": other["id"]}
    )
    tables = ("work_item_tasks", "work_item_worklogs", "work_item_links")
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in tables:
            rows = (await session.execute(text(f"SELECT tenant_id FROM {table}"))).all()  # noqa: S608 - fixed names
            assert rows == [], table
            changed = await session.execute(text(f"UPDATE {table} SET version = version + 1"))  # noqa: S608 - fixed names
            assert changed.rowcount == 0, table
    foreign = await world.call("GET", f"{BASE}/{item['id']}/tasks", b, b.admin)
    assert problem(foreign) == (404, "work_item_not_found")
    for table in tables:
        rows = await world.sql(
            f"SELECT count(*) AS n FROM {table} WHERE tenant_id = $1",  # noqa: S608 - fixed names
            a.tenant,
        )
        assert rows[0]["n"] == 1, table
