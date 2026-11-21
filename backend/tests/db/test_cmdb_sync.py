"""Attribute sources and sync rules from assets over HTTP (WP-053 S4a; REQ-CMDB-015, 016; 0191).

The coordinator's conditions 1, 2 and 6 and lane C's conditions 1 to 5:
- only an unrestricted author makes or changes a rule (cmdb.configure, cmdb.view and assets.view
  at "all", no fine-grained narrowing); anyone else gets `cmdb_sync_author_restricted`;
- the field map takes only assets' syncable fields: money, a person and custom fields are 422;
- the preview runs as the author and writes nothing;
- a run writes through the CI save path as the sync identity: history source `system` with the
  run in its automation reference and batch, attributes stamped `asset_sync`, one audit entry;
- which source wins: a hand-set value is kept, never overwritten; the order is audited with its
  before and after;
- a run's items and a CI's sources never show a CI, an asset or a field the reader may not see.

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.cmdb.service import sync
from app.shared.events import EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_assets_api import _add as add_asset
from tests.db.test_assets_api import _product
from tests.db.test_cmdb_api import _ci, _types
from tests.db.test_cmdb_custom_fields import _field, _role_id
from tests.db.test_cmdb_custom_fields import _rule as field_rule
from tests.db.test_incidents_api import Org, World, field_codes, problem, role
from tests.db.test_knowledge_api import _match, _new

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

BASE = "/cmdb"
TABLES = ("cmdb_sync_rules", "cmdb_sync_runs")


async def _assets(world: World, org: Org, count: int) -> tuple[str, list[dict[str, Any]]]:
    product = await _product(world, org, "laptop", f"Sync laptop {uuid.uuid4().hex[:8]}")
    made = []
    for n in range(count):
        found = await add_asset(
            world, org, {"name": f"Laptop {n} {uuid.uuid4().hex[:4]}", "product_id": product}
        )
        assert found.status_code == 201, found.text
        made.append(dict(found.json()))
    return product, made


async def _body(world: World, org: Org, product: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    types = await _types(world, org)
    return {
        "name": f"Laptops {uuid.uuid4().hex[:6]}",
        "filter": {"field": "product_id", "op": "eq", "value": product},
        "target_type_id": types["workstation"]["id"],
        "field_map": {"name": "name", "description": "location"},
        **extra,
    }


async def _rule(
    world: World, org: Org, body: dict[str, Any], user: uuid.UUID | None = None
) -> httpx.Response:
    return await world.call(
        "POST", f"{BASE}/sync-rules", org, user or org.admin, json=body, headers=_new()
    )


async def _run(world: World, org: Org, rule: dict[str, Any]) -> dict[str, Any]:
    """Queue a run, work the tenant's queue as the worker does, and read the run back."""
    queued = await world.call(
        "POST", f"{BASE}/sync-rules/{rule['id']}/runs", org, org.admin, headers=_new()
    )
    assert queued.status_code == 201, queued.text
    await sync.run_tenant(world.app.state.db, org.tenant)
    found = await world.call("GET", f"{BASE}/sync-runs/{queued.json()['id']}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def _ci_of(world: World, org: Org, asset_id: str) -> dict[str, Any]:
    rows = await world.sql(
        "SELECT id FROM cmdb_cis WHERE tenant_id = $1 AND asset_id = $2 AND deleted_at IS NULL",
        org.tenant,
        uuid.UUID(asset_id),
    )
    assert rows, "no CI for the asset"
    found = await world.call("GET", f"{BASE}/cis/{rows[0]['id']}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


# --- tenant isolation (rule a) --------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
async def test_the_sync_tables_are_isolated_by_rls(world: World, table: str) -> None:
    a, b = world.a, world.b
    product, _ = await _assets(world, a, 1)
    made = await _rule(world, a, await _body(world, a, product))
    assert made.status_code == 201, made.text
    await _run(world, a, made.json())
    assert problem(
        await world.call("GET", f"{BASE}/sync-rules/{made.json()['id']}", b, b.admin)
    ) == (404, "cmdb_sync_rule_not_found")
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - a fixed table name
            {"a": a.tenant},
        )
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text(f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :a"),  # noqa: S608 - a fixed table name
            {"a": a.tenant},
        )
        assert changed.rowcount == 0


# --- who may make a rule, and what it may map (lane C 1, 3) ---------------------------------------


async def test_only_an_unrestricted_author_makes_or_changes_a_rule(world: World) -> None:
    a = world.a
    product, _ = await _assets(world, a, 1)
    body = await _body(world, a, product)
    types = await _types(world, a)
    # Every right, but assets only at their own sites (and no other role giving more): refused.
    site_only = await role(
        world,
        a,
        f"Sync site {uuid.uuid4().hex[:4]}",
        [("cmdb.configure", "all"), ("cmdb.view", "all"), ("assets.view", "site")],
    )
    assert (
        await world.call("PUT", f"/users/{a.requester}/roles/{site_only}", a, a.admin)
    ).status_code == 204
    # Every right at "all", but narrowed to servers by a fine-grained rule: refused too.
    await world.sql(
        "UPDATE tenant_subscriptions SET edition = 'enterprise' WHERE tenant_id = $1", a.tenant
    )
    narrowed = await role(
        world,
        a,
        f"Sync narrowed {uuid.uuid4().hex[:4]}",
        [("cmdb.configure", "all"), ("cmdb.view", "all"), ("assets.view", "all")],
    )
    assert (
        await world.call("PUT", f"/users/{a.tech_c}/roles/{narrowed}", a, a.admin)
    ).status_code == 204
    ruled = await world.call(
        "POST",
        "/resource-access/rules",
        a,
        a.admin,
        json={
            "role_id": str(narrowed),
            "resource": "ci",
            "criteria": {"type_ids": [types["server"]["id"]]},
        },
        headers=_new(),
    )
    assert ruled.status_code == 201, ruled.text
    try:
        for user in (a.requester, a.tech_c):
            assert problem(await _rule(world, a, body, user)) == (
                403,
                "cmdb_sync_author_restricted",
            )
            preview = await world.call("POST", f"{BASE}/sync-rules/preview", a, user, json=body)
            assert problem(preview) == (403, "cmdb_sync_author_restricted")
        made = await _rule(world, a, body)
        assert made.status_code == 201, made.text
        changed = await world.call(
            "PUT",
            f"{BASE}/sync-rules/{made.json()['id']}",
            a,
            a.tech_c,
            json={**body, "enabled": True},
            headers=_match(made.json()["version"]),
        )
        assert problem(changed) == (403, "cmdb_sync_author_restricted")
        # Without cmdb.configure at all: the route's own 403.
        assert (await world.call("GET", f"{BASE}/sync-rules", a, a.requester2)).status_code == 403
    finally:
        await world.call("DELETE", f"/users/{a.requester}/roles/{site_only}", a, a.admin)
        await world.call("DELETE", f"/users/{a.tech_c}/roles/{narrowed}", a, a.admin)


@pytest.mark.parametrize(
    ("target", "source"),
    [
        ("description", "purchase_price"),  # money (D-157, D-164)
        ("description", "owner_user_id"),  # a person
        ("owner_group_id", "department_id"),  # a person's department
        ("description", "custom.anything"),  # an asset custom field (may be sealed or ruled)
        ("description", "gl_code"),  # not marked syncable
    ],
)
async def test_the_field_map_takes_only_syncable_asset_fields(
    world: World, target: str, source: str
) -> None:
    a = world.a
    product, _ = await _assets(world, a, 1)
    body = await _body(world, a, product, field_map={"name": "name", target: source})
    refused = await _rule(world, a, body)
    assert refused.status_code == 422, refused.text
    assert field_codes(refused)[f"field_map.{target}"] == "cmdb_sync_field_not_syncable"


async def test_a_sensitive_or_personal_ci_field_is_never_a_target(world: World) -> None:
    a = world.a
    product, _ = await _assets(world, a, 1)
    plain = (await _field(world, a, f"Rack {uuid.uuid4().hex[:4]}", "workstation"))["key"]
    personal = await _field(world, a, f"Owner note {uuid.uuid4().hex[:4]}", "workstation")
    # Marked as personal data (as an e-mail or a person field is): never filled by a sync.
    await world.sql(
        "UPDATE custom_fields SET personal_data = true WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(personal["id"]),
    )
    ok = await _rule(
        world,
        a,
        await _body(world, a, product, field_map={"name": "name", f"custom.{plain}": "location"}),
    )
    assert ok.status_code == 201, ok.text
    refused = await _rule(
        world,
        a,
        await _body(
            world, a, product, field_map={"name": "name", f"custom.{personal['key']}": "location"}
        ),
    )
    assert refused.status_code == 422, refused.text
    assert field_codes(refused)[f"field_map.custom.{personal['key']}"] == (
        "cmdb_sync_target_unknown"
    )


# --- preview (lane C 2; REQ-CMDB-015 AC1) --------------------------------------------------------


async def test_the_preview_lists_what_would_sync_and_writes_nothing(world: World) -> None:
    a = world.a
    product, made = await _assets(world, a, 4)
    before = await world.sql("SELECT count(*) AS n FROM cmdb_cis WHERE tenant_id = $1", a.tenant)
    events = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1", a.tenant
    )
    found = await world.call(
        "POST", f"{BASE}/sync-rules/preview", a, a.admin, json=await _body(world, a, product)
    )
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["total"] == 4
    assert body["complete"] is True
    assert body["counts"]["created"] == 4
    assert {i["asset_id"] for i in body["items"]} == {m["id"] for m in made}
    after = await world.sql("SELECT count(*) AS n FROM cmdb_cis WHERE tenant_id = $1", a.tenant)
    assert after[0]["n"] == before[0]["n"]
    later = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1", a.tenant
    )
    assert later[0]["n"] == events[0]["n"]


