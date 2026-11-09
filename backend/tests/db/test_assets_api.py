"""The asset record over HTTP (WP-049a s2; parity 07 §3: REQ-AST-001, 002, 004, 007, 008).

The incident world: org A has an admin (every permission) and technicians (assets.view at all,
assets.manage at group scope); org B is there for isolation.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.assets.service.realtime import ASSET_CHANGED, RECORD_KIND, ROUTES
from app.shared.events import EventEnvelope
from app.shared.realtime import record
from tests.db import test_incidents_api
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _match, _new

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"


async def _types(world: World, org: Org) -> dict[str, dict[str, Any]]:
    found = await world.call("GET", f"{BASE}/product-types", org, org.admin)
    assert found.status_code == 200, found.text
    return {t["api_name"]: t for t in found.json()}


async def _product(world: World, org: Org, api_name: str, name: str) -> str:
    types = await _types(world, org)
    made = await world.call(
        "POST",
        f"{BASE}/products",
        org,
        org.admin,
        json={"product_type_id": types[api_name]["id"], "name": name},
        headers=_new(),
    )
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


async def _add(world: World, org: Org, body: dict[str, Any], user: uuid.UUID | None = None) -> Any:  # noqa: ANN401 - httpx response
    return await world.call("POST", BASE, org, user or org.admin, json=body, headers=_new())


async def _patch(world: World, org: Org, asset: dict[str, Any], body: dict[str, Any]) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "PATCH",
        f"{BASE}/{asset['id']}",
        org,
        org.admin,
        json=body,
        headers=_match(asset["version"]),
    )


async def test_new_assets_get_tags_from_the_pattern_and_start_in_stock(world: World) -> None:
    a = world.a
    laptop = await _product(world, a, "laptop", "ThinkPad T14")
    first = await _add(world, a, {"name": "Aisha's laptop", "product_id": laptop})
    assert first.status_code == 201, first.text
    second = (await _add(world, a, {"name": "Spare laptop", "product_id": laptop})).json()
    assert first.json()["tag"] == "AST-1"
    assert second["tag"] == "AST-2"
    states = {s["id"]: s for s in (await world.call("GET", f"{BASE}/states", a, a.admin)).json()}
    assert states[second["state_id"]]["code"] == "in_stock"
    types = await _types(world, a)
    assert second["product_type_id"] == types["laptop"]["id"]
    # A type with its own pattern counts on its own; a typed tag is kept.
    lt = types["laptop"]
    changed = await world.call(
        "PATCH",
        f"{BASE}/product-types/{lt['id']}",
        a,
        a.admin,
        json={"tag_pattern": "LT-{n}"},
        headers=_match(lt["version"]),
    )
    assert changed.status_code == 200, changed.text
    third = (await _add(world, a, {"name": "New laptop", "product_id": laptop})).json()
    assert third["tag"] == "LT-1"
    typed = (await _add(world, a, {"name": "Typed", "product_id": laptop, "tag": "X-9"})).json()
    assert typed["tag"] == "X-9"


async def test_tags_and_serials_are_unique_and_the_refusal_names_the_holder(world: World) -> None:
    a = world.a
    laptop = await _product(world, a, "laptop", "Latitude")
    held = (
        await _add(world, a, {"name": "Held", "product_id": laptop, "serial_number": "SN-100"})
    ).json()
    twin = await _add(world, a, {"name": "Twin", "product_id": laptop, "serial_number": "sn-100"})
    assert field_codes(twin) == {"serial_number": "asset_serial_number_taken"}
    assert twin.json()["errors"][0]["params"] == {"asset": held["tag"]}
    same_tag = await _add(world, a, {"name": "Twin", "product_id": laptop, "tag": held["tag"]})
    assert field_codes(same_tag) == {"tag": "asset_tag_taken"}
    bad = await _add(world, a, {"name": "Bad", "product_id": laptop, "serial_number": "a b"})
    assert field_codes(bad) == {"serial_number": "asset_identifier_invalid"}
    # In the trash it still holds them: a restore never collides, a tag is never reused.
    gone = await world.call(
        "DELETE", f"{BASE}/{held['id']}", a, a.admin, headers=_match(held["version"])
    )
    assert gone.status_code == 204, gone.text
    again = await _add(world, a, {"name": "Again", "product_id": laptop, "serial_number": "SN-100"})
    assert field_codes(again) == {"serial_number": "asset_serial_number_taken"}
    trash = await world.call("GET", f"{BASE}/trash", a, a.admin)
    assert [t["id"] for t in trash.json()["items"]] == [held["id"]]
    restored = await world.call("POST", f"{BASE}/{held['id']}/restore", a, a.admin)
    assert restored.status_code == 200, restored.text
    assert restored.json()["tag"] == held["tag"]


async def test_only_it_assets_take_a_slot_of_the_plan(world: World) -> None:
    a = world.a
    await world.sql(
        "UPDATE tenant_subscriptions SET limits = '{\"assets\": 1}'::jsonb WHERE tenant_id = $1",
        a.tenant,
    )
    await world.app.state.entitlements.invalidate(a.tenant)  # the plan changed under it
    laptop = await _product(world, a, "laptop", "MacBook")
    chair = await _product(world, a, "furniture", "Office chair")
    first = await _add(world, a, {"name": "One", "product_id": laptop})
    assert first.status_code == 201, first.text
    refused = await _add(world, a, {"name": "Two", "product_id": laptop})
    assert problem(refused) == (403, "asset_limit_reached")
    # Non-IT assets are unlimited (D-141).
    for n in range(3):
        assert (
            await _add(world, a, {"name": f"Chair {n}", "product_id": chair})
        ).status_code == 201
    # The trash frees the slot.
    one = first.json()
    await world.call("DELETE", f"{BASE}/{one['id']}", a, a.admin, headers=_match(one["version"]))
    assert (await _add(world, a, {"name": "Two", "product_id": laptop})).status_code == 201
    # ... and a restore needs one again.
    refused = await world.call("POST", f"{BASE}/{one['id']}/restore", a, a.admin)
    assert problem(refused) == (403, "asset_limit_reached")


async def test_assets_are_found_by_any_identifier_and_filtered(world: World) -> None:
    a = world.a
    laptop = await _product(world, a, "laptop", "XPS 13")
    await _add(
        world,
        a,
        {
            "name": "Finance laptop",
            "product_id": laptop,
            "serial_number": "CN0X7Q",
            "barcode": "4006381333931",
        },
    )
    await _add(world, a, {"name": "Reception PC", "product_id": laptop})
    for query, expected in (
        ("CN0X7Q", ["Finance laptop"]),
        ("4006381333931", ["Finance laptop"]),
        ("reception", ["Reception PC"]),
    ):
        found = await world.call("GET", f"{BASE}?search={query}", a, a.tech_a)
        assert found.status_code == 200, found.text
        assert [x["name"] for x in found.json()["items"]] == expected, query
    types = await _types(world, a)
    by_type = await world.call(
        "GET",
        f"{BASE}?filter="
        + json.dumps({"field": "product_type_id", "op": "eq", "value": types["laptop"]["id"]}),
        a,
        a.admin,
    )
    assert len(by_type.json()["items"]) == 2


async def test_vendor_site_and_custom_fields_are_checked(world: World) -> None:
    a = world.a
    laptop = await _product(world, a, "laptop", "Surface")
    vendor = await world.call(
        "POST", "/procurement/vendors", a, a.admin, json={"name": "Dell"}, headers=_new()
    )
    assert vendor.status_code == 201, vendor.text
    field = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "asset", "field_type": "text", "labels": {"en": "Cost centre"}},
    )
    assert field.status_code == 201, field.text
    key = field.json()["key"]
    made = await _add(
        world,
        a,
        {
            "name": "With vendor",
            "product_id": laptop,
            "vendor_id": vendor.json()["id"],
            "purchase_price": "1000.00",
            "purchase_tax": "170.00",
            "custom": {key: "CC-42"},
        },
    )
    assert made.status_code == 201, made.text
    asset = made.json()
    assert asset["purchase_total"] == "1170.00"
    assert asset["custom"] == {key: "CC-42"}
    found = await world.call("GET", f"{BASE}?search=CC-42", a, a.admin)
    assert [x["id"] for x in found.json()["items"]] == [asset["id"]]
    missing = await _patch(
        world, a, asset, {"vendor_id": str(uuid.uuid4()), "site_id": str(uuid.uuid4())}
    )
    assert field_codes(missing) == {"vendor_id": "vendor_not_found", "site_id": "site_not_found"}
    # A vendor still named by an asset cannot be deleted.
    v = vendor.json()
    blocked = await world.call(
        "DELETE", f"/procurement/vendors/{v['id']}", a, a.admin, headers=_match(v["version"])
    )
    assert problem(blocked) == (409, "vendor_in_use")


async def test_saves_keep_history_events_audit_and_reach_screens(world: World) -> None:
    a = world.a
    laptop = await _product(world, a, "laptop", "Pixelbook")
    asset = (await _add(world, a, {"name": "Old name", "product_id": laptop})).json()
    changed = await _patch(world, a, asset, {"name": "New name", "location": "Floor 3"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    stale = await _patch(world, a, asset, {"name": "Lost"})
    assert problem(stale) == (409, "version_conflict")
    history = await world.call("GET", f"{BASE}/{asset['id']}/history", a, a.tech_a)
    assert history.status_code == 200, history.text
    latest = history.json()["items"][0]
    assert {c["field"] for c in latest["changes"]} == {"name", "location"}
    assert latest["actor_name"]
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'assets.asset.changed' ORDER BY created_at",
        a.tenant,
    )
    envelopes = [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]
    # IDs and field names only (§8.2): never a name, serial or price.
    assert all(
        set(e.payload) <= {"asset_id", "action", "changed_fields", "site_id"} for e in envelopes
    )
    assert envelopes[-1].payload["changed_fields"] == ["location", "name"]
    audit = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1 AND outcome = 'done'"
        " AND action IN ('asset.created', 'asset.updated')",
        a.tenant,
    )
    assert sorted(r["action"] for r in audit) == ["asset.created", "asset.updated"]
    route = next(r for r in ROUTES if envelopes[-1].event_type in r.event_types)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(envelopes[-1], session)
    own = next(
        p
        for p in effects.publications
        if p.channel == record(a.tenant, RECORD_KIND, uuid.UUID(asset["id"]))
    )
    assert own.type == ASSET_CHANGED
    assert own.fields == ("location", "name")
    assert own.version == 2
    assert len(effects.publications) > 1  # the list hears of it too


async def test_technicians_manage_assets_in_their_reach_only(world: World) -> None:
    a = world.a
    laptop = await _product(world, a, "laptop", "Chromebook")
    mine = await _add(world, a, {"name": "No site", "product_id": laptop}, a.tech_a)
    assert mine.status_code == 201, mine.text
    renamed = await world.call(
        "PATCH",
        f"{BASE}/{mine.json()['id']}",
        a,
        a.tech_a,
        json={"name": "Still no site"},
        headers=_match(1),
    )
    assert renamed.status_code == 200, renamed.text
    elsewhere = (
        await _add(world, a, {"name": "Other site", "product_id": laptop, "site_id": str(a.s2)})
    ).json()
    refused = await world.call(
        "PATCH",
        f"{BASE}/{elsewhere['id']}",
        a,
        a.tech_a,
        json={"name": "Mine now"},
        headers=_match(elsewhere["version"]),
    )
    assert problem(refused)[0] == 403  # it may see it (view: all), not change it


async def test_assets_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    laptop = await _product(world, a, "laptop", "Only A")
    asset = (await _add(world, a, {"name": "A's", "product_id": laptop})).json()
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM assets")) == 0
        assert (await session.execute(text("UPDATE assets SET name = 'x'"))).rowcount == 0
    assert problem(await world.call("GET", f"{BASE}/{asset['id']}", b, b.admin)) == (
        404,
        "asset_not_found",
    )
