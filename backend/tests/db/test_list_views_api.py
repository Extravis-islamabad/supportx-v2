"""Saved views, list settings and bulk jobs over HTTP (WP-020d; REQ-INC-104, 106, 110, 119, 120).

Real PostgreSQL, the incidents test world. Each test names the requirement and criterion.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.work_items.service.bulk import run_bulk_jobs
from tests.db.test_incidents_api import (
    BASE,
    Org,
    World,
    field_codes,
    ids,
    incidents_world,
    problem,
)
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(migrated_db) as built:
        yield built


async def save_view(world: World, org: Org, user: uuid.UUID, **body: Any) -> Any:  # noqa: ANN401 - JSON
    return await world.call("POST", f"{BASE}/saved-views", org, user, json=body)


async def bulk(
    world: World,
    org: Org,
    user: uuid.UUID,
    action: str,
    *,
    records: list[dict[str, Any]] | None = None,
    query: str = "",
    **changes: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    body: dict[str, Any] = {"action": action, "changes": changes}
    if records is None:
        body["all_matching"] = True
    else:
        body["record_ids"] = [r["id"] for r in records]
    started = await world.call("POST", f"{BASE}/bulk{query}", org, user, json=body)
    assert started.status_code == 202, started.text
    await run_bulk_jobs(world.app.state.db, world.app.state.settings)
    done = await world.call("GET", f"{BASE}/bulk-jobs/{started.json()['id']}", org, user)
    assert done.status_code == 200, done.text
    return dict(done.json())


# --- saved views (REQ-INC-106) --------------------------------------------------------------------


async def test_req_inc_106_ac1_ac3_saved_filter_is_the_list_filter(world: World) -> None:
    a = world.a
    p1 = await world.create(a, a.admin, group_id=str(a.ga))
    p2 = await world.create(a, a.admin, group_id=str(a.ga))
    old_p1 = await world.create(a, a.admin, group_id=str(a.ga))
    p3 = await world.create(a, a.admin, group_id=str(a.ga))
    for item, priority in ((p1, "p1"), (p2, "p2"), (old_p1, "p1"), (p3, "p3")):
        await world.sql(
            "UPDATE work_items SET priority = $1 WHERE id = $2", priority, uuid.UUID(item["id"])
        )
    await world.sql(
        "UPDATE work_items SET created_at = now() - interval '9 days' WHERE id = $1",
        uuid.UUID(old_p1["id"]),
    )
    tree = {
        "and": [
            {"field": "priority", "op": "in", "value": ["p1", "p2"]},
            {"field": "created_at", "op": "last_n_days", "value": 7},
        ]
    }
    saved = await save_view(world, a, a.tech_a, name="Urgent this week", filter=tree)
    assert saved.status_code == 201, saved.text
    assert saved.headers["ETag"] == '"1"'
    stored = saved.json()
    assert stored["filter"] == tree
    assert stored["mine"] is True
    # AC3: the stored filter, sent unchanged to the list API, returns the view's rows.
    query = "?filter=" + json.dumps(stored["filter"])
    assert await ids(world, a, a.tech_a, query) == {p1["id"], p2["id"]}  # AC1
    listed = (await world.call("GET", f"{BASE}/saved-views", a, a.tech_a)).json()
    assert [v["name"] for v in listed] == ["Urgent this week"]


async def test_req_inc_106_ac4_a_view_cannot_hold_a_filter_the_list_refuses(world: World) -> None:
    a = world.a
    wrong_op = {"field": "subject", "op": "last_n_days", "value": 7}
    refused = await save_view(world, a, a.tech_a, name="Broken", filter=wrong_op)
    assert refused.status_code == 422, refused.text
    unknown = await save_view(world, a, a.tech_a, name="Broken", sort="-nonsense")
    assert unknown.status_code == 422, unknown.text
    assert field_codes(await save_view(world, a, a.tech_a, name=" ")) == {"name": "required"}


async def test_private_and_shared_views_and_only_the_owner_changes_them(world: World) -> None:
    a = world.a
    mine = (await save_view(world, a, a.tech_a, name="Mine")).json()
    shared = (await save_view(world, a, a.tech_a, name="Team", visibility="shared")).json()
    seen = {
        v["name"]: v for v in (await world.call("GET", f"{BASE}/saved-views", a, a.tech_b)).json()
    }
    assert set(seen) == {"Team"}  # private views stay private
    assert seen["Team"]["mine"] is False
    # Only the owner changes a shared view; others are told why.
    denied = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{shared['id']}",
        a,
        a.tech_b,
        json={"name": "Hijacked"},
        headers={"If-Match": '"1"'},
    )
    assert problem(denied) == (403, "permission_denied")
    hidden = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{mine['id']}",
        a,
        a.tech_b,
        json={"name": "Peek"},
        headers={"If-Match": '"1"'},
    )
    assert problem(hidden) == (404, "work_item_view_not_found")
    renamed = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{mine['id']}",
        a,
        a.tech_a,
        json={"name": "Mine, renamed"},
        headers={"If-Match": '"1"'},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["version"] == 2
    stale = await world.call(
        "DELETE", f"{BASE}/saved-views/{mine['id']}", a, a.tech_a, headers={"If-Match": '"1"'}
    )
    assert stale.status_code == 409, stale.text
    removed = await world.call(
        "DELETE", f"{BASE}/saved-views/{mine['id']}", a, a.tech_a, headers={"If-Match": '"2"'}
    )
    assert removed.status_code == 204, removed.text
    duplicate = await save_view(world, a, a.tech_a, name="team")
    assert field_codes(duplicate) == {"name": "duplicate_name"}


# --- list settings (REQ-INC-104, 110) ------------------------------------------------------------


async def test_req_inc_104_ac1_ac3_columns_per_user_per_view(world: World) -> None:
    a = world.a
    path = f"{BASE}/list-settings/my_open"
    defaults = (await world.call("GET", path, a, a.tech_a)).json()
    assert defaults == {
        "view_key": "my_open",
        "columns": [],
        "sort": None,
        "page_size": 50,
        "version": None,
    }
    columns = [{"key": "display_id", "width": 120}, {"key": "custom.asset_tag", "width": None}]
    first = await world.call(
        "PUT",
        path,
        a,
        a.tech_a,
        json={"columns": columns, "sort": "-resolution_due_at", "page_size": 25},
    )
    assert first.status_code == 200, first.text
    assert first.headers["ETag"] == '"1"'
    # AC1: kept for that user (a reload reads it back) and nobody else.
    assert (await world.call("GET", path, a, a.tech_a)).json()["columns"] == columns
    assert (await world.call("GET", path, a, a.tech_b)).json()["version"] is None
    # AC3: another view keeps its own (default) columns.
    other = (await world.call("GET", f"{BASE}/list-settings/open", a, a.tech_a)).json()
    assert other["columns"] == []
    # A second save needs the version read.
    blind = await world.call("PUT", path, a, a.tech_a, json={"page_size": 100})
    assert problem(blind) == (428, "precondition_required")
    second = await world.call(
        "PUT", path, a, a.tech_a, json={"page_size": 100}, headers={"If-Match": '"1"'}
    )
    assert second.json()["page_size"] == 100
    assert field_codes(
        await world.call("PUT", f"{BASE}/list-settings/open", a, a.tech_a, json={"page_size": 30})
    ) == {"page_size": "invalid_choice"}
    bad_key = await world.call("GET", f"{BASE}/list-settings/nonsense", a, a.tech_a)
    assert bad_key.status_code == 422, bad_key.text


async def test_settings_of_a_saved_view_need_the_view(world: World) -> None:
    a = world.a
    view = (await save_view(world, a, a.tech_a, name="Mine")).json()
    key = f"custom:{view['id']}"
    saved = await world.call(
        "PUT", f"{BASE}/list-settings/{key}", a, a.tech_a, json={"page_size": 25}
    )
    assert saved.status_code == 200, saved.text
    foreign = await world.call(
        "PUT", f"{BASE}/list-settings/{key}", a, a.tech_b, json={"page_size": 25}
    )
    assert problem(foreign) == (404, "work_item_view_not_found")


# --- bulk jobs (REQ-INC-119, 120) -----------------------------------------------------------------


async def test_req_inc_120_ac1_ac4_bulk_close_skips_records_without_a_closure_code(
    world: World,
) -> None:
    a = world.a
    items = [await world.create(a, a.admin, group_id=str(a.ga)) for _ in range(5)]
    for item in items:
        resolved = await world.act(a, a.admin, item, "resolve", resolution="<p>Fixed</p>")
        assert resolved.status_code == 200, resolved.text
    coded = items[:3]
    for item in coded:
        await world.sql(
            "UPDATE work_items SET closure_code = 'fixed' WHERE id = $1", uuid.UUID(item["id"])
        )
    job = await bulk(world, a, a.admin, "close", records=items)
    assert (job["status"], job["total"], job["done_count"], job["skipped_count"]) == (
        "done",
        5,
        3,
        2,
    )
    skipped = {r["id"]: r for r in job["results"] if r["outcome"] == "skipped"}
    assert set(skipped) == {items[3]["id"], items[4]["id"]}
    assert {(r["field"], r["code"]) for r in skipped.values()} == {("closure_code", "required")}
    assert all(r["display_id"] for r in job["results"])
    for item in coded:  # AC4: each closed record's history names the job
        history = await world.history(a, item)
        assert history[0]["kind"] == "status"
        assert history[0]["bulk_job_id"] == job["id"]
    assert (await world.get(a, a.admin, items[3])).json()["status_category"] == "resolved"


async def test_req_inc_120_ac2_bulk_edit_changes_only_the_sent_fields(world: World) -> None:
    a = world.a
    first = await world.create(a, a.admin, group_id=str(a.ga), tags=["vpn"])
    second = await world.create(a, a.admin, group_id=str(a.ga), tags=["mail"])
    job = await bulk(world, a, a.admin, "edit", records=[first, second], subject="Outage")
    assert job["done_count"] == 2, job
    after = [(await world.get(a, a.admin, i)).json() for i in (first, second)]
    assert [x["subject"] for x in after] == ["Outage", "Outage"]
    assert [x["tags"] for x in after] == [["vpn"], ["mail"]]  # untouched
    nothing = await world.call(
        "POST", f"{BASE}/bulk", a, a.admin, json={"action": "edit", "record_ids": [first["id"]]}
    )
    assert field_codes(nothing) == {"changes": "required"}


async def test_req_inc_119_ac1_select_all_takes_every_matching_record_frozen(world: World) -> None:
    a = world.a
    group = [await world.create(a, a.admin, group_id=str(a.ga)) for _ in range(3)]
    elsewhere = await world.create(a, a.admin, group_id=str(a.gb))
    tree = json.dumps({"field": "group_id", "op": "eq", "value": str(a.ga)})
    job = await bulk(world, a, a.tech_a, "take", query=f"?view=open&filter={tree}")
    assert job["total"] == 3, job
    assert {r["id"] for r in job["results"]} == {g["id"] for g in group}
    assert (await world.get(a, a.admin, elsewhere)).json()["technician_id"] is None
    for item in group:
        assert (await world.get(a, a.admin, item)).json()["technician_id"] == str(a.tech_a)


async def test_bulk_runs_as_the_requester_and_skips_what_they_cannot_change(world: World) -> None:
    a = world.a
    theirs = await world.create(a, a.admin, group_id=str(a.gb))  # outside tech_a's scope
    mine = await world.create(a, a.admin, group_id=str(a.ga))
    job = await bulk(world, a, a.tech_a, "edit", records=[theirs, mine], subject="Changed")
    outcomes = {r["id"]: (r["outcome"], r.get("code")) for r in job["results"]}
    assert outcomes[mine["id"]] == ("done", None)
    assert outcomes[theirs["id"]][0] == "skipped"
    assert (await world.get(a, a.admin, theirs)).json()["subject"] == "Mail is down"
    # The job is the requester's own: nobody else reads it.
    other = await world.call("GET", f"{BASE}/bulk-jobs/{job['id']}", a, a.tech_b)
    assert problem(other) == (404, "bulk_job_not_found")
    latest = (await world.call("GET", f"{BASE}/bulk-jobs", a, a.tech_a)).json()
    assert [j["id"] for j in latest] == [job["id"]]
    assert latest[0]["results"] == []  # the list leaves the per-record results out


async def test_bulk_refuses_more_than_a_thousand_and_empty_selections(world: World) -> None:
    a = world.a
    too_many = await world.call(
        "POST",
        f"{BASE}/bulk",
        a,
        a.admin,
        json={"action": "take", "record_ids": [str(uuid.uuid4()) for _ in range(1001)]},
    )
    assert too_many.status_code == 422, too_many.text
    empty = await world.call(
        "POST", f"{BASE}/bulk", a, a.admin, json={"action": "take", "record_ids": []}
    )
    assert field_codes(empty) == {"records": "required"}


# --- tenant isolation (CLAUDE.md rule a) ----------------------------------------------------------


async def test_new_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    view = (await save_view(world, a, a.tech_a, name="Mine", visibility="shared")).json()
    await world.call("PUT", f"{BASE}/list-settings/open", a, a.tech_a, json={"page_size": 25})
    item = await world.create(a, a.admin, group_id=str(a.ga))
    await bulk(world, a, a.admin, "take", records=[item])
    tables = ("work_item_views", "work_item_list_settings", "work_item_bulk_jobs")
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in tables:
            rows = (await session.execute(text(f"SELECT tenant_id FROM {table}"))).all()  # noqa: S608 - fixed names
            assert rows == [], table
            changed = await session.execute(text(f"UPDATE {table} SET version = version + 1"))  # noqa: S608 - fixed names
            assert changed.rowcount == 0, table
    # Tenant B's people do not see tenant A's shared view.
    assert (await world.call("GET", f"{BASE}/saved-views", b, b.admin)).json() == []
    foreign = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{view['id']}",
        b,
        b.admin,
        json={"name": "x"},
        headers={"If-Match": '"1"'},
    )
    assert problem(foreign) == (404, "work_item_view_not_found")
    for table in tables:
        rows = await world.sql(
            f"SELECT count(*) AS n FROM {table} WHERE tenant_id = $1",  # noqa: S608 - fixed names
            a.tenant,
        )
        assert rows[0]["n"] == 1, table