# --- runs (lane C 4, the coordinator's 2; REQ-CMDB-015 AC2, 016 AC2) ------------------------------


async def test_a_run_creates_and_updates_cis_through_the_save_path(world: World) -> None:
    a = world.a
    product, made = await _assets(world, a, 2)
    rule = await _rule(world, a, await _body(world, a, product, enabled=True))
    assert rule.status_code == 201, rule.text
    run = await _run(world, a, rule.json())
    assert run["status"] == "succeeded", run
    assert run["created_count"] == 2
    ci = await _ci_of(world, a, made[0]["id"])
    assert ci["source"] == "asset_sync"
    assert ci["name"] == made[0]["name"]
    assert ci["sources"]["name"]["source"] == "asset_sync"
    # Field history: source `system`, the run in the automation reference and as the batch.
    rows = await world.sql(
        "SELECT source, automation_ref, batch_id FROM field_changes"
        " WHERE tenant_id = $1 AND record_type = 'ci' AND record_id = $2",
        a.tenant,
        uuid.UUID(ci["id"]),
    )
    assert rows
    assert {r["source"] for r in rows} == {"system"}
    assert {str(r["batch_id"]) for r in rows} == {run["id"]}
    assert all('"cmdb_sync"' in str(r["automation_ref"]) for r in rows)
    assert all(run["id"] in str(r["automation_ref"]) for r in rows)
    # One audit entry for the run, with its counts.
    entries = await world.sql(
        "SELECT action, details FROM audit_entries WHERE tenant_id = $1 AND object_id = $2",
        a.tenant,
        run["id"],
    )
    assert [e["action"] for e in entries] == ["cmdb.sync_run_finished"]

    # An asset changes: the consumer queues it (IDs only), the next run updates the CI.
    renamed = f"Renamed {uuid.uuid4().hex[:6]}"
    patched = await world.call(
        "PATCH",
        f"/assets/{made[0]['id']}",
        a,
        a.admin,
        json={"name": renamed},
        headers=_match(made[0]["version"]),
    )
    assert patched.status_code == 200, patched.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await sync.on_asset_changed(
            EventEnvelope.model_construct(payload={"asset_id": made[0]["id"]}), session
        )
    queued = await world.sql(
        "SELECT asset_ids FROM cmdb_sync_runs WHERE tenant_id = $1 AND rule_id = $2"
        " AND status = 'queued' AND trigger = 'asset_changed'",
        a.tenant,
        uuid.UUID(rule.json()["id"]),
    )
    assert queued
    assert made[0]["id"] in str(queued[0]["asset_ids"])
    await sync.run_tenant(world.app.state.db, a.tenant)
    assert (await _ci_of(world, a, made[0]["id"]))["name"] == renamed


