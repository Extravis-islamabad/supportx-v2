"""Route-walk guard: every CMDB and asset record route goes through scope_filter (lane C 6).

Every GET route under /cmdb and /assets is called by a person narrowed by fine-grained access
(ADR-053), and `scope_filter` reports what it filtered (a test-only hook). A route that returns
CIs or assets must have filtered its resource type; every other route must be listed in EXEMPT
with why it holds no such record. A new route that is in neither list, or a record route that
skips `scope_filter`, fails here.

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.identity_access.service.policy import add_scope_hook, remove_scope_hook
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_asset_audits_api import _plan
from tests.db.test_assets_api import _add as add_asset
from tests.db.test_assets_api import _product
from tests.db.test_cmdb_api import _ci, _types
from tests.db.test_incidents_api import World, role
from tests.db.test_knowledge_api import _new
from tooling.route_permissions import api_routes

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

API = "/api/v1"
CIS = "cis"  # the resource type names scope_filter reports
ASSETS = "assets"

# Routes that return CIs or assets: each must filter its own resource type.
MUST: dict[str, str] = {
    "/cmdb/business-views": CIS,
    "/cmdb/business-views/{view_id}": CIS,
    "/cmdb/ci-types": CIS,  # the counts per type (lane C 2)
    "/cmdb/cis": CIS,
    "/cmdb/cis/picker": CIS,
    "/cmdb/cis/trash": CIS,
    "/cmdb/cis/{ci_id}": CIS,
    "/cmdb/cis/{ci_id}/as-of": CIS,
    "/cmdb/cis/{ci_id}/change-type-preview": CIS,
    "/cmdb/cis/{ci_id}/compare": CIS,
    "/cmdb/cis/{ci_id}/history": CIS,
    "/cmdb/cis/{ci_id}/neighbours": CIS,
    "/cmdb/cis/{ci_id}/versions": CIS,
    "/assets": ASSETS,
    "/assets/audits/{audit_id}/items": ASSETS,
    "/assets/bookings": ASSETS,
    "/assets/groups/{group_id}/assets": ASSETS,
    "/assets/held-by": ASSETS,
    "/assets/loanable": ASSETS,
    "/assets/loans": ASSETS,
    "/assets/merge-preview": ASSETS,
    "/assets/picker": ASSETS,
    "/assets/picker/search": ASSETS,
    "/assets/trash": ASSETS,
    "/assets/type-counts": ASSETS,
    "/assets/{asset_id}": ASSETS,
    "/assets/{asset_id}/access": ASSETS,
    "/assets/{asset_id}/disposal": ASSETS,
    "/assets/{asset_id}/financials": ASSETS,
    "/assets/{asset_id}/history": ASSETS,
    "/assets/{asset_id}/holdings": ASSETS,
    "/assets/{asset_id}/linked": ASSETS,
    "/assets/{asset_id}/linked/{kind}": ASSETS,
    "/assets/{asset_id}/links": ASSETS,
    "/assets/{asset_id}/moves": ASSETS,
    "/assets/{asset_id}/notes": ASSETS,
    "/assets/{asset_id}/scans": ASSETS,
}

# Routes that return no CI or asset (configuration, jobs, other record kinds), and why.
EXEMPT: dict[str, str] = {
    "/cmdb/ci-states": "CI states: configuration",
    "/cmdb/relationship-types": "relationship types: configuration",
    "/cmdb/settings": "CMDB settings: configuration",
    "/assets/audits": "audit campaigns, not assets (their items route is checked)",
    "/assets/audits/{audit_id}": "one audit campaign's header, not assets",
    "/assets/availability": (
        "the shared loan pool (D-179): product, site name and busy periods only, never an asset,"
        " a tag or a holder, so alike for everyone who may ask"
    ),
    "/assets/bookable": (
        "the portal's bookable list: tags and names offered alike to every signed-in person when"
        " the tenant turns portal booking on; no staff scope, so no ADR-053 set to apply"
    ),
    "/assets/mine": (
        "the caller's own holdings (portal): every person sees what they hold, staff or not;"
        " ADR-053 narrows staff rights; the record itself stays 404 (test_resource_access_paths)"
    ),
    "/assets/my-bookings": "the caller's own bookings (portal), as /assets/mine",
    "/assets/bulk-jobs": "bulk jobs: the person's own jobs (the runner is visibility-first)",
    "/assets/bulk-jobs/{job_id}": "one bulk job's progress, IDs of what it touched only",
    "/assets/consumable-allocations": "consumables, not assets",
    "/assets/consumables": "consumables, not assets",
    "/assets/consumables/{consumable_id}": "a consumable, not an asset",
    "/assets/consumables/{consumable_id}/ledger": "a consumable's ledger, not assets",
    "/assets/groups": "asset groups (saved filters), not assets",
    "/assets/imports": "import jobs, not assets",
    "/assets/imports/{import_id}": "one import job, not assets",
    "/assets/labels/jobs": "label print jobs, not assets",
    "/assets/labels/jobs/{job_id}/file": "a label job's file",
    "/assets/labels/prints": "label print log, not assets",
    "/assets/life-cycles": "life cycles: configuration",
    "/assets/overdue-rule": "the overdue rule: configuration",
    "/assets/overdue-rule/runs": "the overdue rule's runs: counts only",
    "/assets/overdue-rule/states": "states per product type: configuration",
    "/assets/product-types": "product types: configuration",
    "/assets/products": "products: catalogue",
    "/assets/products/{product_id}": "a product: catalogue",
    "/assets/settings": "asset settings: configuration",
    "/assets/states": "asset states: configuration",
    "/assets/stock-rules": "stock rules: configuration",
    "/assets/{asset_id}/notes/{note_id}/history": "a note's history (the note route is checked)",
}


async def test_every_cmdb_and_asset_record_route_goes_through_scope_filter(world: World) -> None:
    a = world.a
    await world.sql(
        "UPDATE tenant_subscriptions SET edition = 'enterprise' WHERE tenant_id = $1", a.tenant
    )
    types = await _types(world, a)
    ci = (await _ci(world, a, "Walked server", "server")).json()
    other = (await _ci(world, a, "Walked database", "database")).json()
    product = await _product(world, a, "laptop", f"Walk laptop {uuid.uuid4().hex[:6]}")
    asset = (await add_asset(world, a, {"name": "Walked laptop", "product_id": product})).json()
    second = (await add_asset(world, a, {"name": "Walked laptop 2", "product_id": product})).json()
    asset_group = await world.call(
        "POST",
        "/assets/groups",
        a,
        a.admin,
        json={"name": f"Walk {uuid.uuid4().hex[:6]}", "kind": "static"},
        headers=_new(),
    )
    assert asset_group.status_code == 201, asset_group.text
    audit = await _plan(world, a, site_ids=[str(a.s1)])
    view = await world.call(
        "POST",
        "/cmdb/business-views",
        a,
        a.admin,
        json={"name": "Walk view", "base_ci_id": ci["id"], "layout": "radial"},
        headers=_new(),
    )
    # Every right a GET route asks for, so each reaches its read instead of a 403.
    narrowed = await role(
        world,
        a,
        "Walk",
        [
            ("cmdb.view", "all"),
            ("cmdb.edit", "all"),
            ("assets.view", "all"),
            ("assets.manage", "all"),
            ("assets.view_financials", "all"),
        ],
    )
    assert (
        await world.call("PUT", f"/users/{a.requester}/roles/{narrowed}", a, a.admin)
    ).status_code == 204
    for resource, criteria in (
        ("ci", {"type_ids": [types["server"]["id"]]}),
        ("asset", {"site_ids": [str(a.s2)]}),
    ):
        made = await world.call(
            "POST",
            "/resource-access/rules",
            a,
            a.admin,
            json={"role_id": str(narrowed), "resource": resource, "criteria": criteria},
            headers=_new(),
        )
        assert made.status_code == 201, made.text
    now = datetime.now(UTC).isoformat()
    fill = {
        "{ci_id}": ci["id"],
        "{asset_id}": asset["id"],
        "{view_id}": view.json().get("id", str(uuid.uuid4())),
        "{group_id}": asset_group.json()["id"],
        "{kind}": "incident",
        "{audit_id}": audit["id"],
    }
    query = {
        "/assets/held-by": {"kind": "user", "id": str(a.requester)},
        "/assets/merge-preview": {"first": asset["id"], "second": second["id"]},
        "/cmdb/cis/{ci_id}/as-of": {"at": now},
        "/cmdb/cis/{ci_id}/change-type-preview": {"type_id": types["database"]["id"]},
        "/cmdb/cis/{ci_id}/compare": {"from": "1", "to": "1"},
    }
    seen: list[str] = []

    def hook(name: str, permission: str) -> None:
        del permission
        seen.append(name)

    # The app nests its routers; walk them as the route-permission map does.
    routes = sorted(
        {
            path.removeprefix(API)
            for method, path, _dependant, _endpoint in api_routes(world.app)
            if method == "GET" and path.startswith((f"{API}/cmdb", f"{API}/assets"))
        }
    )
    assert routes, "no route found: the walk must cover something"
    unknown = [p for p in routes if p not in MUST and p not in EXEMPT]
    assert unknown == [], f"classify these in MUST or EXEMPT: {unknown}"
    skipped: list[str] = []
    add_scope_hook(hook)
    try:
        for path in routes:
            if path in EXEMPT:
                continue
            target = path
            for marker, value in fill.items():
                target = target.replace(marker, value)
            seen.clear()
            await world.call("GET", target, a, a.requester, params=query.get(path, {}))
            if MUST[path] not in seen:
                skipped.append(path)
    finally:
        remove_scope_hook(hook)
        await world.call("DELETE", f"/users/{a.requester}/roles/{narrowed}", a, a.admin)
    assert skipped == [], f"record routes that skip scope_filter: {skipped}"
    del other
