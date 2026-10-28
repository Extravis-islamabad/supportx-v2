"""Resolving, closing and reopening over HTTP (WP-020f; REQ-INC-090, 093-095, 097, 100).

Real PostgreSQL, the incidents test world. Each test names the requirement and criterion.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio

from app.modules.work_items.domain.closure import OpenItem, OpenWorkKind
from app.modules.work_items.service import closing
from tests.db.test_incidents_api import BASE, Org, World, field_codes, incidents_world, problem
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(migrated_db) as built:
        yield built


async def settings(world: World, org: Org) -> dict[str, Any]:
    read = await world.call("GET", f"{BASE}/settings", org, org.admin)
    assert read.status_code == 200, read.text
    return dict(read.json())


async def change_closure(world: World, org: Org, **body: Any) -> Any:  # noqa: ANN401 - JSON
    current = await settings(world, org)
    return await world.call(
        "PATCH",
        f"{BASE}/settings/closure",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{current["version"]}"'},
    )


async def fresh(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    return dict((await world.get(org, org.admin, item)).json())


async def test_req_inc_090_ac1_resolve_needs_a_resolution_and_keeps_it(world: World) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    refused = await world.act(org, org.admin, item, "resolve", resolution="<p> </p>")
    assert problem(refused) == (422, "closure_rules")
    assert field_codes(refused) == {"resolution": "required"}
    resolved = await world.act(
        org,
        org.admin,
        item,
        "resolve",
        resolution="<p>Restarted the <strong>spooler</strong><script>x</script></p>",
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status_category"] == "resolved"
    assert body["resolved_at"] is not None
    assert body["resolution"] == "<p>Restarted the <strong>spooler</strong></p>"  # sanitised
    assert body["resolution_notified_at"] is None  # nobody has told the requester yet


async def test_req_inc_093_and_094_ac1_close_asks_only_for_the_closure_code(world: World) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    resolved = (await world.act(org, org.admin, item, "resolve")).json()
    refused = await world.act(org, org.admin, resolved, "close", closure_code="")
    assert problem(refused) == (422, "closure_rules")
    assert field_codes(refused) == {"closure_code": "required"}
    wrong = await world.act(org, org.admin, resolved, "close", closure_code="nope")
    assert field_codes(wrong) == {"closure_code": "invalid_choice"}
    closed = await world.act(org, org.admin, resolved, "close", closure_code="workaround")
    assert closed.status_code == 200, closed.text
    assert closed.json()["closure_code"] == "workaround"


async def test_req_inc_094_ac3_rule_fields_are_named_with_the_codes_the_ui_shows(
    world: World,
) -> None:
    org = world.a
    saved = await change_closure(world, org, resolve_requires=["resolution", "category_id"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["closure"]["resolve_requires"] == ["resolution", "category_id"]
    item = await world.create(org, org.admin)
    # The record says what is missing before anyone tries (the move asks for its own field).
    (state,) = [a for a in (await fresh(world, org, item))["actions"] if a["action"] == "resolve"]
    assert state["missing"] == ["category_id"]
    refused = await world.act(org, org.admin, item, "resolve")
    assert field_codes(refused) == {"category_id": "required_to_resolve"}


async def test_req_inc_094_only_known_fields_can_be_required(world: World) -> None:
    org = world.a
    refused = await change_closure(world, org, close_requires=["closure_code", "favourite_colour"])
    assert field_codes(refused) == {"close_requires": "invalid_choice"}


@pytest.fixture
def open_task() -> Iterator[None]:
    async def tasks(_session: object, _record: object) -> list[OpenItem]:
        return [OpenItem(OpenWorkKind.TASKS, "Replace the toner")]

    closing.register_open_work(OpenWorkKind.TASKS, tasks)
    yield
    closing.unregister_open_work(OpenWorkKind.TASKS)


@pytest.mark.usefixtures("open_task")
async def test_req_inc_095_ac1_ac4_open_tasks_warn_and_the_confirmation_is_recorded(
    world: World,
) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    warned = await world.act(org, org.admin, item, "resolve")
    assert problem(warned) == (409, "open_work_unconfirmed")
    assert warned.json()["params"]["items"] == "Replace the toner"
    confirmed = await world.act(org, org.admin, item, "resolve", confirm_open_work=True)
    assert confirmed.status_code == 200, confirmed.text
    history = await world.history(org, confirmed.json())
    lines = [c for h in history for c in h["changes"] if c["field"] == "open_work_confirmed"]
    assert [line["new"] for line in lines] == [["Replace the toner"]]


@pytest.mark.usefixtures("open_task")
async def test_req_inc_095_ac2_an_admin_turns_the_warning_into_a_block(world: World) -> None:
    org = world.a
    assert (await change_closure(world, org, open_work={"tasks": "block"})).status_code == 200
    item = await world.create(org, org.admin)
    refused = await world.act(org, org.admin, item, "resolve", confirm_open_work=True)
    assert problem(refused) == (409, "open_work_blocked")


async def test_req_inc_097_reopen_keeps_the_past_and_asks_again(world: World) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    resolved = (
        await world.act(org, org.admin, item, "resolve", resolution="<p>Rebooted</p>")
    ).json()
    closed = (await world.act(org, org.admin, resolved, "close", closure_code="fixed")).json()
    reopened = await world.act(
        org, org.admin, closed, "reopen", reason_code="not_fixed", reason_text="Still jams"
    )
    assert reopened.status_code == 200, reopened.text
    body = reopened.json()
    assert (body["resolution"], body["closure_code"], body["reopen_count"]) == (None, None, 1)
    history = await world.history(org, body)
    seen = {(c["field"], str(c["old"])) for h in history for c in h["changes"]}
    # The earlier resolution and closure code stay in history (REQ-INC-097 AC2).
    assert ("resolution", "<p>Rebooted</p>") in seen
    assert ("closure_code", "fixed") in seen


async def test_req_inc_096_auto_close_waits_for_a_channel_that_tells_requesters(
    world: World,
) -> None:
    org = world.a
    assert (await settings(world, org))["closure"]["auto_close_days"] is None  # off by default
    refused = await change_closure(world, org, auto_close_days=3)
    assert field_codes(refused) == {"auto_close_days": "auto_close_needs_notifications"}
    closing.register_requester_channel("email")
    try:
        allowed = await change_closure(world, org, auto_close_days=3)
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["closure"]["requester_channels"] == ["email"]
        assert field_codes(await change_closure(world, org, auto_close_days=31)) == {
            "auto_close_days": "out_of_range"
        }
    finally:
        closing.unregister_requester_channel("email")


async def test_req_inc_100_ac2_a_canceled_record_takes_no_edits(world: World) -> None:
    org = world.a
    item = await world.create(org, org.admin)
    canceled = (
        await world.act(org, org.admin, item, "cancel", reason_code="duplicate", reason_text="x")
    ).json()
    edited = await world.call(
        "PATCH",
        f"{BASE}/{canceled['id']}",
        org,
        org.admin,
        json={"subject": "Changed"},
        headers={"If-Match": f'"{canceled["version"]}"'},
    )
    assert problem(edited) == (409, "record_closed")
