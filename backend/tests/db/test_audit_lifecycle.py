"""One audit entry per save of a lifecycle record (WP-064 S1, D-150, ADR-045).

Assets first (lane B's). Condition by condition (coordinator, 2026-11-10):
1. what found a route's entry still finds it: the action filter matches a code among a save's
   events, and the route's own code leads its saves' entries;
2. outcome, actor and reason are carried as the route's entry had them (reason outside the hash);
3. decided in the save's transaction: a delete and a restore write exactly one entry each, and a
   refused save writes none;
4. a save outside a route (a worker) gets its entry at once, from the worker.
"""

import json
import uuid
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.shared.history import Change, record_changes
from tests.db import test_incidents_api
from tests.db.test_assets_api import _add, _patch, _product
from tests.db.test_incidents_api import Org, World, problem
from tests.db.test_knowledge_api import _match

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"


async def _entries(world: World, org: Org, asset_id: str) -> list[Any]:
    return await world.sql(
        "SELECT action, events, outcome, actor_id, client, change_id, details"
        " FROM audit_entries WHERE tenant_id = $1 AND object_type = 'asset' AND object_id = $2"
        " ORDER BY occurred_at, id",
        org.tenant,
        asset_id,
    )


async def _asset(world: World, org: Org, name: str) -> dict[str, Any]:
    product = await _product(world, org, "laptop", f"Lifecycle {name}")
    made = await _add(world, org, {"name": name, "product_id": product})
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_a_create_is_one_entry_led_by_the_routes_code(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Created once")
    (entry,) = await _entries(world, a, asset["id"])
    assert entry["action"] == "asset.created"
    assert list(entry["events"]) == ["asset.created"]
    assert (entry["outcome"], entry["actor_id"]) == ("done", a.admin)
    assert entry["change_id"] is not None  # linked to the save's history
    assert json.loads(entry["details"])["record_version"] == 1


async def test_a_delete_and_a_restore_write_exactly_one_entry_each(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Trash and back")
    gone = await world.call(
        "DELETE", f"{BASE}/{asset['id']}", a, a.admin, headers=_match(asset["version"])
    )
    assert gone.status_code == 204, gone.text
    back = await world.call("POST", f"{BASE}/{asset['id']}/restore", a, a.admin)
    assert back.status_code == 200, back.text
    found = [(e["action"], list(e["events"] or [])) for e in await _entries(world, a, asset["id"])]
    assert found == [
        ("asset.created", ["asset.created"]),
        ("asset.deleted", ["asset.deleted"]),
        ("asset.restored", ["asset.restored"]),
    ]


async def test_one_save_lists_all_its_events_and_each_code_finds_it(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Moved and renamed")
    changed = await _patch(world, a, asset, {"name": "Renamed", "location": "Floor 3"})
    assert changed.status_code == 200, changed.text
    last = (await _entries(world, a, asset["id"]))[-1]
    assert last["action"] == "asset.updated"
    assert list(last["events"]) == ["asset.updated", "asset.relocated"]
    # Filtering by the second code finds the save's entry (condition 1).
    found = await world.call(
        "GET",
        "/audit/entries",
        a,
        a.admin,
        params={"filter": json.dumps({"field": "action", "op": "eq", "value": "asset.relocated"})},
    )
    assert found.status_code == 200, found.text
    assert {e["object_id"] for e in found.json()["items"]} == {asset["id"]}
    # And "not relocated" leaves it out.
    other = await world.call(
        "GET",
        "/audit/entries",
        a,
        a.admin,
        params={
            "filter": json.dumps({"field": "action", "op": "ne", "value": "asset.relocated"}),
            "limit": "200",
        },
    )
    assert asset["id"] not in {
        e["object_id"] for e in other.json()["items"] if e["action"] == "asset.updated"
    }


async def test_a_refused_save_writes_no_entry(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Stale")
    stale = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.admin, json={"name": "Late"}, headers=_match(9)
    )
    assert problem(stale)[0] == 409
    entries = await _entries(world, a, asset["id"])
    # No save, no lifecycle entry; a refusal the route logs stays as it was (condition 4).
    assert [e["action"] for e in entries if e["events"] is not None] == ["asset.created"]
    assert all(e["outcome"] != "done" for e in entries if e["events"] is None)


async def test_a_save_outside_a_route_gets_its_entry_at_once(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Worker save")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await record_changes(
            session,
            record_type="asset",
            record_id=uuid.UUID(asset["id"]),
            version=2,
            kind="updated",
            changes=[Change("state_id", None, str(uuid.uuid4()))],
            source="system",
            automation_ref={"kind": "rule", "id": "r-1", "name": "Free text never logged"},
        )
    last = (await _entries(world, a, asset["id"]))[-1]
    assert (last["action"], list(last["events"])) == ("asset.moved", ["asset.moved"])
    assert last["client"] == "worker"
    details = json.loads(last["details"])
    assert details["automation"] == "rule"
    assert "Free text never logged" not in last["details"]  # a rule's name stays out


async def test_other_record_types_get_no_lifecycle_entry(world: World) -> None:
    a = world.a
    before = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND events IS NOT NULL",
        a.tenant,
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await record_changes(
            session,
            record_type="announcement",
            record_id=uuid.uuid4(),
            version=1,
            kind="created",
            changes=[],
            source="system",
        )
    after = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND events IS NOT NULL",
        a.tenant,
    )
    assert after[0]["n"] == before[0]["n"]
