"""Saved views, list settings and bulk jobs over HTTP (WP-020d; REQ-INC-104, 106, 110, 119, 120).

Real PostgreSQL, the incidents test world. Each test names the requirement and criterion.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.work_items.service.bulk import run_bulk_jobs
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, Org, World, field_codes, ids, problem

pytestmark = [pytest.mark.db, pytest.mark.valkey, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, used by name


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
    # D-176: sharing with everyone is for SDMs and admins (a technician gets 403, tested below).
    shared = (await save_view(world, a, a.admin, name="Team", visibility="everyone")).json()
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
    duplicate = await save_view(world, a, a.admin, name="team")  # names are unique per owner
    assert field_codes(duplicate) == {"name": "duplicate_name"}


async def test_d111_a_view_shared_with_groups_reaches_their_members_only(world: World) -> None:
    """D-111 as approved: private, chosen groups or everyone; only the owner edits."""
    a = world.a
    # tech_a is in GA only, tech_b in GB only, tech_c in both.
    made = await save_view(
        world, a, a.admin, name="Group A queue", visibility="groups", group_ids=[str(a.ga)]
    )
    assert made.status_code == 201, made.text
    assert made.json()["group_ids"] == [str(a.ga)]

    async def names(user: uuid.UUID) -> set[str]:
        found = await world.call("GET", f"{BASE}/saved-views", a, user)
        return {v["name"] for v in found.json()}

    assert "Group A queue" in await names(a.tech_a)
    assert "Group A queue" in await names(a.tech_c)
    assert "Group A queue" not in await names(a.tech_b)
    no_groups = await save_view(world, a, a.admin, name="Nobody", visibility="groups")
    assert field_codes(no_groups) == {"group_ids": "required"}
    unknown = await save_view(
        world, a, a.admin, name="Ghost", visibility="groups", group_ids=[str(uuid.uuid4())]
    )
    assert field_codes(unknown) == {"group_ids": "group_not_found"}
    member = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{made.json()['id']}",
        a,
        a.tech_a,
        json={"name": "Mine now"},
        headers={"If-Match": '"1"'},
    )
    assert problem(member) == (403, "permission_denied")
    # Back to private: the groups are dropped, members no longer see it.
    private = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{made.json()['id']}",
        a,
        a.admin,
        json={"visibility": "private"},
        headers={"If-Match": '"1"'},
    )
    assert private.json()["group_ids"] == []
    assert "Group A queue" not in await names(a.tech_a)


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
        "row_colour_by": None,  # REQ-INC-115: no choice of theirs, the tenant's default applies
        "layout": None,  # REQ-INC-111: the table
        "group_by": None,  # the board by status
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


async def test_bulk_never_names_a_record_the_person_cannot_see(world: World) -> None:
    """A record the person cannot see is refused as one that does not exist: same answer, no
    number, and no action run. One they see but may not change keeps its number and its own
    reason. Regression for 45a1d36f3 (2026-10-28), where skipped results named any record."""
    a = world.a
    mine = await world.create(a, a.admin, group_id=str(a.ga))
    theirs = await world.create(a, a.admin, group_id=str(a.gb))  # outside tech_a's scope
    closed = await world.create(a, a.admin, group_id=str(a.ga))
    resolved = await world.act(a, a.admin, closed, "resolve", resolution="<p>Fixed</p>")
    assert (await world.act(a, a.admin, resolved.json(), "close")).status_code == 200
    missing = {"id": str(uuid.uuid4())}  # a crafted ID: no such record
    job = await bulk(
        world, a, a.tech_a, "edit", records=[mine, theirs, missing, closed], subject="Changed"
    )
    by_id = {r["id"]: r for r in job["results"]}
    assert by_id[mine["id"]]["outcome"] == "done"
    unseen, gone = by_id[theirs["id"]], by_id[missing["id"]]
    assert (
        (unseen["outcome"], unseen["code"])
        == (gone["outcome"], gone["code"])
        == (
            "skipped",
            "work_item_not_found",
        )
    )
    assert unseen["display_id"] is None
    assert gone["display_id"] is None
    assert (await world.get(a, a.admin, theirs)).json()["subject"] == "Mail is down"
    # Seen but not changeable (closed): named, with its own reason.
    seen = by_id[closed["id"]]
    assert seen["outcome"] == "skipped"
    assert seen["display_id"] == closed["display_id"]
    assert seen["code"] != "work_item_not_found"


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
    view = (await save_view(world, a, a.admin, name="Mine", visibility="everyone")).json()
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


async def test_list_fields_name_every_field_the_list_takes(world: World) -> None:
    a = world.a
    found = await world.call("GET", f"{BASE}/list-fields", a, a.tech_a)
    assert found.status_code == 200, found.text
    fields = {f["name"]: f for f in found.json()}
    assert fields["resolution_due_at"]["sortable"] is True  # REQ-INC-104 AC2
    assert fields["priority"]["dimension"]["label_prefix"] == "priority"
    assert fields["group_id"]["dimension"]["reference"] == "group"


async def test_every_built_in_view_has_an_equivalent_filter_with_the_same_rows(
    world: World,
) -> None:
    """The export sends a view as a filter: each equivalent returns exactly the view's rows."""
    a = world.a
    mine = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    await world.create(a, a.admin)
    await world.create(a, a.admin, group_id=str(a.gb))
    resolved = await world.create(a, a.admin, group_id=str(a.ga))
    await world.act(a, a.admin, resolved, "resolve", resolution="<p>Done</p>")
    late = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    await world.sql(
        "UPDATE work_items SET resolution_due_at = now() - interval '1 hour' WHERE id = $1",
        uuid.UUID(late["id"]),
    )
    await world.call("PUT", f"{BASE}/{mine['id']}/followers/{a.tech_a}", a, a.tech_a)
    await world.sql("UPDATE users SET manager_id = $1 WHERE id = $2", a.tech_a, a.requester)
    found = await world.call("GET", f"{BASE}/view-filters", a, a.tech_a)
    assert found.status_code == 200, found.text
    views = {v["view"]: v for v in found.json()}
    assert views["updated_by_others"]["expressible"] is False
    for code, view in views.items():
        if not view["expressible"]:
            continue
        query = "" if view["filter"] is None else "?filter=" + json.dumps(view["filter"])
        as_view = await ids(world, a, a.tech_a, f"?view={code}")
        assert await ids(world, a, a.tech_a, query) == as_view, code


