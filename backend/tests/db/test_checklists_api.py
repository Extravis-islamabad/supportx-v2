"""Checklists, the library and its CSV import (WP-046a S2; REQ-INC-077, -078).

Real PostgreSQL with RLS: ticking records who and when; empty items are dropped and said; a
library copy is the record's own; the CSV import keeps good rows and lists bad ones; another
tenant's rows are never read or written; unticked items are open work at close.
"""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, problem

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def _add(world: World, org: Org, item: dict[str, Any], **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "POST", f"{BASE}/{item['id']}/checklists", org, org.admin, json=body, headers=CONSOLE
    )


async def test_req_inc_077_a_checklist_drops_empty_items_and_ticks_say_who_and_when(
    world: World,
) -> None:
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    made = await _add(world, a, item, title="Before go-live", items=["Back up", "  ", "", "Test"])
    assert made.status_code == 201, made.text
    assert made.json()["dropped"] == 2  # AC2: left out and said
    checklist = made.json()["checklist"]
    assert [i["text"] for i in checklist["items"]] == ["Back up", "Test"]
    first = checklist["items"][0]
    ticked = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}/checklist-items/{first['id']}",
        a,
        a.tech_a,
        json={"done": True},
        headers={"If-Match": f'"{first["version"]}"', **CONSOLE},
    )
    assert ticked.status_code == 200, ticked.text
    assert ticked.json()["done_by"] == str(a.tech_a)  # AC1
    assert ticked.json()["done_at"] is not None
    listed = (await world.call("GET", f"{BASE}/{item['id']}/checklists", a, a.tech_a)).json()
    assert (listed[0]["done"], listed[0]["total"]) == (1, 2)


async def test_req_inc_077_ac3_and_078_a_library_copy_is_the_record_s_own(world: World) -> None:
    a = world.a
    saved = await world.call(
        "POST",
        f"{BASE}/checklist-library",
        a,
        a.admin,
        json={
            "name": f"Laptop handover {uuid.uuid4().hex[:6]}",
            "labels": {"ar": "تسليم الحاسوب"},
            "items": ["Wipe", "Image"],
        },
        headers=CONSOLE,
    )
    assert saved.status_code == 201, saved.text
    library = saved.json()
    assert library["labels"] == {"ar": "تسليم الحاسوب"}  # AC2: translated
    item = await world.create(a, a.admin)
    copied = await _add(world, a, item, library_id=library["id"])
    assert copied.status_code == 201, copied.text
    checklist = copied.json()["checklist"]
    more = await world.call(
        "POST",
        f"{BASE}/{item['id']}/checklists/{checklist['id']}/items",
        a,
        a.admin,
        json={"items": ["Hand over"]},
        headers=CONSOLE,
    )
    assert more.status_code == 200, more.text
    again = (await world.call("GET", f"{BASE}/checklist-library", a, a.admin)).json()
    [kept] = [x for x in again if x["id"] == library["id"]]
    assert kept["items"] == ["Wipe", "Image"]  # AC3: the library copy is unchanged
    refused = await world.call(
        "POST",
        f"{BASE}/checklist-library",
        a,
        a.tech_a,
        json={"name": "Mine", "items": ["x"]},
        headers=CONSOLE,
    )
    assert refused.status_code == 403, refused.text


async def test_req_inc_078_ac1_a_csv_keeps_good_rows_and_lists_the_bad_one(world: World) -> None:
    a = world.a
    content = "item\nCheck the cable\n\n" + ("x" * 501) + "\nRestart\n"
    read = await world.call(
        "POST",
        f"{BASE}/checklist-library/import",
        a,
        a.admin,
        content=content.encode(),
        headers={"Content-Type": "text/csv", **CONSOLE},
    )
    assert read.status_code == 200, read.text
    assert read.json()["items"] == ["Check the cable", "Restart"]
    assert read.json()["rejected"] == [
        {"row": 3, "reason": "empty"},
        {"row": 4, "reason": "value_too_long"},
    ]
    binary = await world.call(
        "POST",
        f"{BASE}/checklist-library/import",
        a,
        a.admin,
        content=b"\xff\xfe\x00bad",
        headers={"Content-Type": "text/csv", **CONSOLE},
    )
    assert problem(binary)[0] == 422, binary.text


async def test_unticked_items_are_open_work_and_rls_keeps_tenants_apart(world: World) -> None:
    a, b = world.a, world.b
    item = await world.create(a, a.admin)
    made = await _add(world, a, item, title="Close-out", items=["Confirm with the user"])
    assert made.status_code == 201, made.text
    checklist = made.json()["checklist"]
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in ("work_item_checklists", "work_item_checklist_items"):
            rows = await session.execute(
                text(f"SELECT 1 FROM {table} WHERE work_item_id = :r"),  # noqa: S608 - fixed names
                {"r": item["id"]},
            )
            assert rows.all() == [], table
        written = await session.execute(
            text("UPDATE work_item_checklists SET title = 'x' WHERE id = :c"),
            {"c": checklist["id"]},
        )
        assert written.rowcount == 0
    seen = await world.call("GET", f"{BASE}/{item['id']}/checklists", b, b.admin)
    assert seen.status_code == 404, seen.text
    from app.modules.work_items.service import checklists  # noqa: PLC0415 - the port

    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        from app.modules.work_items.infra.models import WorkItem  # noqa: PLC0415 - one row

        record = await session.get(WorkItem, uuid.UUID(item["id"]))
        assert record is not None
        found = await checklists.open_work(session, record)
    assert [o.title for o in found] == ["Close-out: Confirm with the user"]
