"""Copying an incident one or more times over HTTP (WP-046a S5c; REQ-INC-033).

Each copy is a new record through the same create, its history naming the original, its
subject marked as a copy. Tasks come when chosen, as new open tasks; conversations, worklogs and
history never do (AC2). How many at once is limited, and the refusal says the limit (AC3).
"""

import json
import uuid
from typing import Any

import httpx

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_conversation_api import say
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, field_codes, problem
from tests.db.test_parts_api import add_task, tasks

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def copy(
    world: World,
    org: Org,
    user: uuid.UUID,
    item: dict[str, Any],
    **body: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "POST",
        f"{BASE}/{item['id']}/copies",
        org,
        user,
        json=body,
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def test_req_inc_033_ac1_two_copies_name_the_original(world: World) -> None:
    a = world.a
    original = await world.create(
        a, a.admin, subject="Printer jammed", impact="team", tags=["printer"]
    )
    made = await copy(world, a, a.admin, original, count=2)
    assert made.status_code == 201, made.text
    copies = made.json()["items"]
    assert [c["subject"] for c in copies] == [
        "Copy 1 of: Printer jammed",
        "Copy 2 of: Printer jammed",
    ]
    for c in copies:
        assert c["id"] != original["id"]
        assert c["display_id"] != original["display_id"]
        assert (c["impact"], c["tags"], c["requester_id"]) == (
            "team",
            ["printer"],
            original["requester_id"],
        )
        history = await world.history(a, c)
        changes = [ch for e in history for ch in e.get("changes", [])]
        assert any(
            ch["field"] == "copied_from" and ch["new"] == original["display_id"] for ch in changes
        ), history


async def test_req_inc_033_ac2_tasks_when_chosen_never_the_conversation(world: World) -> None:
    a = world.a
    original = await world.create(a, a.admin, group_id=str(a.ga))
    assert (await add_task(world, a, a.admin, original, title="Swap toner")).status_code == 201
    await say(world, a, a.admin, original)
    plain, with_tasks = (
        (await copy(world, a, a.admin, original)).json()["items"][0],
        (await copy(world, a, a.admin, original, parts=["tasks"])).json()["items"][0],
    )
    assert (await tasks(world, a, a.admin, plain))["items"] == []
    copied = (await tasks(world, a, a.admin, with_tasks))["items"]
    assert [(t["title"], t["status"]) for t in copied] == [("Swap toner", "open")]
    for c in (plain, with_tasks):
        talk = await world.call("GET", f"{BASE}/{c['id']}/conversation", a, a.admin)
        assert [e for e in talk.json()["items"] if e["kind"] in {"note", "reply"}] == []
        rows = await world.sql(
            "SELECT count(*) AS n FROM work_item_worklogs"
            " WHERE tenant_id = $1 AND work_item_id = $2",
            a.tenant,
            uuid.UUID(c["id"]),
        )
        assert rows[0]["n"] == 0
    # The group came (the admin may assign); a person never does.
    assert (plain["group_id"], plain["technician_id"]) == (str(a.ga), None)


async def test_req_inc_033_ac3_the_limit_is_said(world: World) -> None:
    a = world.a
    original = await world.create(a, a.admin)
    refused = await copy(world, a, a.admin, original, count=21)
    assert field_codes(refused) == {"count": "too_many_copies"}
    params = [e["params"] for e in refused.json()["errors"]]
    assert params == [{"max": 20}], json.dumps(refused.json())


async def test_copies_need_create_and_a_visible_original(world: World) -> None:
    a, b = world.a, world.b
    original = await world.create(a, a.admin)
    other_tenant = await copy(world, b, b.admin, original)
    assert problem(other_tenant) == (404, "work_item_not_found")
    requester = await copy(world, a, a.requester, original)
    assert requester.status_code == 403, requester.text