async def test_history_never_names_a_linked_record_the_reader_cannot_see(world: World) -> None:
    """A link's other record shows in history only for a reader who may see it: the line stays
    (linked, which kind), the number and ID do not. The admin, who sees both, gets the number."""
    a = world.a
    mine = await world.create(a, a.admin, group_id=str(a.ga))
    theirs = await world.create(a, a.admin, group_id=str(a.gb))  # outside tech_a's scope
    linked = await world.call(
        "POST",
        f"{BASE}/{mine['id']}/links",
        a,
        a.admin,
        json={"other_id": theirs["id"]},
    )
    assert linked.status_code == 201, linked.text

    async def link_values(user: uuid.UUID) -> list[Any]:
        shown = await world.call("GET", f"{BASE}/{mine['id']}/history", a, user)
        assert shown.status_code == 200, shown.text
        return [
            c["new"] for e in shown.json()["items"] for c in e["changes"] if c["field"] == "link"
        ]

    (hidden,) = await link_values(a.tech_a)
    assert hidden["display_id"] is None
    assert hidden["id"] is None
    assert hidden["hidden"] is True
    assert hidden["kind"] == "related"
    assert theirs["display_id"] not in str(hidden)
    (named,) = await link_values(a.admin)  # sees both: no over-masking
    assert named["display_id"] == theirs["display_id"]


# --- favourites (WP-046b S3a; REQ-INC-107 AC1) ----------------------------------------------------


