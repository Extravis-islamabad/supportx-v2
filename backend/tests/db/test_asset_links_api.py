"""Assets linked to incidents and requests (REQ-AST-025; the coordinator's plan, 2026-11-10).

The incident world (tests/db/test_incidents_api.py): org A's admin holds everything; tech_a is
in group GA. Assets are made through lane B's API; work items only ever see their IDs.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import asset_links
from tests.db import test_incidents_api
from tests.db.test_asset_holders_api import _asset, _hold
from tests.db.test_incidents_api import BASE, World, field_codes

pytestmark = [pytest.mark.db, pytest.mark.valkey]
world = test_incidents_api.world  # the incident world fixture, reused


async def _assets_of(world: World, item: dict[str, Any], user: uuid.UUID) -> list[dict[str, Any]]:
    found = await world.call("GET", f"{BASE}/{item['id']}/assets", world.a, user)
    assert found.status_code == 200, found.text
    return list(found.json()["items"])


async def _events(world: World, item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE aggregate_id = $1 AND event_type = $2"
        " ORDER BY id",
        item["id"],
        "work_items.asset_link.changed",
    )
    return [json.loads(r["envelope"])["payload"] for r in rows]


async def test_an_incident_links_assets_on_create_and_later_with_history_and_events(
    world: World,
) -> None:
    a = world.a
    laptop = await _asset(world, "Link laptop")
    monitor = await _asset(world, "Link monitor")
    item = await world.create(a, a.admin, asset_ids=[laptop["id"]])
    assert [x["asset_id"] for x in await _assets_of(world, item, a.admin)] == [laptop["id"]]
    # Linking again leaves the first as it is; the new one joins.
    added = await world.call(
        "POST",
        f"{BASE}/{item['id']}/assets",
        a,
        a.admin,
        json={"asset_ids": [laptop["id"], monitor["id"]]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert added.status_code == 201, added.text
    rows = added.json()["items"]
    assert [(r["asset_id"], r["name"]) for r in rows] == [
        (laptop["id"], "Link laptop"),
        (monitor["id"], "Link monitor"),
    ]
    # Unlink with If-Match on the link; a stale version is a conflict.
    link = rows[1]
    stale = await world.call(
        "DELETE",
        f"{BASE}/{item['id']}/assets/{link['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{link["version"] + 1}"'},
    )
    assert stale.status_code == 409, stale.text
    gone = await world.call(
        "DELETE",
        f"{BASE}/{item['id']}/assets/{link['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{link["version"]}"'},
    )
    assert gone.status_code == 204, gone.text
    assert [x["asset_id"] for x in await _assets_of(world, item, a.admin)] == [laptop["id"]]
    # History names each asset by its tag and name, never an ID.
    lines = [
        (c["old"], c["new"])
        for h in await world.history(a, item)
        for c in h["changes"]
        if c["field"] == "asset"
    ]
    assert len(lines) == 3
    assert all(laptop["id"] not in str(line) and monitor["id"] not in str(line) for line in lines)
    assert any(new is not None and "Link monitor" in new for _, new in lines)
    assert any(old is not None and "Link monitor" in old for old, _ in lines)
    # One event per link and unlink, IDs only.
    events = await _events(world, item)
    assert [e["change"] for e in events] == ["added", "added", "removed"]
    assert set(events[0]) >= {"work_item_id", "asset_id", "change"}
    assert "name" not in events[0]


async def test_an_asset_you_may_not_see_is_refused_and_the_cap_holds(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = world.a, world.b
    item = await world.create(a, a.admin)
    elsewhere = await world.call(  # another organisation's asset is unknown here
        "POST",
        f"{BASE}/{item['id']}/assets",
        a,
        a.admin,
        json={"asset_ids": [str(uuid.uuid4())]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert field_codes(elsewhere) == {"asset_ids": "asset_not_found"}, elsewhere.text
    del b
    first = await _asset(world, "Cap one")
    second = await _asset(world, "Cap two")
    monkeypatch.setattr(asset_links, "MAX_LINKS", 1)
    over = await world.call(
        "POST",
        f"{BASE}/{item['id']}/assets",
        a,
        a.admin,
        json={"asset_ids": [first["id"], second["id"]]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert field_codes(over) == {"asset_ids": "too_many_assets"}, over.text


async def test_asset_links_are_isolated_by_tenant(world: World) -> None:
    a, b = world.a, world.b
    laptop = await _asset(world, "RLS laptop")
    item = await world.create(a, a.admin, asset_ids=[laptop["id"]])
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = (await session.execute(text("SELECT count(*) FROM work_item_assets"))).scalar()
        assert seen == 0  # tenant B reads none of A's links
    with pytest.raises(Exception, match="row-level security"):
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO work_item_assets (id, tenant_id, work_item_id, asset_id)"
                    " VALUES (:id, :t, :w, :x)"
                ),
                {"id": uuid.uuid4(), "t": a.tenant, "w": uuid.UUID(item["id"]), "x": uuid.uuid4()},
            )


async def _set_email_assets(world: World, on: bool) -> None:
    await world.sql(
        "INSERT INTO asset_settings (tenant_id, email_include_assets) VALUES ($1, $2)"
        " ON CONFLICT (tenant_id) DO UPDATE SET email_include_assets = $2",
        world.a.tenant,
        on,
    )


async def test_an_emailed_incident_gets_the_requesters_one_asset_when_the_tenant_says_so(
    world: World,
) -> None:
    """AC2: one laptop held, the setting on: linked, from the e-mail. Off, or two: none."""
    a = world.a
    laptop = await _asset(world, "Mail laptop")
    assert (await _hold(world, laptop, "user", a.requester)).status_code == 200

    async def emailed() -> list[dict[str, Any]]:
        item = await world.create(a, a.admin, requester_id=str(a.requester))
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            record = await session.get(WorkItem, uuid.UUID(item["id"]))
            assert record is not None
            await asset_links.attach_emailed(session, record)
        return await _assets_of(world, item, a.admin)

    await _set_email_assets(world, on=False)
    assert await emailed() == []
    await _set_email_assets(world, on=True)
    (one,) = await emailed()
    assert (one["asset_id"], one["source"]) == (laptop["id"], "email")
    printer = await _asset(world, "Mail printer")
    assert (await _hold(world, printer, "user", a.requester)).status_code == 200
    assert await emailed() == []  # two held: which one is unclear, so none


async def test_linked_to_my_tickets_counts_assigned_records_still_being_worked(
    world: World,
) -> None:
    """D-153 (the coordinator): records assigned to the technician, open, paused or resolved."""
    a = world.a
    laptop = await _asset(world, "Mine laptop")
    other = await _asset(world, "Group laptop")
    mine = await world.create(
        a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a), asset_ids=[laptop["id"]]
    )
    await world.create(a, a.admin, group_id=str(a.ga), asset_ids=[other["id"]])  # nobody's yet

    async def linked() -> set[str]:
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            rows = await session.scalars(asset_links.linked_asset_ids_select(a.tech_a))
            return {str(r) for r in rows}

    assert await linked() == {laptop["id"]}  # assigned to them only, not their group's
    resolved = await world.act(a, a.tech_a, mine, "resolve")
    assert resolved.status_code == 200, resolved.text
    assert await linked() == {laptop["id"]}  # resolved, not closed: still theirs
    closed = await world.act(a, a.tech_a, await world.fresh(a, mine), "close")
    assert closed.status_code == 200, closed.text
    assert await linked() == set()