async def test_a_hand_set_value_is_kept_never_overwritten(world: World) -> None:
    a = world.a
    product, made = await _assets(world, a, 1)
    located = await world.call(
        "PATCH",
        f"/assets/{made[0]['id']}",
        a,
        a.admin,
        json={"location": "Floor 1"},
        headers=_match(made[0]["version"]),
    )
    assert located.status_code == 200, located.text
    rule = (await _rule(world, a, await _body(world, a, product))).json()
    await _run(world, a, rule)
    ci = await _ci_of(world, a, made[0]["id"])
    assert ci["description"] == "Floor 1"
    typed = await world.call(
        "PATCH",
        f"{BASE}/cis/{ci['id']}",
        a,
        a.admin,
        json={"description": "Typed by hand"},
        headers=_match(ci["version"]),
    )
    assert typed.status_code == 200, typed.text
    assert typed.json()["sources"]["description"]["source"] == "hand"
    moved = await world.call(
        "PATCH",
        f"/assets/{made[0]['id']}",
        a,
        a.admin,
        json={"location": "Floor 2"},
        headers=_match(located.json()["version"]),
    )
    assert moved.status_code == 200, moved.text
    run = await _run(world, a, rule)
    assert run["kept_count"] == 1, run
    assert [i["kept"] for i in run["items"]] == [["description"]]
    assert (await _ci_of(world, a, made[0]["id"]))["description"] == "Typed by hand"