async def test_req_inc_107_ac1_starred_views_come_first_and_are_personal(world: World) -> None:
    a = world.a
    shared = (await save_view(world, a, a.admin, name="A team", visibility="everyone")).json()
    mine = (await save_view(world, a, a.tech_a, name="Z mine")).json()
    star = f"{BASE}/saved-views/{mine['id']}/favourite"
    for _ in range(2):  # starring twice is the same as once
        assert (await world.call("PUT", star, a, a.tech_a)).status_code == 204
    listed = (await world.call("GET", f"{BASE}/saved-views", a, a.tech_a)).json()
    assert [(v["name"], v["favourite"]) for v in listed] == [("Z mine", True), ("A team", False)]
    # Someone else sees the shared view unstarred: a star is the starrer's only.
    others = (await world.call("GET", f"{BASE}/saved-views", a, a.tech_b)).json()
    assert [(v["name"], v["favourite"]) for v in others] == [("A team", False)]
    # A view they may not use cannot be starred (and nothing says it exists).
    hidden = await world.call("PUT", star, a, a.tech_b)
    assert hidden.status_code == 404, hidden.text
    # Un-starring, twice, is fine; the order goes back to by name.
    for _ in range(2):
        assert (await world.call("DELETE", star, a, a.tech_a)).status_code == 204
    listed = (await world.call("GET", f"{BASE}/saved-views", a, a.tech_a)).json()
    assert [v["name"] for v in listed] == ["A team", "Z mine"]
    # A starred view later unshared from them drops out of their picker, star and all.
    assert (
        await world.call("PUT", f"{BASE}/saved-views/{shared['id']}/favourite", a, a.tech_b)
    ).status_code == 204
    gone = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{shared['id']}",
        a,
        a.admin,
        json={"visibility": "private"},
        headers={"If-Match": f'"{shared["version"]}"'},
    )
    assert gone.status_code == 200, gone.text
    assert (await world.call("GET", f"{BASE}/saved-views", a, a.tech_b)).json() == []


async def test_favourites_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    view = (await save_view(world, a, a.tech_a, name="Starred")).json()
    put = await world.call("PUT", f"{BASE}/saved-views/{view['id']}/favourite", a, a.tech_a)
    assert put.status_code == 204, put.text
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        rows = (
            await session.execute(text("SELECT tenant_id FROM work_item_view_favourites"))
        ).all()
        assert rows == []
        gone = await session.execute(text("DELETE FROM work_item_view_favourites"))
        assert gone.rowcount == 0
    foreign = await world.call("PUT", f"{BASE}/saved-views/{view['id']}/favourite", b, b.admin)
    assert foreign.status_code == 404, foreign.text


# --- unread markers (WP-046b S3a; REQ-INC-115 AC2) ------------------------------------------------


async def _unread(world: World, org: Org, user: uuid.UUID) -> set[str]:
    page = await world.call("GET", f"{BASE}?limit=100", org, user)
    assert page.status_code == 200, page.text
    return set(page.json()["unread"])


