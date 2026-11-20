"""Lists by POST, and sealed values kept out of URLs (lane C's follow-up to #549, PR 2).

Real PostgreSQL, the incidents test world, a key ring of its own. The sealed values hold a space
and "!", which no base64 or hex text contains, so "absent" never passes by chance.
"""

import base64
import hashlib
import json
import uuid
from typing import Any

import pytest
import structlog

from app.core.tenancy import TenantContext
from app.modules.work_items.service import view_audit
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, field_codes, problem
from tests.db.test_view_filters_api import _forget, _sealed_field, _with_keys

pytestmark = [pytest.mark.db, pytest.mark.valkey, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, used by name

SECRET = "ZX 9081!"
OTHER = "QY 4417!"


async def _post(w: World, org: Org, user: uuid.UUID, **body: Any) -> Any:  # noqa: ANN401 - JSON
    return await w.call("POST", f"{BASE}/list", org, user, json=body)


def _ids(page: Any) -> list[str]:  # noqa: ANN401 - JSON
    return [item["id"] for item in page.json()["items"]]


async def test_the_post_form_answers_as_the_get_does(world: World) -> None:
    a = world.a
    for _ in range(3):
        await world.create(a, a.admin, group_id=str(a.ga), subject="Batch match for POST")
    tree = {"field": "subject", "op": "contains", "value": "Batch match for POST"}
    got = await world.call("GET", f"{BASE}?limit=2&filter={json.dumps(tree)}", a, a.admin)
    posted = await _post(world, a, a.admin, filter=tree, limit=2)
    assert got.status_code == posted.status_code == 200, posted.text
    assert _ids(got) == _ids(posted)
    assert posted.headers["cache-control"] == "no-store"
    # A POST cursor pages the POST form; it never replays on the GET (its own scope).
    cursor = posted.json()["next_cursor"]
    second = await _post(world, a, a.admin, filter=tree, limit=2, cursor=cursor)
    assert second.status_code == 200, second.text
    crossed = await world.call(
        "GET", f"{BASE}?limit=2&filter={json.dumps(tree)}&cursor={cursor}", a, a.admin
    )
    assert crossed.status_code in {400, 422}, crossed.text


async def test_a_sealed_filter_never_travels_in_a_url_and_works_by_post(world: World) -> None:
    _with_keys(world)
    a = world.a
    field = await _sealed_field(world, a, "National ID")
    key = field.removeprefix("custom.")
    match = await world.create(a, a.admin, group_id=str(a.ga), custom={key: SECRET})
    await world.create(a, a.admin, group_id=str(a.ga), custom={key: OTHER})
    tree = {"field": field, "op": "eq", "value": SECRET}
    # Both GET shapes are refused, naming the field and never the value (lane C's point 3).
    for url in (f"{BASE}?filter={json.dumps(tree)}", f"{BASE}?{field}={SECRET}"):
        refused = await world.call("GET", url, a, a.admin)
        assert field_codes(refused) == {"query.filter": "sealed_filter_needs_post"}
        assert refused.json()["errors"][0]["params"] == {"field": field}
        assert SECRET not in refused.text
    found = await _post(world, a, a.admin, filter=tree)
    assert found.status_code == 200, found.text
    assert _ids(found) == [match["id"]]


async def test_a_cursor_holds_no_filter_and_sealed_fields_never_sort(world: World) -> None:
    """Lane C: the fingerprint is only an input to the cursor's MAC, never in its payload."""
    _with_keys(world)
    a = world.a
    field = await _sealed_field(world, a, "Passport no")
    key = field.removeprefix("custom.")
    for value in (SECRET, SECRET, OTHER, OTHER):
        await world.create(a, a.admin, group_id=str(a.ga), custom={key: value})

    async def cursor_for(value: str) -> str:
        page = await _post(
            world, a, a.admin, filter={"field": field, "op": "eq", "value": value}, limit=1
        )
        assert page.status_code == 200, page.text
        return str(page.json()["next_cursor"])

    one, two = await cursor_for(SECRET), await cursor_for(OTHER)
    tree = {"field": field, "op": "eq", "value": SECRET}
    plain_hash = hashlib.sha256(json.dumps([tree, []], sort_keys=True).encode()).hexdigest()
    for cursor in (one, two):
        payload, _, _signature = cursor.partition(".")
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        assert SECRET not in decoded
        assert OTHER not in decoded
        assert plain_hash not in cursor
        assert plain_hash not in decoded
    assert one.partition(".")[2] != two.partition(".")[2]  # different values, different MACs
    # A sealed field cannot be a sort key (its payload would carry the stored value).
    sorted_on = await _post(world, a, a.admin, sort=f"-{field}")
    assert problem(sorted_on)[0] == 422
    assert sorted_on.json()["code"] == "invalid_sort"


async def test_bad_bodies_echo_nothing_and_large_ones_are_refused(world: World) -> None:
    """Lane C's point 5 and lane B's cap: nothing sent comes back, a large body is refused."""
    _with_keys(world)
    a = world.a
    field = await _sealed_field(world, a, "Tax no")
    malformed = await world.call(
        "POST",
        f"{BASE}/list",
        a,
        a.admin,
        json={"filter": {"field": field, "op": "eq", "value": SECRET}, "limit": SECRET},
    )
    assert malformed.status_code == 422, malformed.text
    assert SECRET not in malformed.text
    oversized = await _post(
        world, a, a.admin, filter={"field": "subject", "op": "contains", "value": "x" * 70_000}
    )
    assert oversized.status_code == 422, oversized.text
    assert oversized.json()["code"] in {"list_body_too_large", "invalid_filter"}
    assert "x" * 1000 not in oversized.text


async def test_no_log_line_holds_a_sealed_value(world: World) -> None:
    """Lane C's condition 7: the GET refusal and the POST success, captured."""
    _with_keys(world)
    a = world.a
    field = await _sealed_field(world, a, "Badge no")
    key = field.removeprefix("custom.")
    await world.create(a, a.admin, group_id=str(a.ga), custom={key: SECRET})
    tree = {"field": field, "op": "eq", "value": SECRET}
    with structlog.testing.capture_logs() as logs:
        await world.call("GET", f"{BASE}?filter={json.dumps(tree)}", a, a.admin)
        await _post(world, a, a.admin, filter=tree)
    assert SECRET not in json.dumps(logs, default=str)


async def test_a_sort_on_a_field_turned_sensitive_is_cleared_not_refused(world: World) -> None:
    """Lane B: a saved view and a person's list settings sorting on a field that later turns
    sensitive lose that sort (the audit), so the list falls back to its default."""
    _with_keys(world)
    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Level"}},
        headers=CONSOLE,
    )
    field = f"custom.{made.json()['key']}"
    view = (
        await world.call(
            "POST", f"{BASE}/saved-views", a, a.admin, json={"name": "By level", "sort": field}
        )
    ).json()
    setting = await world.call(
        "PUT", f"{BASE}/list-settings/open", a, a.admin, json={"page_size": 25, "sort": f"-{field}"}
    )
    assert setting.status_code == 200, setting.text
    await world.sql(
        "UPDATE custom_fields SET sensitive = true, seal_state = 'sealed'"
        " WHERE tenant_id = $1 AND entity = 'incident' AND key = $2",
        a.tenant,
        field.removeprefix("custom."),
    )
    await _forget(world)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await view_audit.audit_all(session)
    (row,) = await world.sql(
        "SELECT sort FROM work_item_views WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(view["id"]),
    )
    assert row["sort"] is None
    shown = await world.call("GET", f"{BASE}/list-settings/open", a, a.admin)
    assert shown.json()["sort"] is None
    assert (await _post(world, a, a.admin)).status_code == 200
