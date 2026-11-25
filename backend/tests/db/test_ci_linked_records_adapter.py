"""Work items' CiLinkedRecords adapter: a CI's Associations tab for real (WP-053 S5c, D-158).

Real PostgreSQL with RLS, through the CMDB's own routes, with lane A's adapter registered (the
module registers it at import). Lane B's and the coordinator's conditions:

- **Visible only:** a record the reader may not see is neither listed nor counted, so the tab's
  page and its counts agree, always.
- **"Open" means one thing:** a row's `open` is exactly what the counts call open.
- **Paging:** newest first, an opaque cursor, nothing repeated or skipped.
- **Unknown kinds answer an empty page** (the adapter itself; the route refuses them first).
- **An unlinked record is gone from the tab.**
"""

import uuid
from collections.abc import Iterator
from typing import Any  # JSON bodies

import pytest

from app.core.errors import BadRequest
from app.core.tenancy import TenantContext
from app.modules.cmdb.service.linked import (
    clear_ci_linked_records,
    linked_records_port,
    register_ci_linked_records,
)
from app.modules.identity_access import subject_for
from app.modules.work_items.service import ci_linked_port
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_linked_api import _cmdb_viewer_without_incidents
from tests.db.test_incidents_api import CONSOLE, World
from tests.db.test_work_item_cis_api import _a_ci

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, used by name

CMDB = "/cmdb"


@pytest.fixture(autouse=True)
def adapter() -> Iterator[None]:
    """Lane A's real adapter, whatever another test left registered (restored afterwards)."""
    before = linked_records_port()
    register_ci_linked_records(ci_linked_port.PORT)
    try:
        yield
    finally:
        clear_ci_linked_records()
        if before is not None:
            register_ci_linked_records(before)


async def _kinds(world: World, ci: dict[str, Any], user: uuid.UUID) -> dict[str, tuple[int, int]]:
    found = await world.call("GET", f"{CMDB}/cis/{ci['id']}/linked", world.a, user)
    assert found.status_code == 200, found.text
    return {k["kind"]: (k["open"], k["total"]) for k in found.json()["kinds"]}


async def _page(world: World, ci: dict[str, Any], user: uuid.UUID, **params: str) -> dict[str, Any]:
    page = await world.call(
        "GET", f"{CMDB}/cis/{ci['id']}/linked/incident", world.a, user, params=params
    )
    assert page.status_code == 200, page.text
    return dict(page.json())


async def test_an_unseen_incident_is_neither_listed_nor_counted(world: World) -> None:
    a = world.a
    ci = await _a_ci(world, a, f"Linked host {uuid.uuid4().hex[:6]}")
    made = await world.create(a, a.admin, ci_ids=[ci["id"]])
    seen = await _page(world, ci, a.admin)
    assert [i["display_id"] for i in seen["items"]] == [made["display_id"]]
    assert (await _kinds(world, ci, a.admin))["incident"] == (1, 1)
    viewer = await _cmdb_viewer_without_incidents(world, a)
    blind = await _page(world, ci, viewer)
    assert blind["items"] == []  # may see the CI, never that an incident is linked
    assert blind["next_cursor"] is None
    assert (await _kinds(world, ci, viewer))["incident"] == (0, 0)  # the count agrees
    other = await world.call(
        "GET", f"{CMDB}/cis/{ci['id']}/linked/incident", world.b, world.b.admin
    )
    assert other.status_code == 404  # tenant B never reaches A's CI


async def test_newest_first_with_a_cursor_that_never_repeats_or_skips(world: World) -> None:
    a = world.a
    ci = await _a_ci(world, a, f"Paged host {uuid.uuid4().hex[:6]}")
    made = [await world.create(a, a.admin, ci_ids=[ci["id"]]) for _ in range(3)]
    first = await _page(world, ci, a.admin, limit="2")
    second = await _page(world, ci, a.admin, limit="2", cursor=str(first["next_cursor"]))
    listed = [i["display_id"] for i in [*first["items"], *second["items"]]]
    assert listed == [m["display_id"] for m in reversed(made)]  # all three, once, newest first
    assert first["next_cursor"] is not None
    assert second["next_cursor"] is None


async def test_open_on_a_row_is_what_the_counts_call_open(world: World) -> None:
    a = world.a
    ci = await _a_ci(world, a, f"Mixed host {uuid.uuid4().hex[:6]}")
    working = await world.create(a, a.admin, ci_ids=[ci["id"]])
    done = await world.create(a, a.admin, ci_ids=[ci["id"]])
    await world.sql(  # resolved, as the life cycle would leave it (the test's own record)
        "UPDATE work_items SET status_category = 'resolved' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(done["id"]),
    )
    rows = {i["display_id"]: i["open"] for i in (await _page(world, ci, a.admin))["items"]}
    assert rows == {working["display_id"]: True, done["display_id"]: False}
    assert (await _kinds(world, ci, a.admin))["incident"] == (1, 2)  # one open of two, as listed


async def test_an_unlinked_record_leaves_the_tab(world: World) -> None:
    a = world.a
    ci = await _a_ci(world, a, f"Unlinked host {uuid.uuid4().hex[:6]}")
    item = await world.create(a, a.admin, ci_ids=[ci["id"]])
    path = f"/incidents/{item['id']}"
    [row] = (await world.call("GET", f"{path}/cis", a, a.admin)).json()["items"]
    gone = await world.call(
        "DELETE",
        f"{path}/cis/{row['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert gone.status_code == 204, gone.text
    assert (await _page(world, ci, a.admin))["items"] == []
    assert (await _kinds(world, ci, a.admin))["incident"] == (0, 0)


async def test_the_adapter_itself_unknown_kinds_cursors_and_live_ci_ids(world: World) -> None:
    a = world.a
    ci = await _a_ci(world, a, f"Port host {uuid.uuid4().hex[:6]}")
    item = await world.create(a, a.admin, ci_ids=[ci["id"]])
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        subject = await subject_for(session, a.tenant, a.admin)
        port = ci_linked_port.PORT
        ci_id = uuid.UUID(ci["id"])
        # An unknown kind is an empty page, never an error naming the types.
        assert await port.linked_page(session, subject, ci_id, "not_a_type") == ([], None)
        with pytest.raises(BadRequest):
            await port.linked_page(session, subject, ci_id, "incident", cursor="not-a-cursor")
        # A forged cursor only narrows: one above every ID lists what is visible, no more.
        rows, _ = await port.linked_page(
            session, subject, ci_id, "incident", cursor="ffffffff-ffff-7fff-bfff-ffffffffffff"
        )
        assert [r.id for r in rows] == [uuid.UUID(item["id"])]
        assert await port.ci_ids_of(session, uuid.UUID(item["id"])) == [ci_id]
