"""The asset catalogue over HTTP (WP-049a session 1; parity 07 §2, §4; D-141; Appendix A).

The incident world of test_incidents_api.py: org A has an admin (every permission) and
technicians (assets.view, no catalogue rights); org B is there for isolation.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.assets.service.realtime import CATALOGUE_CHANGED, ROUTES
from app.shared.events import EventEnvelope
from app.shared.realtime import broadcast
from tests.db import test_incidents_api
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _match, _new

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"
TABLES = (
    "asset_settings",
    "asset_states",
    "asset_life_cycles",
    "asset_life_cycle_transitions",
    "asset_product_types",
    "asset_products",
)


async def _get(world: World, org: Org, path: str, user: uuid.UUID | None = None) -> Any:  # noqa: ANN401 - JSON
    response = await world.call("GET", f"{BASE}{path}", org, user or org.admin)
    assert response.status_code == 200, response.text
    return response.json()


async def _post(world: World, org: Org, path: str, body: dict[str, Any], **kw: Any) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "POST", f"{BASE}{path}", org, kw.get("user", org.admin), json=body, headers=_new()
    )


async def _patch(world: World, org: Org, path: str, version: int, body: dict[str, Any]) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "PATCH", f"{BASE}{path}", org, org.admin, json=body, headers=_match(version)
    )


async def _delete(world: World, org: Org, path: str, version: int) -> Any:  # noqa: ANN401 - httpx response
    return await world.call("DELETE", f"{BASE}{path}", org, org.admin, headers=_match(version))


def _by(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {item[key]: item for item in items}


async def test_a_new_tenant_gets_the_appendix_a_catalogue(world: World) -> None:
    a = world.a
    # A technician reads it (the asset form needs it); the defaults are made on first use.
    states = _by(await _get(world, a, "/states", a.tech_a), "code")
    assert list(states) == [
        "in_stock", "in_use", "on_loan", "in_repair", "missing", "retired", "disposed"
    ]  # fmt: skip
    assert states["on_loan"]["category"] == "in_use"
    assert states["missing"]["category"] == "retired"
    assert states["disposed"]["system"] is True
    assert states["in_repair"]["reason_required"] is True
    assert states["in_stock"]["names"]["ar"]  # seeded in every language, renamable
    defaults = {s["category"] for s in states.values() if s["is_default_for_category"]}
    assert defaults == {"in_stock", "in_use", "in_repair", "retired", "disposed"}

    cycles = await _get(world, a, "/life-cycles", a.tech_a)
    assert [c["code"] for c in cycles] == ["standard"]
    assert cycles[0]["is_default"] is True
    ids = {s["id"]: code for code, s in states.items()}
    moves = {(ids[m["from_state_id"]], ids[m["to_state_id"]]) for m in cycles[0]["moves"]}
    assert len(moves) == 21
    assert ("retired", "disposed") in moves
    assert not [m for m in moves if m[0] == "disposed"]  # disposed is the end
    reinstate = next(
        m
        for m in cycles[0]["moves"]
        if (ids[m["from_state_id"]], ids[m["to_state_id"]]) == ("retired", "in_stock")
    )
    assert reinstate["permission"] == "assets.reinstate"

    types = _by(await _get(world, a, "/product-types", a.tech_a), "api_name")
    assert len(types) == 35
    assert types["laptop"]["parent_id"] == types["computer"]["id"]
    assert (types["laptop"]["category"], types["laptop"]["kind"]) == ("it", "asset")
    assert (types["furniture"]["category"], types["furniture"]["kind"]) == ("non_it", "asset")
    assert types["mouse"]["kind"] == "component"
    assert types["paper"]["kind"] == "consumable"

    settings = await _get(world, a, "/settings", a.tech_a)
    assert settings["tag_pattern"] == "AST-{n}"
    assert settings["cost_includes_tax"] is True  # D-141
    assert settings["copy_limit"] == 50

    # Asking again seeds nothing twice.
    assert len(await _get(world, a, "/product-types")) == 35
    rows = await world.sql("SELECT count(*) AS n FROM asset_states WHERE tenant_id = $1", a.tenant)
    assert rows[0]["n"] == 7


async def test_only_catalogue_admins_change_it(world: World) -> None:
    a = world.a
    types = _by(await _get(world, a, "/product-types"), "api_name")
    body = {
        "api_name": "tablet_pro",
        "names": {"en": "Tablet Pro"},
        "parent_id": types["mobile_device"]["id"],
    }
    assert problem(await _post(world, a, "/product-types", body, user=a.tech_a))[0] == 403
    settings = await _get(world, a, "/settings")
    denied = await world.call(
        "PATCH",
        f"{BASE}/settings",
        a,
        a.tech_a,
        json={"copy_limit": 5},
        headers=_match(settings["version"]),
    )
    assert problem(denied)[0] == 403
    # A requester has no assets.view: not even the catalogue.
    assert problem(await world.call("GET", f"{BASE}/states", a, a.requester))[0] == 403


async def test_product_type_tree_rules(world: World) -> None:
    a = world.a
    types = _by(await _get(world, a, "/product-types"), "api_name")
    created = await _post(
        world,
        a,
        "/product-types",
        {
            "api_name": "rugged_tablet",
            "names": {"en": "Rugged tablet"},
            "parent_id": types["tablet"]["id"],
        },
    )
    assert created.status_code == 201, created.text
    child = created.json()
    assert (child["category"], child["kind"]) == ("it", "asset")  # inherited

    # A type under a parent can't pick its own category.
    refused = await _patch(
        world, a, f"/product-types/{child['id']}", child["version"], {"category": "non_it"}
    )
    assert field_codes(refused) == {"category": "asset_product_type_inherited"}
    # No loops: a type can't move under its own child.
    mobile = types["mobile_device"]
    loop = await _patch(
        world, a, f"/product-types/{mobile['id']}", mobile["version"], {"parent_id": child["id"]}
    )
    assert field_codes(loop) == {"parent_id": "asset_product_type_cycle"}
    # The API name is unique per tenant.
    again = await _post(
        world,
        a,
        "/product-types",
        {"api_name": "laptop", "names": {"en": "x"}, "parent_id": types["computer"]["id"]},
    )
    assert field_codes(again) == {"api_name": "asset_api_name_taken"}
    # A top-level type needs its category and kind.
    top = await _post(
        world, a, "/product-types", {"api_name": "lab_kit", "names": {"en": "Lab kit"}}
    )
    assert set(field_codes(top)) == {"category", "kind"}

    # Changing a top-level type's category flows down the tree (D-141).
    tops = types["non_it_assets"]
    moved = await _patch(
        world, a, f"/product-types/{tops['id']}", tops["version"], {"category": "it"}
    )
    assert moved.status_code == 200, moved.text
    after = _by(await _get(world, a, "/product-types"), "api_name")
    assert after["vehicle"]["category"] == "it"

    # A type with types below it can't be deleted; one with products neither.
    busy = await _delete(
        world, a, f"/product-types/{types['computer']['id']}", types["computer"]["version"]
    )
    assert problem(busy) == (409, "asset_product_type_has_children")
    product = await _post(world, a, "/products", {"product_type_id": child["id"], "name": "RT-10"})
    assert product.status_code == 201, product.text
    used = await _delete(world, a, f"/product-types/{child['id']}", child["version"])
    assert problem(used) == (409, "asset_product_type_in_use")


async def test_products_keep_price_and_tax_apart(world: World) -> None:
    a = world.a
    types = _by(await _get(world, a, "/product-types"), "api_name")
    body = {
        "product_type_id": types["laptop"]["id"],
        "name": "  ThinkBook 14 ",
        "manufacturer": "Lenovo",
        "price": "1000.00",
        "tax": "170.00",
        "currency": "PKR",
        "depreciation_method": "straight_line",
        "useful_life_years": 3,
    }
    first = await _post(world, a, "/products", body)
    assert first.status_code == 201, first.text
    product = first.json()
    assert product["name"] == "ThinkBook 14"
    assert (product["price"], product["tax"], product["total"]) == ("1000.00", "170.00", "1170.00")

    # Filter by type and manufacturer.
    page = await _get(
        world, a, f"/products?product_type_id={types['laptop']['id']}&manufacturer=Lenovo"
    )
    assert [p["id"] for p in page["items"]] == [product["id"]]

    # If-Match: a stale version is refused.
    changed = await _patch(
        world, a, f"/products/{product['id']}", product["version"], {"tax": None}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["total"] == "1000.00"
    stale = await _patch(world, a, f"/products/{product['id']}", product["version"], {"name": "x"})
    assert problem(stale) == (409, "version_conflict")

    bad = await _post(world, a, "/products", {**body, "currency": "rs"})
    assert problem(bad)[0] == 422
    gone = await _delete(world, a, f"/products/{product['id']}", changed.json()["version"])
    assert gone.status_code == 204, gone.text
    assert problem(await world.call("GET", f"{BASE}/products/{product['id']}", a, a.admin)) == (
        404,
        "asset_product_not_found",
    )


async def test_states_keep_one_default_per_category(world: World) -> None:
    a = world.a
    created = await _post(
        world,
        a,
        "/states",
        {
            "code": "with_courier",
            "names": {"en": "With courier"},
            "category": "in_stock",
            "is_default_for_category": True,
        },
    )
    assert created.status_code == 201, created.text
    states = _by(await _get(world, a, "/states"), "code")
    assert states["with_courier"]["is_default_for_category"] is True
    assert states["in_stock"]["is_default_for_category"] is False  # handed over

    taken = await _post(
        world, a, "/states", {"code": "in_use", "names": {"en": "x"}, "category": "in_use"}
    )
    assert field_codes(taken) == {"code": "asset_state_code_taken"}
    protected = await _delete(
        world, a, f"/states/{states['disposed']['id']}", states["disposed"]["version"]
    )
    assert problem(protected) == (409, "asset_state_protected")
    in_use = await _delete(
        world, a, f"/states/{states['missing']['id']}", states["missing"]["version"]
    )
    assert problem(in_use) == (409, "asset_state_in_use")  # the standard life cycle uses it
    system = await _patch(
        world,
        a,
        f"/states/{states['on_loan']['id']}",
        states["on_loan"]["version"],
        {"category": "in_stock"},
    )
    assert field_codes(system) == {"category": "asset_state_system"}

    # Renaming changes only the display text; the code stays.
    renamed = await _patch(
        world, a, f"/states/{states['missing']['id']}", states["missing"]["version"],
        {"names": {"en": "Lost", "ar": "ضائع"}},
    )  # fmt: skip
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["code"], renamed.json()["names"]["en"]) == ("missing", "Lost")


async def test_life_cycles(world: World) -> None:
    a = world.a
    states = _by(await _get(world, a, "/states"), "code")
    move = {"from_state_id": states["in_stock"]["id"], "to_state_id": states["in_use"]["id"]}
    dup = await _post(
        world,
        a,
        "/life-cycles",
        {"code": "leased", "names": {"en": "Leased"}, "moves": [move, move]},
    )
    assert field_codes(dup) == {"moves.1": "asset_move_duplicate"}
    created = await _post(
        world, a, "/life-cycles", {"code": "leased", "names": {"en": "Leased"}, "moves": [move]}
    )
    assert created.status_code == 201, created.text
    cycle = created.json()
    assert len(cycle["moves"]) == 1

    made_default = await _patch(
        world, a, f"/life-cycles/{cycle['id']}", cycle["version"], {"is_default": True}
    )
    assert made_default.status_code == 200, made_default.text
    cycles = _by(await _get(world, a, "/life-cycles"), "code")
    assert cycles["leased"]["is_default"] is True
    assert cycles["standard"]["is_default"] is False
    refused = await _delete(world, a, f"/life-cycles/{cycle['id']}", made_default.json()["version"])
    assert problem(refused) == (409, "asset_life_cycle_protected")
    removable = await _delete(
        world, a, f"/life-cycles/{cycles['standard']['id']}", cycles["standard"]["version"]
    )
    assert removable.status_code == 204, removable.text


async def test_saves_keep_history_events_and_audit(world: World) -> None:
    a = world.a
    settings = await _get(world, a, "/settings")
    changed = await _patch(world, a, "/settings", settings["version"], {"cost_includes_tax": False})
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == settings["version"] + 1
    stale = await _patch(world, a, "/settings", settings["version"], {"copy_limit": 10})
    assert problem(stale) == (409, "version_conflict")
    bad = await _patch(world, a, "/settings", changed.json()["version"], {"tag_pattern": "AST"})
    assert field_codes(bad) == {"tag_pattern": "asset_tag_pattern_invalid"}

    history = await world.sql(
        "SELECT field FROM field_changes WHERE record_type = 'asset_settings' AND tenant_id = $1",
        a.tenant,
    )
    assert {r["field"] for r in history} == {"cost_includes_tax"}
    events = await world.sql(
        "SELECT envelope->'payload' AS payload FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'assets.catalogue.changed'",
        a.tenant,
    )
    payloads = [json.loads(e["payload"]) for e in events]
    assert {"kind": "settings", "item_id": None, "action": "updated",
            "changed_fields": ["cost_includes_tax"]} in payloads  # fmt: skip
    # IDs, codes and field names only (§8.2): never a name or a price.
    assert all(set(p) == {"kind", "item_id", "action", "changed_fields"} for p in payloads)
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE action = 'asset.settings_changed'"
        " AND outcome = 'done'"
        " AND tenant_id = $1",
        a.tenant,
    )
    assert audit[0]["n"] == 1


async def test_asset_catalogue_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    types = _by(await _get(world, a, "/product-types"), "api_name")
    made = await _post(
        world, a, "/products", {"product_type_id": types["laptop"]["id"], "name": "A only"}
    )
    assert made.status_code == 201, made.text
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in TABLES:
            count = await session.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608 - fixed names
            assert count == 0, table
        for statement in (
            "UPDATE asset_settings SET copy_limit = 1",
            "UPDATE asset_states SET sort = 9",
            "UPDATE asset_life_cycles SET is_default = false",
            "UPDATE asset_product_types SET sort = 9",
            "UPDATE asset_products SET name = 'x'",
            "DELETE FROM asset_life_cycle_transitions",
        ):
            assert (await session.execute(text(statement))).rowcount == 0, statement
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO asset_states (id, tenant_id, code, names, category)"
                    " VALUES (:id, :other, 'stolen', '{\"en\": \"x\"}', 'in_stock')"
                ),
                {"id": uuid.uuid4(), "other": a.tenant},
            )
    assert problem(await world.call("GET", f"{BASE}/products/{made.json()['id']}", b, b.admin)) == (
        404,
        "asset_product_not_found",
    )
    # B's own catalogue is its own defaults, untouched by A.
    assert len(await _get(world, b, "/product-types")) == 35


async def test_life_cycle_moves_are_replaced_and_checked(world: World) -> None:
    a = world.a
    states = _by(await _get(world, a, "/states"), "code")
    cycles = _by(await _get(world, a, "/life-cycles"), "code")
    standard = cycles["standard"]
    keep = [m for m in standard["moves"] if m["from_state_id"] == states["in_stock"]["id"]]
    replaced = await _patch(
        world,
        a,
        f"/life-cycles/{standard['id']}",
        standard["version"],
        {
            "names": {"en": "Shop floor", "ur": "فلور"},
            "moves": [{**keep[0], "reason_required": True}],
        },
    )
    assert replaced.status_code == 200, replaced.text
    body = replaced.json()
    assert (len(body["moves"]), body["moves"][0]["reason_required"]) == (1, True)
    assert body["code"] == "standard"  # renaming changes the display text only
    history = await world.sql(
        "SELECT field FROM field_changes WHERE record_type = 'asset_life_cycle' AND record_id = $1",
        uuid.UUID(standard["id"]),
    )
    assert {"names", "moves"} <= {r["field"] for r in history}
    unknown = {"from_state_id": str(uuid.uuid4()), "to_state_id": states["in_use"]["id"]}
    bad = await _patch(
        world, a, f"/life-cycles/{standard['id']}", body["version"], {"moves": [unknown]}
    )
    assert field_codes(bad) == {"moves.0": "asset_state_not_found"}
    keep_default = await _patch(
        world, a, f"/life-cycles/{standard['id']}", body["version"], {"is_default": False}
    )
    assert field_codes(keep_default) == {"is_default": "asset_life_cycle_default_needed"}
    code = await _post(world, a, "/life-cycles", {"code": "Bad Code", "names": {"en": "x"}})
    assert set(field_codes(code)) == {"code"}
    # A life cycle a product type uses stays.
    extra = await _post(world, a, "/life-cycles", {"code": "spare", "names": {"en": "Spare"}})
    assert extra.status_code == 201, extra.text
    types = _by(await _get(world, a, "/product-types"), "api_name")
    linked = await _patch(
        world, a, f"/product-types/{types['server']['id']}", types["server"]["version"],
        {"life_cycle_id": extra.json()["id"], "tag_pattern": "SRV-{n}", "icon": "database"},
    )  # fmt: skip
    assert linked.status_code == 200, linked.text
    assert linked.json()["tag_pattern"] == "SRV-{n}"
    in_use = await _delete(world, a, f"/life-cycles/{extra.json()['id']}", extra.json()["version"])
    assert problem(in_use) == (409, "asset_life_cycle_in_use")
    assert in_use.json()["params"] == {"used": 1}


async def test_product_and_state_validation(world: World) -> None:
    a = world.a
    types = _by(await _get(world, a, "/product-types"), "api_name")
    made = await _post(
        world, a, "/products", {"product_type_id": types["router"]["id"], "name": "R1"}
    )
    assert made.status_code == 201, made.text
    product = made.json()
    fetched = await world.call("GET", f"{BASE}/products/{product['id']}", a, a.tech_a)
    assert fetched.status_code == 200, fetched.text
    assert fetched.headers["ETag"] == f'"{product["version"]}"'
    moved = await _patch(
        world, a, f"/products/{product['id']}", product["version"],
        {"product_type_id": str(uuid.uuid4()), "useful_life_years": 3},
    )  # fmt: skip
    assert field_codes(moved) == {"product_type_id": "asset_product_type_not_found"}
    nothing = await _patch(
        world, a, f"/products/{product['id']}", product["version"], {"name": "R1"}
    )
    assert nothing.json()["version"] == product["version"]  # no change, no new version

    state = await _post(
        world, a, "/states", {"code": "x", "names": {"en": ""}, "category": "in_use"}
    )
    assert set(field_codes(state)) == {"code", "names.en"}
    states = _by(await _get(world, a, "/states"), "code")
    default = states["in_use"]
    off = await _patch(
        world, a, f"/states/{default['id']}", default["version"], {"is_default_for_category": False}
    )
    assert field_codes(off) == {"is_default_for_category": "asset_state_default_needed"}
    moved_category = await _patch(
        world, a, f"/states/{default['id']}", default["version"], {"category": "in_stock"}
    )
    assert field_codes(moved_category) == {"category": "asset_state_default_needed"}
    added = await _post(
        world, a, "/states", {"code": "at_desk", "names": {"en": "At desk"}, "category": "in_use"}
    )
    assert added.status_code == 201, added.text
    removed = await _delete(world, a, f"/states/{added.json()['id']}", added.json()["version"])
    assert removed.status_code == 204, removed.text
    settings = await _get(world, a, "/settings")
    ranged = await _patch(world, a, "/settings", settings["version"], {"copy_limit": 900})
    assert problem(ranged)[0] == 422


async def test_catalogue_changes_reach_every_screen_without_ids(world: World) -> None:
    a = world.a
    await _get(world, a, "/states")
    settings = await _get(world, a, "/settings")
    await _patch(world, a, "/settings", settings["version"], {"site_follows_owner": True})
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'assets.catalogue.changed' ORDER BY created_at DESC LIMIT 1",
        a.tenant,
    )
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    route = next(r for r in ROUTES if envelope.event_type in r.event_types)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(envelope, session)
    [publication] = effects.publications
    assert publication.type == CATALOGUE_CHANGED
    assert publication.channel == broadcast(a.tenant)
    assert not publication.ids
