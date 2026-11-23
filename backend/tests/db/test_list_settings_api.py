"""The shared list-settings store over HTTP (WP-049b s4a; 0140; REQ-AST-047, REQ-INC-104/106/107).

The asset list is the first registered list (`assets`): widths per person and view, saved views
with the list's own filter, favourites, If-Match, the outbox event, and isolation by person and
by tenant (RLS, rule 5a).
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db import test_incidents_api
from tests.db.test_asset_financials_api import _events
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _match, _new

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/list-settings/assets"
WIDTHS = {"columns": [{"key": "name", "width": 260}, {"key": "tag"}], "page_size": 50}


async def _put(
    world: World,
    org: Org,
    user: uuid.UUID,
    key: str,
    body: dict[str, Any],
    version: int | None = None,
) -> Any:  # noqa: ANN401 - httpx response
    headers = {} if version is None else _match(version)
    return await world.call("PUT", f"{BASE}/views/{key}", org, user, json=body, headers=headers)


async def test_widths_are_kept_per_person_and_view_with_if_match(world: World) -> None:
    a = world.a
    empty = await world.call("GET", f"{BASE}/views/all", a, a.tech_a)
    assert empty.status_code == 200, empty.text
    assert (empty.json()["version"], empty.json()["columns"]) == (None, [])
    saved = await _put(world, a, a.tech_a, "all", WIDTHS)
    assert saved.status_code == 200, saved.text
    assert saved.json()["columns"] == [{"key": "name", "width": 260}, {"key": "tag", "width": None}]
    assert saved.headers["ETag"] == '"1"'
    # A second save needs the version read; a stale one is a conflict.
    assert problem(await _put(world, a, a.tech_a, "all", WIDTHS))[0] == 428
    assert problem(await _put(world, a, a.tech_a, "all", WIDTHS, version=7)) == (
        409, "version_conflict",
    )  # fmt: skip
    starred = await _put(world, a, a.tech_a, "all", {**WIDTHS, "favourite": True}, version=1)
    assert (starred.json()["favourite"], starred.json()["version"]) == (True, 2)
    kept = await _put(world, a, a.tech_a, "all", WIDTHS, version=2)  # favourite left out: kept
    assert kept.json()["favourite"] is True
    # Another view, another person: their own defaults.
    assert (await world.call("GET", f"{BASE}/views/mine", a, a.tech_a)).json()["version"] is None
    assert (await world.call("GET", f"{BASE}/views/all", a, a.admin)).json()["version"] is None
    (event, *_) = await _events(world, a, "system.list_settings.changed")
    assert set(event["payload"]) == {"user_id", "list_key", "view_key", "change"}
    assert event["payload"]["list_key"] == "assets"


async def test_bad_settings_are_refused_like_the_list_refuses_them(world: World) -> None:
    a = world.a
    too_narrow = await _put(world, a, a.admin, "all", {"columns": [{"key": "name", "width": 5}]})
    assert field_codes(too_narrow) == {"columns": "out_of_range"}
    assert field_codes(await _put(world, a, a.admin, "all", {"page_size": 40})) == {
        "page_size": "invalid_choice"
    }
    assert field_codes(await _put(world, a, a.admin, "nonsense", WIDTHS)) == {
        "view_key": "invalid_choice"
    }
    bad_sort = await _put(world, a, a.admin, "all", {**WIDTHS, "sort": "-secret"})
    assert bad_sort.status_code == 422, bad_sort.text
    assert problem(await world.call("GET", "/list-settings/nothing/views/all", a, a.admin)) == (
        404, "list_not_found",
    )  # fmt: skip
    # The list's own permission: a requester has no asset list, so no settings for it.
    assert problem(await world.call("GET", BASE, a, a.requester))[0] == 403


async def test_saved_views_are_the_owners_with_the_lists_own_filter(world: World) -> None:
    a = world.a
    body = {
        "name": "Laptops in stock",
        "filter": {"field": "name", "op": "contains", "value": "Laptop"},
        "sort": "name",
        "columns": [{"key": "name", "width": 300}],
    }
    made = await world.call("POST", f"{BASE}/saved-views", a, a.tech_a, json=body, headers=_new())
    assert made.status_code == 201, made.text
    view = made.json()
    assert view["view_key"] == f"custom:{view['saved_view_id']}"
    assert (view["name"], view["filter"], view["sort"]) == (body["name"], body["filter"], "name")
    again = await world.call("POST", f"{BASE}/saved-views", a, a.tech_a, json=body, headers=_new())
    assert field_codes(again) == {"name": "duplicate_name"}
    bad = {"name": "Bad", "filter": {"field": "secret", "op": "eq", "value": "x"}}
    refused = await world.call("POST", f"{BASE}/saved-views", a, a.tech_a, json=bad, headers=_new())
    assert refused.status_code == 422, refused.text
    # Listed for its owner, never for anyone else; its settings and star work like a view's.
    mine = (await world.call("GET", BASE, a, a.tech_a)).json()["views"]
    assert [v["name"] for v in mine] == ["Laptops in stock"]
    assert (await world.call("GET", BASE, a, a.admin)).json()["views"] == []
    key = view["view_key"]
    assert problem(await world.call("GET", f"{BASE}/views/{key}", a, a.admin)) == (
        404, "saved_view_not_found",
    )  # fmt: skip
    path = f"{BASE}/saved-views/{view['saved_view_id']}"
    theirs = await world.call("PATCH", path, a, a.admin, json={"name": "x"}, headers=_match(1))
    assert theirs.status_code == 404
    renamed = await world.call(
        "PATCH", path, a, a.tech_a, json={"name": "Stocked laptops", "favourite": True},
        headers=_match(1),
    )  # fmt: skip
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["favourite"]) == ("Stocked laptops", True)
    gone = await world.call("DELETE", path, a, a.tech_a, headers=_match(renamed.json()["version"]))
    assert gone.status_code == 204, gone.text
    assert (await world.call("GET", BASE, a, a.tech_a)).json()["views"] == []
    removed = [e for e in await _events(world, a, "system.list_settings.changed")
               if e["payload"]["change"] == "removed"]  # fmt: skip
    assert len(removed) == 1


async def test_list_settings_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    assert (await _put(world, a, a.admin, "all", WIDTHS)).status_code == 200
    made = await world.call(
        "POST", f"{BASE}/saved-views", a, a.admin, json={"name": "Tenant A"}, headers=_new()
    )
    assert made.status_code == 201, made.text
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM list_settings")) == 0
        changed = await session.execute(text("UPDATE list_settings SET favourite = true"))
        assert changed.rowcount == 0
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM list_settings")) == 2
    assert (await world.call("GET", BASE, b, b.admin)).json()["views"] == []
