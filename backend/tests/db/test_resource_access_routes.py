"""Route-walk guard: every CMDB and asset record route goes through scope_filter (lane C 6).

Every GET route under /cmdb and /assets is called by a person narrowed by fine-grained access
(ADR-053), and `scope_filter` reports what it filtered (a test-only hook). A route that returns
CIs or assets must have filtered its resource type; every other route must be listed in EXEMPT
with why it holds no such record. A new route that is in neither list, or a record route that
skips `scope_filter`, fails here.

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

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
    "/cmdb/cis/{ci_id}/impact": CIS,  # S3b: redacts through the same filter
    "/cmdb/cis/{ci_id}/neighbours": CIS,
    "/cmdb/cis/{ci_id}/subscribers": CIS,  # 0185: the CI is read through get_ci first
    "/cmdb/cis/{ci_id}/subscribers/people": CIS,
    "/cmdb/cis/{ci_id}/versions": CIS,
    "/cmdb/merges/preview": CIS,  # S4b: both CIs read through get_visible first
    "/assets": ASSETS,
    "/assets/audits/{audit_id}/items": ASSETS,
    "/assets/bookings": ASSETS,
    "/assets/groups/{group_id}/assets": ASSETS,
    "/assets/held-by": ASSETS,
    "/assets/loanable": ASSETS,
    "/assets/loans": ASSETS,
    "/assets/merge-preview": ASSETS,
    "/assets/picker": ASSETS,
    "/assets/{asset_id}/notes/{note_id}/history": ASSETS,  # reads the asset first (lane C)
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
    "/cmdb/imports": "import jobs, not CIs (S4b)",
    "/cmdb/imports/{import_id}": "one import job: codes and counts, never a CI",
    "/cmdb/imports/{import_id}/problems": "one import job's refused rows: codes only",
    "/cmdb/relationship-types": "relationship types: configuration",
    "/cmdb/settings": "CMDB settings: configuration",
    "/cmdb/settings/source-precedence": "which source wins: configuration (S4a)",
    "/cmdb/sync-rules": "sync rules: configuration (cmdb.configure)",
    "/cmdb/sync-rules/fields": "the fields a sync rule may map: configuration",
    "/cmdb/sync-rules/{rule_id}": "one sync rule: configuration",
    "/cmdb/sync-rules/{rule_id}/runs": "a rule's runs: counts only, no CI or asset",
    "/cmdb/sync-runs/{run_id}": (
        "a run's items: each CI through visible_rows and each asset through asset_refs, an unseen"
        " one a placeholder with no ID (test_cmdb_sync's reader test)"
    ),
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
            ("cmdb.manage", "all"),  # the merge preview (S4b)
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
        "{note_id}": str(uuid.uuid4()),  # the asset is read before the note
    }
    query = {
        "/assets/held-by": {"kind": "user", "id": str(a.requester)},
        "/assets/merge-preview": {"first": asset["id"], "second": second["id"]},
        "/cmdb/merges/preview": {"first": ci["id"], "second": other["id"]},
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


# --- writes (lane C, #560) ------------------------------------------------------------------------

WRITES = ("POST", "PUT", "PATCH", "DELETE")
RECORD_MARKERS = ("{ci_id}", "{asset_id}")


# Bodies for record write routes that check their body before the record: with these the call
# reaches the record, so the walk tests the scope check and not the body's validation.
def _record_bodies(state_id: str, type_id: str, rel_type_id: str, other: str) -> dict[str, Any]:
    today = datetime.now(UTC).date().isoformat()
    return {
        "PATCH /assets/{asset_id}/notes/{note_id}": {"body": "Probe"},
        "POST /assets/{asset_id}/copy": {"count": 1},
        "POST /assets/{asset_id}/costs": {"kind": "service", "incurred_on": today, "amount": "1"},
        "POST /assets/{asset_id}/dispose": {
            "disposed_on": today, "method": "recycling", "reason": "Probe",
        },
        "POST /assets/{asset_id}/links": {"to_asset_id": other, "kind": "connected_to"},
        "POST /assets/{asset_id}/move": {"to_state_id": state_id},
        "POST /assets/{asset_id}/notes": {"body": "Probe"},
        "POST /cmdb/cis/{ci_id}/change-type": {"type_id": type_id},
        "POST /cmdb/cis/{ci_id}/relationships": {
            "type_id": rel_type_id, "direction": "forward", "targets": [other],
        },
        "PUT /assets/{asset_id}/holder": {"kind": "user", "id": other},
    }  # fmt: skip


# Write routes that take CI or asset IDs in their body: each is probed below with an unseen record
# and with an ID that exists nowhere, and the two answers must be the same (nothing tells them
# apart). The probe's body is built in `_body_probes`.
BODY_PROBED = frozenset(
    {
        "POST /assets/loans",
        "POST /assets/bookings",
        "POST /assets/loanable",
        "POST /assets/merges",
        "POST /assets/bulk-moves",
        "POST /assets/bulk-jobs",
        "POST /assets/groups/{group_id}/members",
        "POST /assets/labels",
        "POST /cmdb/cis/from-assets",
        "POST /cmdb/business-views",
        "POST /cmdb/merges",
        "DELETE /cmdb/relationships/{relationship_id}",
        "POST /assets/bookings/{booking_id}/cancel",
        "POST /assets/bookings/{booking_id}/handover",
    }
)

# Routes that accept the request and refuse each record inside it (a bulk job, visibility-first,
# #542): the answer is the same for an unseen record and none, and the job names neither.
ACCEPTED_THEN_REFUSED = frozenset(
    {"/assets/bulk-moves", "/assets/bulk-jobs", "/cmdb/cis/from-assets"}
)

_CONFIG = "configuration: names no CI or asset"
_CATALOGUE = "the product catalogue: names no asset"
_CONSUMABLE = "consumables, not assets (their ledger is scope-checked, test_asset_scope_registers)"
_CREATE = (
    "a create: a record that would fall outside the set is 403 out_of_scope"
    " (test_resource_access_paths)"
)
_AUDIT = (
    "an audit campaign or its items by item ID: items are read through the asset scope"
    " (test_asset_scope_registers)"
)
_OWN = "the caller's own record (portal): no staff scope"
_JOB = "a job by its own ID, started by the caller; its rows were checked when it was made"
_SYNC = (
    "a sync rule (S4a): only an unrestricted author (no ADR-053 narrowing, every asset and CI at"
    " 'all') may write or preview one, so a narrowed person is refused first (test_cmdb_sync)"
)

# Write routes that name no CI or asset, and why they need no probe here.
WRITE_EXEMPT: dict[str, str] = {
    "DELETE /assets/consumables/{consumable_id}": _CONSUMABLE,
    "DELETE /assets/groups/{group_id}": "an asset group (a saved filter), not assets",
    "DELETE /assets/life-cycles/{life_cycle_id}": _CONFIG,
    "DELETE /assets/product-types/{product_type_id}": _CONFIG,
    "DELETE /assets/products/{product_id}": _CATALOGUE,
    "DELETE /assets/states/{state_id}": _CONFIG,
    "DELETE /assets/stock-rules/{rule_id}": _CONFIG,
    "DELETE /cmdb/business-views/{view_id}": "a view by its owner or cmdb.configure; its map is"
    " the reader's own (test_cmdb_relationships)",
    "DELETE /cmdb/ci-states/{state_id}": _CONFIG,
    "DELETE /cmdb/ci-types/{type_id}": _CONFIG,
    "DELETE /cmdb/relationship-types/{type_id}": _CONFIG,
    "PATCH /assets/audits/{audit_id}": _AUDIT,
    "PATCH /assets/audits/{audit_id}/items/{item_id}": _AUDIT,
    "PATCH /assets/consumables/{consumable_id}": _CONSUMABLE,
    "PATCH /assets/groups/{group_id}": "an asset group's own fields, not assets",
    "PATCH /assets/life-cycles/{life_cycle_id}": _CONFIG,
    "PATCH /assets/overdue-rule": _CONFIG,
    "PATCH /assets/product-types/{product_type_id}": _CONFIG,
    "PATCH /assets/products/{product_id}": _CATALOGUE,
    "PATCH /assets/settings": _CONFIG,
    "PATCH /assets/states/{state_id}": _CONFIG,
    "PATCH /assets/stock-rules/{rule_id}": _CONFIG,
    "PATCH /cmdb/business-views/{view_id}": "a view's own fields; its base CI is checked on"
    " create (probed) and its map through the reader's rights",
    "PATCH /cmdb/ci-states/{state_id}": _CONFIG,
    "PATCH /cmdb/ci-types/{type_id}": _CONFIG,
    "PATCH /cmdb/relationship-types/{type_id}": _CONFIG,
    "POST /assets": _CREATE,
    "POST /assets/acknowledgements/{acknowledgement_id}/answer": _OWN,
    "POST /assets/audits": _AUDIT,
    "POST /assets/audits/{audit_id}/close": _AUDIT,
    "POST /assets/audits/{audit_id}/fixes": "fixes by item ID: an item whose asset is unseen"
    " reads as no item (asset_audit_item_not_found), as an unknown one",
    "POST /assets/audits/{audit_id}/scans": "a scan by code, read through `_visible`: an unseen"
    " asset is the same 404 asset_not_found as an unknown code",
    "POST /assets/audits/{audit_id}/start": _AUDIT,
    "POST /assets/consumables": _CONSUMABLE,
    "POST /assets/consumables/{consumable_id}/adjustments": _CONSUMABLE,
    "POST /assets/consumables/{consumable_id}/allocations": _CONSUMABLE,
    "POST /assets/consumables/{consumable_id}/receipts": _CONSUMABLE,
    "POST /assets/consumables/{consumable_id}/returns": _CONSUMABLE,
    "POST /assets/groups": "an asset group (a saved filter), not assets",
    "POST /assets/imports": "an import job: its rows never reach an asset outside the set"
    " (test_resource_access_paths, test_an_import_never_reaches_...)",
    "POST /assets/imports/{import_id}/run": _JOB,
    "POST /assets/labels/prints/{print_id}/reprint": _JOB,
    "POST /assets/life-cycles": _CONFIG,
    "POST /assets/loans/{loan_id}/returns": "returns on a loan with no visible asset are 404"
    " (test_asset_scope_registers, test_returns_on_a_loan_with_no_visible_asset_...)",
    "POST /assets/my-bookings": _OWN,
    "POST /assets/my-bookings/{booking_id}/cancel": _OWN,
    "POST /assets/overdue-rule/preview": _CONFIG,
    "POST /assets/product-types": _CONFIG,
    "POST /assets/products": _CATALOGUE,
    "POST /assets/states": _CONFIG,
    "POST /assets/stock-rules": _CONFIG,
    "POST /cmdb/business-views/{view_id}/save-as-new": "a copy of a view the reader can open;"
    " its map is drawn through the reader's rights",
    "POST /cmdb/ci-states": _CONFIG,
    "POST /cmdb/ci-types": _CONFIG,
    "POST /cmdb/cis": _CREATE,
    "POST /cmdb/imports": "an import job: its rows match only CIs the importer sees, and an"
    " unseen one reads as one that exists nowhere (test_cmdb_merge_import)",
    "POST /cmdb/imports/{import_id}/run": _JOB,
    "POST /cmdb/relationship-types": _CONFIG,
    "PUT /cmdb/settings": _CONFIG,
    "PUT /cmdb/settings/source-precedence": _CONFIG,
    "POST /cmdb/sync-rules": _SYNC,
    "POST /cmdb/sync-rules/preview": _SYNC,
    "PUT /cmdb/sync-rules/{rule_id}": _SYNC,
    "DELETE /cmdb/sync-rules/{rule_id}": _SYNC,
    "POST /cmdb/sync-rules/{rule_id}/runs": _SYNC,
}


async def test_every_cmdb_and_asset_record_write_refuses_an_unseen_record(world: World) -> None:
    """A write naming a CI or asset outside the narrowed person's set answers 404 (lane C 1, 6)."""
    a = world.a
    await world.sql(
        "UPDATE tenant_subscriptions SET edition = 'enterprise' WHERE tenant_id = $1", a.tenant
    )
    types = await _types(world, a)
    unseen_ci = (await _ci(world, a, "Unseen database", "database")).json()
    product = await _product(world, a, "laptop", f"Write walk {uuid.uuid4().hex[:6]}")
    unseen_asset = (
        await add_asset(
            world, a, {"name": "Unseen laptop", "product_id": product, "site_id": str(a.s1)}
        )
    ).json()
    narrowed = await role(
        world,
        a,
        "Write walk",
        [
            ("cmdb.view", "all"),
            ("cmdb.edit", "all"),
            ("cmdb.manage", "all"),
            ("cmdb.delete", "all"),
            ("cmdb.add", "all"),
            ("assets.view", "all"),
            ("assets.manage", "all"),
            ("assets.edit_disposed", "all"),
            ("assets.reinstate", "all"),
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
    routes = sorted(
        {
            (method, path.removeprefix(API))
            for method, path, _dependant, _endpoint in api_routes(world.app)
            if method in WRITES and path.startswith((f"{API}/cmdb", f"{API}/assets"))
        }
    )
    record = [(m, p) for m, p in routes if any(x in p for x in RECORD_MARKERS)]
    others = [f"{m} {p}" for m, p in routes if (m, p) not in record]
    unknown = [r for r in others if r not in WRITE_EXEMPT and r not in BODY_PROBED]
    assert unknown == [], f"classify these in WRITE_EXEMPT or BODY_PROBED: {unknown}"
    stale = sorted((set(WRITE_EXEMPT) | BODY_PROBED) - set(others))
    assert stale == [], f"no such route any more: {stale}"
    fill = {
        "{ci_id}": unseen_ci["id"],
        "{asset_id}": unseen_asset["id"],
        "{note_id}": str(uuid.uuid4()),
        "{cost_id}": str(uuid.uuid4()),
        "{link_id}": str(uuid.uuid4()),
        "{group_id}": str(uuid.uuid4()),
    }
    states = (await world.call("GET", "/assets/states", a, a.admin)).json()
    state_id = (states["items"] if isinstance(states, dict) else states)[0]["id"]
    rel_types = (await world.call("GET", "/cmdb/relationship-types", a, a.admin)).json()["items"]
    bodies = _record_bodies(
        state_id,
        types["application"]["id"],
        next(t for t in rel_types if t["code"] == "depends_on")["id"],
        str(a.requester2),
    )
    nowhere = {marker: str(uuid.uuid4()) for marker in fill}
    wrong: list[str] = []
    try:
        for method, path in record:
            name = f"{method} {path}"
            body = bodies.get(name, {})
            answers = []
            for values in (fill, nowhere):
                target = path
                for marker, value in values.items():
                    target = target.replace(marker, value)
                answers.append(
                    await world.call(
                        method,
                        target,
                        a,
                        a.requester,
                        json=body,
                        headers={**_new(), "If-Match": '"1"'},
                    )
                )
            unseen, none = answers
            if unseen.status_code < 400 or _answer(unseen) != _answer(none):
                wrong.append(f"{name}: unseen {_answer(unseen)} vs none {_answer(none)}")
        wrong.extend(await _body_probes(world, unseen_ci, unseen_asset, types))
    finally:
        await world.call("DELETE", f"/users/{a.requester}/roles/{narrowed}", a, a.admin)
    assert wrong == [], "writes that tell an unseen record from none:\n" + "\n".join(wrong)


def _answer(response: Any) -> tuple[Any, ...]:  # noqa: ANN401 - httpx
    """What a caller learns: the status, the code, the field codes, and per-item outcomes."""
    try:
        body = response.json()
    except ValueError:
        return (response.status_code,)
    if not isinstance(body, dict):
        return (response.status_code,)
    errors = body.get("errors", [])
    fields = tuple(sorted((str(e.get("field")), str(e.get("code"))) for e in errors))
    # A batch's own outcomes (from-assets' skipped reasons, a bulk move's per-item codes).
    items = tuple(
        sorted(
            str(item.get("reason") or item.get("code") or item.get("outcome"))
            for key in ("skipped", "results", "items", "outcomes")
            for item in body.get(key, []) or []
            if isinstance(item, dict)
        )
    )
    return (
        response.status_code,
        str(body.get("code", "")),
        fields,
        items,
        len(body.get("created", []) or []),
    )


async def _body_probes(
    world: World,
    unseen_ci: dict[str, Any],
    unseen_asset: dict[str, Any],
    types: dict[str, Any],
) -> list[str]:
    """Each BODY_PROBED route, with the unseen record and with an ID that exists nowhere.

    The admin makes what the routes need (a group, a booking and a relationship touching the
    unseen record); the narrowed person then calls each twice. Any difference tells them apart.
    """
    a = world.a
    soon = datetime.now(UTC) + timedelta(days=3)
    loanable = await world.call(
        "POST", "/assets/loanable", a, a.admin,
        json={"asset_ids": [unseen_asset["id"]], "loanable": True}, headers=_new(),
    )  # fmt: skip
    assert loanable.status_code == 200, loanable.text
    booking = await world.call(
        "POST", "/assets/bookings", a, a.admin,
        json={
            "asset_id": unseen_asset["id"], "borrower_id": str(a.requester2),
            "starts_at": soon.isoformat(), "ends_at": (soon + timedelta(days=1)).isoformat(),
        },
        headers=_new(),
    )  # fmt: skip
    assert booking.status_code == 201, booking.text
    group = await world.call(
        "POST", "/assets/groups", a, a.admin,
        json={"name": f"Probe {uuid.uuid4().hex[:6]}", "kind": "static"}, headers=_new(),
    )  # fmt: skip
    assert group.status_code == 201, group.text
    seen_ci = (await _ci(world, a, "Probe server", "server")).json()
    rel_types = (await world.call("GET", "/cmdb/relationship-types", a, a.admin)).json()["items"]
    depends = next(t for t in rel_types if t["code"] == "depends_on")
    linked = await world.call(
        "POST", f"/cmdb/cis/{unseen_ci['id']}/relationships", a, a.admin,
        json={"type_id": depends["id"], "direction": "forward", "targets": [seen_ci["id"]]},
        headers=_new(),
    )  # fmt: skip
    assert linked.status_code == 201, linked.text
    relationship = (
        await world.sql(
            "SELECT id FROM cmdb_relationships WHERE tenant_id = $1 AND from_ci_id = $2",
            a.tenant,
            uuid.UUID(unseen_ci["id"]),
        )
    )[0]["id"]
    states = (await world.call("GET", "/assets/states", a, a.admin)).json()
    state_id = (states["items"] if isinstance(states, dict) else states)[0]["id"]

    def probes(asset: str, ci: str, rel: str, book: str) -> list[tuple[str, str, Any]]:
        return [
            ("POST", "/assets/loans", {
                "borrower_id": str(a.requester2), "asset_ids": [asset],
                "due_at": soon.isoformat(),
            }),
            ("POST", "/assets/bookings", {
                "asset_id": asset, "borrower_id": str(a.requester2),
                "starts_at": soon.isoformat(), "ends_at": (soon + timedelta(days=1)).isoformat(),
            }),
            ("POST", "/assets/loanable", {"asset_ids": [asset], "loanable": False}),
            ("POST", "/assets/merges", {
                "survivor_id": asset, "survivor_version": 1, "merged_id": asset,
                "merged_version": 1, "choices": {},
            }),
            ("POST", "/assets/bulk-moves", {
                "items": [{"asset_id": asset, "version": 1}], "to_state_id": state_id,
                "reason": "Probe",
            }),
            ("POST", "/assets/bulk-jobs", {"action": "delete", "asset_ids": [asset]}),
            ("POST", f"/assets/groups/{group.json()['id']}/members", {"asset_ids": [asset]}),
            ("POST", "/assets/labels", {"asset_ids": [asset]}),
            ("POST", "/cmdb/cis/from-assets", {
                "asset_ids": [asset], "type_id": types["workstation"]["id"],
            }),
            ("POST", "/cmdb/business-views", {
                "name": "Probe view", "base_ci_id": ci, "layout": "radial",
            }),
            ("POST", "/cmdb/merges", {
                "survivor_id": seen_ci["id"], "survivor_version": 1, "merged_id": ci,
                "merged_version": 1, "choices": {},
            }),
            ("DELETE", f"/cmdb/relationships/{rel}", None),
            ("POST", f"/assets/bookings/{book}/cancel", None),
            ("POST", f"/assets/bookings/{book}/handover", None),
        ]  # fmt: skip

    real = probes(unseen_asset["id"], unseen_ci["id"], str(relationship), booking.json()["id"])
    nowhere = probes(str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()))
    wrong: list[str] = []
    for (method, path, body), (_, other_path, other_body) in zip(real, nowhere, strict=True):
        unseen = await world.call(
            method, path, a, a.requester, json=body, headers={**_new(), "If-Match": '"1"'}
        )
        none = await world.call(
            method, other_path, a, a.requester, json=other_body,
            headers={**_new(), "If-Match": '"1"'},
        )  # fmt: skip
        if _answer(unseen) != _answer(none) or (
            unseen.status_code < 400 and path not in ACCEPTED_THEN_REFUSED
        ):
            wrong.append(f"{method} {path}: unseen {_answer(unseen)} vs none {_answer(none)}")
    return wrong