async def test_req_inc_115_ac2_a_public_reply_marks_it_unread_for_the_assignee(
    world: World,
) -> None:
    from tests.db.test_conversation_api import say  # noqa: PLC0415 - its own test module

    a = world.a
    assigned = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    other = await world.create(a, a.admin, group_id=str(a.ga))  # not theirs, never opened
    assert assigned["id"] in await _unread(world, a, a.tech_a)  # assigned by someone else
    assert other["id"] not in await _unread(world, a, a.tech_a)
    read = f"{BASE}/{assigned['id']}/read"
    assert (await world.call("POST", read, a, a.tech_a)).status_code == 204
    assert assigned["id"] not in await _unread(world, a, a.tech_a)
    # AC2: someone else's public reply marks it unread again, until they open it.
    replied = await say(world, a, a.admin, assigned, kind="reply")
    assert replied.status_code == 201, replied.text
    assert assigned["id"] in await _unread(world, a, a.tech_a)
    assert (await world.call("POST", read, a, a.tech_a)).status_code == 204
    # Their own reply and their own private note leave it read.
    assert (await say(world, a, a.tech_a, assigned, kind="reply")).status_code == 201
    assert (await say(world, a, a.tech_a, assigned)).status_code == 201
    assert assigned["id"] not in await _unread(world, a, a.tech_a)
    # Someone else's change to the record itself marks it unread too.
    fresh = await world.fresh(a, assigned)
    changed = await world.call(
        "PATCH",
        f"{BASE}/{assigned['id']}",
        a,
        a.admin,
        json={"subject": "Mail is down again"},
        headers={"If-Match": f'"{fresh["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    assert assigned["id"] in await _unread(world, a, a.tech_a)
    # Personal: the admin's own list is untouched by what tech_a has read.
    assert assigned["id"] not in await _unread(world, a, a.admin)


async def test_marking_read_needs_sight_of_the_record_and_is_isolated_by_rls(
    world: World,
) -> None:
    a, b = world.a, world.b
    theirs = await world.create(a, a.admin, group_id=str(a.gb))  # outside tech_a's scope
    hidden = await world.call("POST", f"{BASE}/{theirs['id']}/read", a, a.tech_a)
    assert hidden.status_code == 404, hidden.text
    assert (await world.call("POST", f"{BASE}/{theirs['id']}/read", a, a.admin)).status_code == 204
    foreign = await world.call("POST", f"{BASE}/{theirs['id']}/read", b, b.admin)
    assert foreign.status_code == 404, foreign.text
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        rows = (await session.execute(text("SELECT tenant_id FROM work_item_reads"))).all()
        assert rows == []
        changed = await session.execute(text("UPDATE work_item_reads SET seen_version = 0"))
        assert changed.rowcount == 0


# --- D-176: field access decides on every read (lane C's condition 1) -----------------------------


async def test_a_shared_view_on_a_field_later_hidden_from_a_reader_is_gone_for_them_only(
    world: World,
) -> None:
    from tests.db.test_incidents_api import CONSOLE  # noqa: PLC0415 - the console header

    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Salary band"}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    field = f"custom.{made.json()['key']}"
    view = (
        await save_view(
            world,
            a,
            a.admin,
            name="Band B",
            visibility="everyone",
            filter={"field": field, "op": "eq", "value": "B"},
        )
    ).json()
    star = f"{BASE}/saved-views/{view['id']}/favourite"
    assert (await world.call("PUT", star, a, a.tech_b)).status_code == 204

    async def names(user: uuid.UUID) -> list[str]:
        shown = await world.call("GET", f"{BASE}/saved-views", a, user)
        return [v["name"] for v in shown.json()]

    assert await names(a.tech_b) == ["Band B"]
    # The field is now hidden from the technician role (tech_a's and tech_b's).
    await world.sql(
        "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
        " SELECT gen_random_uuid(), $1, id, 'incident', $2, 'hidden' FROM roles"
        " WHERE tenant_id = $1 AND key = 'technician'",
        a.tenant,
        field,
    )
    client = world.app.state.policy.cache.client
    prefix = world.app.state.settings.valkey_key_prefix
    stale = [k async for k in client.scan_iter(match=f"{prefix}*")]
    if stale:
        await client.delete(*stale)
    assert await names(a.tech_b) == []  # not listed for them
    # By ID (every by-ID read goes through the same view()): the 404 of a missing view.
    assert (await world.call("PUT", star, a, a.tech_b)).status_code == 404
    assert await names(a.tech_a) == []
    # The lead also holds a custom role with no rule (the clearest wins): it is still theirs.
    assert await names(a.lead) == ["Band B"]
    assert await names(a.admin) == ["Band B"]  # the owner keeps their own view


# --- D-176: who may share with whom ---------------------------------------------------------------


def _refused(response: Any, audience: str) -> None:  # noqa: ANN401 - an httpx response
    assert problem(response) == (403, "view_share_not_allowed"), response.text
    assert response.json()["params"]["audience"] == audience


async def test_d176_a_technician_shares_with_their_own_groups_only(world: World) -> None:
    a = world.a
    own = await save_view(
        world, a, a.tech_a, name="GA queue", visibility="groups", group_ids=[str(a.ga)]
    )
    assert own.status_code == 201, own.text
    _refused(
        await save_view(world, a, a.tech_a, name="GB", visibility="groups", group_ids=[str(a.gb)]),
        "groups",
    )
    _refused(await save_view(world, a, a.tech_a, name="All", visibility="everyone"), "everyone")
    # Widening on edit needs the right too; an edit keeping the audience does not.
    view = own.json()
    widened = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{view['id']}",
        a,
        a.tech_a,
        json={"group_ids": [str(a.ga), str(a.gb)]},
        headers={"If-Match": f'"{view["version"]}"'},
    )
    _refused(widened, "groups")
    renamed = await world.call(
        "PATCH",
        f"{BASE}/saved-views/{view['id']}",
        a,
        a.tech_a,
        json={"name": "GA queue, renamed"},
        headers={"If-Match": f'"{view["version"]}"'},
    )
    assert renamed.status_code == 200, renamed.text
    # Requesters hold neither right (nor the list): no view of theirs is ever shared.
    asked = await save_view(world, a, a.requester, name="Mine", visibility="groups")
    assert asked.status_code == 403, asked.text


async def test_d176_a_team_lead_shares_with_the_groups_they_lead_never_everyone(
    world: World,
) -> None:
    from tests.db.test_incidents_api import role, unit  # noqa: PLC0415 - the world's helpers

    a = world.a
    # tech_a (a member of GA) leads GB through a team-lead-like role: share_views_wide at group.
    lead_role = await role(world, a, "Desk lead", [("incidents.share_views_wide", "group")])
    put = await world.call("PUT", f"/users/{a.tech_a}/roles/{lead_role}", a, a.admin)
    assert put.status_code == 204, put.text
    await world.sql(
        "UPDATE support_groups SET lead_id = $1 WHERE tenant_id = $2 AND id = $3",
        a.tech_a,
        a.tenant,
        a.gb,
    )
    elsewhere = await unit(world, a, "groups", "Neither", [a.tech_b])
    led = await save_view(world, a, a.tech_a, name="GB", visibility="groups", group_ids=[str(a.gb)])
    assert led.status_code == 201, led.text  # a group they lead, though not a member of
    member = await save_view(
        world, a, a.tech_a, name="GA", visibility="groups", group_ids=[str(a.ga)]
    )
    assert member.status_code == 201, member.text  # a group they're in, though not leading it
    _refused(
        await save_view(
            world, a, a.tech_a, name="Neither", visibility="groups", group_ids=[str(elsewhere)]
        ),
        "groups",
    )
    _refused(await save_view(world, a, a.tech_a, name="All", visibility="everyone"), "everyone")


async def test_d176_a_service_desk_manager_shares_with_everyone(world: World) -> None:
    from tests.db.test_incidents_api import role  # noqa: PLC0415 - the world's helper

    a = world.a
    manager = await role(world, a, "Desk manager", [("incidents.share_views_wide", "all")])
    put = await world.call("PUT", f"/users/{a.tech_b}/roles/{manager}", a, a.admin)
    assert put.status_code == 204, put.text
    everyone = await save_view(world, a, a.tech_b, name="All", visibility="everyone")
    assert everyone.status_code == 201, everyone.text
    other = await save_view(
        world, a, a.tech_b, name="GA", visibility="groups", group_ids=[str(a.ga)]
    )
    assert other.status_code == 201, other.text


async def test_d176_a_filter_on_a_restricted_field_keeps_a_view_private(world: World) -> None:
    from tests.db.test_incidents_api import CONSOLE  # noqa: PLC0415 - the console header

    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Band"}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    field = f"custom.{made.json()['key']}"
    await world.sql(
        "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
        " SELECT gen_random_uuid(), $1, id, 'incident', $2, 'masked' FROM roles"
        " WHERE tenant_id = $1 AND key = 'technician'",
        a.tenant,
        field,
    )
    tree = {"field": field, "op": "eq", "value": "B"}
    refused = await save_view(world, a, a.admin, name="Band", visibility="everyone", filter=tree)
    assert field_codes(refused) == {"filter": "view_filter_not_shareable"}
    assert refused.json()["errors"][0]["params"] == {"field": field, "audience": "everyone"}
    private = await save_view(world, a, a.admin, name="Band", filter=tree)
    assert private.status_code == 201, private.text  # their own: fine
    # No over-masking: a plain field's view is shared as before.
    plain = await save_view(
        world,
        a,
        a.admin,
        name="Urgent",
        visibility="everyone",
        filter={"field": "priority", "op": "eq", "value": "p1"},
    )
    assert plain.status_code == 201, plain.text


# --- D-176: the shared-view audit -----------------------------------------------------------------


async def test_d176_hidden_before_the_audit_then_made_private_once_with_its_effects(
    world: World,
) -> None:
    """The coordinator's condition 3: the read hides it before the job runs; then the job makes
    it private (history, events, stars gone, report), and a second run changes nothing."""
    from app.modules.work_items.service import view_audit  # noqa: PLC0415 - the job under test
    from tests.db.test_conversation_api import events_of  # noqa: PLC0415 - the outbox helper
    from tests.db.test_incidents_api import CONSOLE  # noqa: PLC0415 - the console header

    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Grade"}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    field = f"custom.{made.json()['key']}"
    view = (
        await save_view(
            world,
            a,
            a.admin,
            name="Grade C",
            visibility="everyone",
            filter={"field": field, "op": "eq", "value": "C"},
        )
    ).json()
    star = f"{BASE}/saved-views/{view['id']}/favourite"
    assert (await world.call("PUT", star, a, a.tech_b)).status_code == 204
    await world.sql(
        "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
        " SELECT gen_random_uuid(), $1, id, 'incident', $2, 'hidden' FROM roles"
        " WHERE tenant_id = $1 AND key = 'technician'",
        a.tenant,
        field,
    )
    client = world.app.state.policy.cache.client
    prefix = world.app.state.settings.valkey_key_prefix
    stale = [k async for k in client.scan_iter(match=f"{prefix}*")]
    if stale:
        await client.delete(*stale)

    async def listed(user: uuid.UUID) -> list[dict[str, Any]]:
        shown = await world.call("GET", f"{BASE}/saved-views", a, user)
        return [v for v in shown.json() if v["id"] == view["id"]]

    # Before the job: still shared in storage, yet the recipient never gets it.
    (stored,) = await world.sql(
        "SELECT visibility FROM work_item_views WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(view["id"]),
    )
    assert stored["visibility"] == "everyone"
    assert await listed(a.tech_b) == []
    # The job: private to its owner, once.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        done = await view_audit.audit_all(session)
    assert [(str(d.view_id), d.field_key, d.reason) for d in done] == [
        (view["id"], field, "restricted_field")
    ]
    (mine,) = await listed(a.admin)
    assert mine["visibility"] == "private"
    assert mine["version"] == view["version"] + 1
    stars = await world.sql(
        "SELECT 1 FROM work_item_view_favourites WHERE tenant_id = $1 AND view_id = $2",
        a.tenant,
        uuid.UUID(view["id"]),
    )
    assert stars == []  # tech_b's star went with it
    unshared = [
        e
        for e in await events_of(world, "work_item_view")
        if e.event_type == "work_items.view.unshared"
    ]
    assert [e.payload["field_key"] for e in unshared] == [field]
    assert "Grade" not in json.dumps([e.payload for e in unshared])  # IDs and codes only
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await view_audit.audit_all(session) == []  # idempotent
    # The administrators' report, theirs only.
    report = await world.call("GET", f"{BASE}/saved-views/audit", a, a.admin)
    assert report.status_code == 200, report.text
    assert [(i["id"], i["field"]) for i in report.json()["items"]] == [(view["id"], field)]
    assert (await world.call("GET", f"{BASE}/saved-views/audit", a, a.tech_a)).status_code == 403
    rerun = await world.call(
        "POST",
        f"{BASE}/saved-views/audit",
        a,
        a.admin,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert rerun.status_code == 200, rerun.text
    assert len(rerun.json()["items"]) == 1  # nothing more changed


# --- row colours (REQ-INC-115 AC1) ----------------------------------------------------------------


async def test_req_inc_115_ac1_a_tenant_default_and_a_personal_choice_per_view(
    world: World,
) -> None:
    a = world.a
    path = f"{BASE}/settings/list-display"
    shown = await world.call("GET", path, a, a.tech_a)
    assert shown.status_code == 200, shown.text
    assert shown.json()["row_colour_by"] == "none"
    version = shown.json()["settings_version"]
    refused = await world.call(
        "PUT",
        path,
        a,
        a.tech_a,
        json={"row_colour_by": "priority"},
        headers={"If-Match": f'"{version}"'},
    )
    assert refused.status_code == 403, refused.text
    stale = await world.call(
        "PUT",
        path,
        a,
        a.admin,
        json={"row_colour_by": "priority"},
        headers={"If-Match": f'"{version + 7}"'},
    )
    assert stale.status_code == 409, stale.text
    put = await world.call(
        "PUT",
        path,
        a,
        a.admin,
        json={"row_colour_by": "priority"},
        headers={"If-Match": f'"{version}"'},
    )
    assert put.status_code == 200, put.text
    assert (await world.call("GET", path, a, a.tech_a)).json()["row_colour_by"] == "priority"
    # A person's own choice for one view; a value outside the three is refused.
    mine = await world.call(
        "PUT", f"{BASE}/list-settings/open", a, a.tech_a, json={"row_colour_by": "status"}
    )
    assert mine.status_code == 200, mine.text
    assert mine.json()["row_colour_by"] == "status"
    wrong = await world.call(
        "PUT",
        f"{BASE}/list-settings/open",
        a,
        a.tech_a,
        json={"row_colour_by": "rainbow"},
        headers={"If-Match": f'"{mine.json()["version"]}"'},
    )
    assert wrong.status_code == 422, wrong.text


async def test_d176_a_sealed_field_keeps_views_private_hidden_and_audited_as_sealed(
    world: World,
) -> None:
    """Lane C's #549 review: the sealed path (ADR-050), not only role rules."""
    from app.modules.work_items.service import view_audit  # noqa: PLC0415 - the job under test
    from tests.db.test_incidents_api import CONSOLE  # noqa: PLC0415 - the console header

    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Passport"}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    key = made.json()["key"]
    field = f"custom.{key}"
    tree = {"field": field, "op": "eq", "value": "X1"}
    # Shared while the field was plain.
    before = await save_view(
        world, a, a.admin, name="Passports", visibility="everyone", filter=tree
    )
    assert before.status_code == 201, before.text
    view = before.json()
    await world.sql(
        "UPDATE custom_fields SET sensitive = true, seal_state = 'sealed'"
        " WHERE tenant_id = $1 AND entity = 'incident' AND key = $2",
        a.tenant,
        key,
    )
    client = world.app.state.policy.cache.client
    prefix = world.app.state.settings.valkey_key_prefix
    stale = [k async for k in client.scan_iter(match=f"{prefix}*")]
    if stale:
        await client.delete(*stale)
    # Sharing a new one on it is refused, naming the field.
    refused = await save_view(world, a, a.admin, name="More", visibility="everyone", filter=tree)
    assert field_codes(refused) == {"filter": "view_filter_not_shareable"}
    assert refused.json()["errors"][0]["params"] == {"field": field, "audience": "everyone"}

    async def names(user: uuid.UUID) -> list[str]:
        shown = await world.call("GET", f"{BASE}/saved-views", a, user)
        return [v["name"] for v in shown.json()]

    # The one shared before: gone for everyone else, still the owner's.
    assert "Passports" not in await names(a.tech_b)
    assert "Passports" not in await names(a.lead)
    assert "Passports" in await names(a.admin)
    import structlog  # noqa: PLC0415 - the log capture, here only

    with structlog.testing.capture_logs() as logs:
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            done = await view_audit.audit_all(session)
    assert [(str(d.view_id), d.field_key, d.reason) for d in done] == [
        (view["id"], field, "sealed_field")
    ]
    # No field keys in this world: the unsharing happened, the sealing waits (the coordinator):
    # the view stays pending, the report counts it, and one log line names it by ID, no value.
    pending = [e for e in logs if e.get("event") == "view_filters_seal_pending"]
    assert len(pending) == 1
    assert pending[0]["view_ids"] == [view["id"]]
    assert "X1" not in str(pending[0])
    report = await world.call("GET", f"{BASE}/saved-views/audit", a, a.admin)
    assert report.json()["seal_pending"] == 1


async def test_d176_the_owner_is_told_and_the_audit_runs_on_its_own(world: World) -> None:
    """The view audit's other ways in: the owner's notice (only theirs, the field by its name),
    the field-rule consumer and the schedule (the same idempotent run)."""
    from app.modules.work_items.service import view_audit  # noqa: PLC0415 - the job under test
    from tests.db.test_conversation_api import events_of  # noqa: PLC0415 - the outbox helper
    from tests.db.test_incidents_api import CONSOLE  # noqa: PLC0415 - the console header

    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Region code"}},
        headers=CONSOLE,
    )
    field = f"custom.{made.json()['key']}"
    view = (
        await save_view(
            world,
            a,
            a.admin,
            name="Regional",
            visibility="everyone",
            filter={"field": field, "op": "eq", "value": "R7"},
        )
    ).json()
    await world.sql(
        "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
        " SELECT gen_random_uuid(), $1, id, 'incident', $2, 'hidden' FROM roles"
        " WHERE tenant_id = $1 AND key = 'technician'",
        a.tenant,
        field,
    )
    # The consumer (a field rule changed) runs the audit; without a session it does nothing.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        envelope = None
        await view_audit.on_field_access_changed(envelope, None)  # type: ignore[arg-type]  # the no-session path
        await view_audit.on_field_access_changed(envelope, session)  # type: ignore[arg-type]  # payload unused
    (notice,) = [
        e
        for e in await events_of(world, "work_item_view")
        if e.event_type == "work_items.view.unshared" and e.payload["view_id"] == view["id"]
    ]
    source = view_audit.SOURCE
    assert source.events_for(notice) == (view_audit.UNSHARED,)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        context = await source.context(session, view_audit.UNSHARED, notice)
        assert context is not None
        assert context.relatives[view_audit.OWNER] == frozenset({uuid.UUID(view["owner_id"])})
        assert context.variables["record.title"] == "Regional"
        assert "R7" not in str(context.variables)  # the field by its name, never the value
        mine = await source.access(session, uuid.UUID(view["owner_id"]), uuid.UUID(view["id"]))
        theirs = await source.access(session, a.tech_b, uuid.UUID(view["id"]))
    assert mine.value == "full"
    assert theirs.value == "none"
    # The schedule: every tenant, the same run; nothing left to change, so nothing changes.
    await view_audit.audit_schedule(world.app.state.db, world.app.state.settings)
    (row,) = await world.sql(
        "SELECT visibility, version FROM work_item_views WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(view["id"]),
    )
    assert row["visibility"] == "private"


async def test_req_inc_111_the_layout_and_board_columns_are_kept_per_person_and_view(
    world: World,
) -> None:
    """WP-046b S3b (0182): table, cards or board, and the board's columns, are the person's own."""
    a = world.a
    path = f"{BASE}/list-settings/open"
    first = await world.call(
        "PUT", path, a, a.tech_a, json={"page_size": 25, "layout": "board", "group_by": "priority"}
    )
    assert first.status_code == 200, first.text
    assert (first.json()["layout"], first.json()["group_by"]) == ("board", "priority")
    shown = (await world.call("GET", path, a, a.tech_a)).json()
    assert (shown["layout"], shown["group_by"]) == ("board", "priority")
    # Another person, and another view, keep their own (the table).
    assert (await world.call("GET", path, a, a.tech_b)).json()["layout"] is None
    other = await world.call("GET", f"{BASE}/list-settings/my_open", a, a.tech_a)
    assert other.json()["layout"] is None
    # Only the known codes (the schema refuses the rest; nothing is echoed).
    bad = await world.call(
        "PUT",
        path,
        a,
        a.tech_a,
        json={"page_size": 25, "layout": "kanban", "group_by": "site"},
        headers={"If-Match": f'"{first.json()["version"]}"'},
    )
    assert set(field_codes(bad)) == {"layout", "group_by"}
    assert "kanban" not in bad.text
    # Back to the table (null) with the version read.
    back = await world.call(
        "PUT",
        path,
        a,
        a.tech_a,
        json={"page_size": 25, "layout": None, "group_by": None},
        headers={"If-Match": f'"{first.json()["version"]}"'},
    )
    assert back.status_code == 200, back.text
    assert back.json()["layout"] is None