async def test_the_source_order_is_checked_and_audited_with_before_and_after(world: World) -> None:
    a = world.a
    found = await world.call("GET", f"{BASE}/settings/source-precedence", a, a.admin)
    assert found.status_code == 200, found.text
    order = found.json()["order"]
    assert order[0] == "hand"
    version = found.json()["version"]
    hand_last = [*order[1:], "hand"]
    refused = await world.call(
        "PUT",
        f"{BASE}/settings/source-precedence",
        a,
        a.admin,
        json={"order": hand_last},
        headers=_match(version),
    )
    assert refused.status_code == 422, refused.text
    assert field_codes(refused)["order"] == "cmdb_source_hand_first"
    synced_first = ["asset_sync", *[s for s in order if s != "asset_sync"]]
    changed = await world.call(
        "PUT",
        f"{BASE}/settings/source-precedence",
        a,
        a.admin,
        json={"order": order, "overrides": {"site_id": synced_first}},
        headers=_match(version),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["overrides"] == {"site_id": synced_first}
    stale = await world.call(
        "PUT",
        f"{BASE}/settings/source-precedence",
        a,
        a.admin,
        json={"order": order},
        headers=_match(version),
    )
    assert stale.status_code == 409, stale.text
    entries = await world.sql(
        "SELECT actor_id, details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'cmdb.source_precedence_changed' AND outcome = 'done'"
        " ORDER BY occurred_at DESC LIMIT 1",
        a.tenant,
    )
    assert entries
    assert str(entries[0]["actor_id"]) == str(a.admin)
    details = str(entries[0]["details"])
    assert "before" in details
    assert "after" in details
    assert "site_id" in details
    # Back to the defaults for the other tests.
    reset = await world.call(
        "PUT",
        f"{BASE}/settings/source-precedence",
        a,
        a.admin,
        json={"order": order},
        headers=_match(changed.json()["version"]),
    )
    assert reset.status_code == 200, reset.text


# --- what a reader may see (the coordinator's 1 and 6; lane C 5) ---------------------------------


async def test_run_items_and_sources_show_only_what_the_reader_may_see(world: World) -> None:
    a = world.a
    await world.sql(
        "UPDATE tenant_subscriptions SET edition = 'enterprise' WHERE tenant_id = $1", a.tenant
    )
    masked = (await _field(world, a, f"Rack row {uuid.uuid4().hex[:4]}", "workstation"))["key"]
    product, made = await _assets(world, a, 1)
    rule = (
        await _rule(
            world,
            a,
            await _body(
                world, a, product, field_map={"name": "name", f"custom.{masked}": "location"}
            ),
        )
    ).json()
    located = await world.call(
        "PATCH",
        f"/assets/{made[0]['id']}",
        a,
        a.admin,
        json={"location": "Row A"},
        headers=_match(made[0]["version"]),
    )
    assert located.status_code == 200, located.text
    await _run(world, a, rule)
    ci = await _ci_of(world, a, made[0]["id"])
    assert f"custom.{masked}" in ci["sources"]
    # A hand edit, then the asset moves: the run keeps the custom value.
    typed = await world.call(
        "PATCH",
        f"{BASE}/cis/{ci['id']}",
        a,
        a.admin,
        json={"custom": {masked: "Row by hand"}},
        headers=_match(ci["version"]),
    )
    assert typed.status_code == 200, typed.text
    moved = await world.call(
        "PATCH",
        f"/assets/{made[0]['id']}",
        a,
        a.admin,
        json={"location": "Row B"},
        headers=_match(located.json()["version"]),
    )
    assert moved.status_code == 200, moved.text
    run = await _run(world, a, rule)
    assert [i["kept"] for i in run["items"]] == [[f"custom.{masked}"]]

    # A configurer who sees only servers, with the custom field masked for them.
    reader = await role(
        world,
        a,
        f"Sync reader {uuid.uuid4().hex[:4]}",
        [("cmdb.configure", "all"), ("cmdb.view", "all"), ("assets.view", "all")],
    )
    assert (
        await world.call("PUT", f"/users/{a.requester2}/roles/{reader}", a, a.admin)
    ).status_code == 204
    types = await _types(world, a)
    ruled = await world.call(
        "POST",
        "/resource-access/rules",
        a,
        a.admin,
        json={
            "role_id": str(reader),
            "resource": "ci",
            "criteria": {"type_ids": [types["server"]["id"]]},
        },
        headers=_new(),
    )
    assert ruled.status_code == 201, ruled.text
    for role_id in (reader, await _role_id(world, a, "requester")):
        await field_rule(world, a, role_id, f"custom.{masked}", "masked")
    try:
        seen = await world.call("GET", f"{BASE}/sync-runs/{run['id']}", a, a.requester2)
        assert seen.status_code == 200, seen.text
        item = seen.json()["items"][0]
        assert item["ci_restricted"] is True
        assert item["ci_id"] is None
        assert item["ci_label"] is None
        assert item["kept"] == []
        assert ci["id"] not in seen.text
        # A reader who sees the CI but not the masked field: no source for it.
        server_role = await role(
            world, a, f"Sync wide {uuid.uuid4().hex[:4]}", [("cmdb.view", "all")]
        )
        await world.call("DELETE", f"/users/{a.requester2}/roles/{reader}", a, a.admin)
        assert (
            await world.call("PUT", f"/users/{a.requester2}/roles/{server_role}", a, a.admin)
        ).status_code == 204
        await field_rule(world, a, server_role, f"custom.{masked}", "masked")
        record = await world.call("GET", f"{BASE}/cis/{ci['id']}", a, a.requester2)
        assert record.status_code == 200, record.text
        assert f"custom.{masked}" not in record.json()["sources"]
        assert "name" in record.json()["sources"]
        await world.call("DELETE", f"/users/{a.requester2}/roles/{server_role}", a, a.admin)
    finally:
        await world.call("DELETE", f"/users/{a.requester2}/roles/{reader}", a, a.admin)


async def test_a_ci_from_before_sources_keeps_its_hand_values(world: World) -> None:
    """A CI made by hand before 0191 has no stamps: its values count as hand-set."""
    a = world.a
    product, made = await _assets(world, a, 1)
    old = await _ci(world, a, "Before sources", "workstation", description="Typed long ago")
    assert old.status_code == 201, old.text
    await world.sql(
        "UPDATE cmdb_cis SET sources = '{}'::jsonb, asset_id = $2 WHERE tenant_id = $1 AND id = $3",
        a.tenant,
        uuid.UUID(made[0]["id"]),
        uuid.UUID(old.json()["id"]),
    )
    located = await world.call(
        "PATCH",
        f"/assets/{made[0]['id']}",
        a,
        a.admin,
        json={"location": "Somewhere new"},
        headers=_match(made[0]["version"]),
    )
    assert located.status_code == 200, located.text
    rule = (await _rule(world, a, await _body(world, a, product))).json()
    run = await _run(world, a, rule)
    assert run["kept_count"] == 1, run
    after = await world.call("GET", f"{BASE}/cis/{old.json()['id']}", a, a.admin)
    assert after.json()["description"] == "Typed long ago"
    assert after.json()["name"] == "Before sources"
