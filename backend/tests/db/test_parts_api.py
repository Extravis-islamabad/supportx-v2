"""Tasks, worklogs and links over HTTP (WP-020e; REQ-INC-067, 072, 084).

Real PostgreSQL, the incidents test world. Each test names the requirement and criterion.
"""

import json
import uuid
from datetime import datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, Org, World, field_codes, problem

pytestmark = [pytest.mark.db, pytest.mark.valkey, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, used by name


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


async def test_part_changed_carries_the_tasks_status_for_waiting_workflows(world: World) -> None:
    """WP-048b (lane C's task node): part.changed says the task's status after the change."""
    a = world.a
    item = await world.create(a, a.admin)
    made = (await add_task(world, a, a.admin, item, title="Swap the printer")).json()
    path = f"{BASE}/{item['id']}/tasks/{made['id']}"
    done = await world.call(
        "PATCH", path, a, a.admin, json={"status": "done"}, headers={"If-Match": '"1"'}
    )
    assert done.status_code == 200, done.text
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND envelope->>'event_type' = 'work_items.part.changed' ORDER BY id",
        a.tenant,
    )
    statuses = [
        json.loads(r["envelope"])["payload"].get("task_status")
        if isinstance(r["envelope"], str)
        else r["envelope"]["payload"].get("task_status")
        for r in rows
    ]
    assert statuses[-2:] == ["open", "done"]


# --- time analysis (WP-046a S3, REQ-INC-071) ---------------------------------------------------


async def _line(
    world: World, org: Org, item: dict[str, Any], move: tuple[str, str], at: str
) -> None:
    """Put the history line of one status move at `at` (the test's clock), tenant explicit."""
    await world.sql(
        "UPDATE field_changes SET occurred_at = $5::timestamptz"
        " WHERE tenant_id = $1 AND record_id = $2 AND field = 'status'"
        " AND old_value = to_jsonb($3::text) AND new_value = to_jsonb($4::text)",
        org.tenant,
        uuid.UUID(item["id"]),
        *move,
        datetime.fromisoformat(at),
    )


async def test_req_inc_071_time_per_status_paused_and_reopen_keeps_time(world: World) -> None:
    """AC1 two hours in progress and one paused; AC2 says which hours; AC3 reopen adds time."""
    a = world.a
    item = await world.create(a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga))
    started = await world.act(a, a.tech_a, item, "start_work")
    assert started.status_code == 200, started.text
    item = started.json()
    item = (await world.act(a, a.tech_a, item, "wait_requester", "more_information")).json()
    item = (await world.act(a, a.tech_a, item, "resume")).json()
    item = (await world.act(a, a.tech_a, item, "resolve")).json()
    reopened = await world.act(a, a.tech_a, item, "reopen", "not_fixed")
    assert reopened.status_code == 200, reopened.text
    # A Wednesday, as the test's clock: created 09:00, working 09-11, paused 11-12, working
    # 12-13, resolved 13-14, reopened at 14:00 and working since.
    await world.sql(
        "UPDATE work_items SET created_at = '2026-11-11T09:00:00Z'"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    for move, at in (
        (("assigned", "in_progress"), "2026-11-11T09:00:00Z"),
        (("in_progress", "awaiting_requester"), "2026-11-11T11:00:00Z"),
        (("awaiting_requester", "in_progress"), "2026-11-11T12:00:00Z"),
        (("in_progress", "resolved"), "2026-11-11T13:00:00Z"),
        (("resolved", "in_progress"), "2026-11-11T14:00:00Z"),
    ):
        await _line(world, a, item, move, at)
    # The creation's own lines (none -> new -> assigned) go to the start too: left at the real
    # time they would sort last and put the record back in "assigned" until now, which counts as
    # open but not in progress, inside business hours only (a CI flake at 17:42 UTC, #432).
    await world.sql(
        "UPDATE field_changes SET occurred_at = '2026-11-11T09:00:00Z'"
        " WHERE tenant_id = $1 AND record_id = $2 AND occurred_at > '2026-11-12T00:00:00Z'",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    found = await world.call("GET", f"{BASE}/{item['id']}/time-analysis", a, a.tech_a)
    assert found.status_code == 200, found.text
    body = found.json()
    by_status = {row["key"]: row["seconds"] for row in body["by_status"]}
    assert isinstance(body["business_hours"], bool)  # AC2: the screen says which
    assert by_status["awaiting_requester"] == 3600
    assert by_status["resolved"] == 3600
    assert body["paused_seconds"] == 3600
    # AC3: the three in-progress spells add up (09-11, 12-13, and 14:00 until now), never reset.
    assert by_status["in_progress"] >= 3 * 3600
    assert body["open_seconds"] == by_status["in_progress"] + 3600
    # Someone who cannot see the record gets nothing.
    hidden = await world.call("GET", f"{BASE}/{item['id']}/time-analysis", a, a.tech_b)
    assert hidden.status_code == 404, hidden.text
    # Requesters see none of it, not even on their own incident (the coordinator, #432).
    mine = await world.create(a, a.admin, requester_id=str(a.requester))
    refused = await world.call("GET", f"{BASE}/{mine['id']}/time-analysis", a, a.requester)
    assert refused.status_code in {403, 404}, refused.text
    assert "seconds" not in refused.text
    paths = world.app.openapi()["paths"]
    assert not [p for p in paths if p.startswith("/api/v1/portal") and "time" in p]


async def test_release_links_show_on_the_record_s_side_only(world: World) -> None:
    """Lane C's WP-058b: a record a release caused or started lists that release (labelled from
    its side); the release lists those itself, so its links tab stays as it was."""
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    release = await world.create(a, a.admin, group_id=str(a.ga))  # stands in for the release
    # Written as lane C's release flow writes it (no API here): superuser, tenant explicit.
    for kind in ("caused_by_release", "started_release"):
        await world.sql(
            "INSERT INTO work_item_links (id, tenant_id, source_id, target_id, kind)"
            " VALUES (gen_random_uuid(), $1, $2, $3, $4)",
            a.tenant,
            uuid.UUID(item["id"]),
            uuid.UUID(release["id"]),
            kind,
        )
    mine = await links(world, a, a.admin, item)
    assert sorted(link["relation"] for link in mine) == ["caused_by_release", "started_release"]
    assert {link["other_id"] for link in mine} == {release["id"]}
    assert await links(world, a, a.admin, release) == []
