"""The asset list's views and tree, the paged picker, linked records (WP-049b s4a; 0140).

REQ-AST-047 (views, the product type tree with counts, 50,000 assets), REQ-AST-046 (the picker:
type and site filters, part of a serial, cursor pages, scope), REQ-AST-044 (no port yet: not
available) and REQ-AST-045 (a work item raised with an asset: its history line).
"""

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from sqlalchemy import select

from app.core.tenancy import TenantContext
from app.modules.assets.domain.views import AssetView
from app.modules.assets.infra.models import Asset
from app.modules.assets.service import linked, views
from app.modules.assets.service.realtime import ASSET_CHANGED, RECORD_KIND, ROUTES
from app.modules.identity_access import subject_for
from app.shared.events import EventEnvelope
from app.shared.realtime import record
from tests.db import test_incidents_api
from tests.db.test_asset_holders_api import _hold
from tests.db.test_asset_moves_api import _states
from tests.db.test_assets_api import _add, _product, _types
from tests.db.test_incidents_api import Org, World, problem
from tooling import timing

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"
FIFTY_THOUSAND = 50_000


async def _asset(
    world: World,
    org: Org,
    name: str,
    kind: str = "laptop",
    **values: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    product = await _product(world, org, kind, f"P {name}")
    made = await _add(world, org, {"name": name, "product_id": product, **values})
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _ids(world: World, org: Org, user: uuid.UUID | None = None, **params: str) -> set[str]:
    found = await world.call("GET", BASE, org, user or org.admin, params=params)
    assert found.status_code == 200, found.text
    return {r["id"] for r in found.json()["items"]}


async def test_047_ac1_a_tree_node_lists_its_types_and_the_counts_follow(world: World) -> None:
    a = world.a
    types = await _types(world, a)
    station = await _asset(world, a, "Station 1", "workstation")
    laptop = await _asset(world, a, "Laptop 1", "laptop")
    phone = await _asset(world, a, "Phone 1", "phone")
    only_stations = await _ids(world, a, product_type=types["workstation"]["id"])
    assert only_stations == {station["id"]}
    computers = await _ids(world, a, product_type=types["computer"]["id"])
    assert computers == {station["id"], laptop["id"]}  # the node and every type below it
    assert phone["id"] not in computers
    counts = await world.call("GET", f"{BASE}/type-counts", a, a.admin)
    assert counts.status_code == 200, counts.text
    per_type = {c["product_type_id"]: c["count"] for c in counts.json()["types"]}
    assert per_type[types["workstation"]["id"]] == 1
    assert per_type[types["laptop"]["id"]] == 1
    assert counts.json()["total"] == 3
    # Within what the caller may see: another tenant counts nothing of A's.
    b = world.b
    theirs = (await world.call("GET", f"{BASE}/type-counts", b, b.admin)).json()
    assert theirs["total"] == 0
    # A requester has no asset list at all.
    assert problem(await world.call("GET", f"{BASE}/type-counts", a, a.requester))[0] == 403


async def test_047_the_built_in_views(world: World) -> None:
    a = world.a
    states = await _states(world, a)
    held = await _asset(world, a, "Held laptop")
    assert (await _hold(world, held, "user", a.admin)).status_code == 200
    loanable = await _asset(world, a, "Loan laptop")
    made = await world.call(
        "POST", f"{BASE}/loanable", a, a.admin,
        json={"asset_ids": [loanable["id"]], "loanable": True},
    )  # fmt: skip
    assert made.status_code in {200, 204}, made.text
    soon = (datetime.now(UTC).date() + timedelta(days=10)).isoformat()
    later = (datetime.now(UTC).date() + timedelta(days=400)).isoformat()
    expiring = await _asset(world, a, "Warranty soon", warranty_expires_on=soon)
    await _asset(world, a, "Warranty later", warranty_expires_on=later)
    failed = await _asset(world, a, "Scan failed")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        from app.modules.assets import ScanFailure, ScanResult, ScanSource, record_scan  # noqa: PLC0415 - the port discovery calls

        await record_scan(
            session, asset_id=uuid.UUID(failed["id"]), scanned_at=datetime.now(UTC),
            source=ScanSource.PROBE, result=ScanResult.FAILED,
            failure_reason=ScanFailure.UNREACHABLE,
        )  # fmt: skip
    assert await _ids(world, a, view="mine") == {held["id"]}
    assert await _ids(world, a, view="loanable") == {loanable["id"]}
    assert expiring["id"] in await _ids(world, a, view="warranty_expiring")
    assert len(await _ids(world, a, view="warranty_expiring")) == 1
    assert await _ids(world, a, view="scan_failures") == {failed["id"]}
    # New assets start in stock (Appendix A); one in use leaves the view.
    in_stock = await _ids(world, a, view="in_stock")
    assert failed["id"] in in_stock
    in_use = next(code for code in states if code == "in_use")
    await world.sql(
        "UPDATE assets SET state_id = $1 WHERE id = $2", uuid.UUID(states[in_use]),
        uuid.UUID(failed["id"]),
    )  # fmt: skip
    assert failed["id"] not in await _ids(world, a, view="in_stock")
    # Recently discovered: empty until discovery sets a discovered serial (WP-050).
    assert await _ids(world, a, view="recently_discovered") == set()
    await world.sql(
        "UPDATE assets SET discovered_serial = 'DSC-1' WHERE id = $1", uuid.UUID(held["id"])
    )
    assert await _ids(world, a, view="recently_discovered") == {held["id"]}
    assert (await world.call("GET", BASE, a, a.admin, params={"view": "secret"})).status_code == 422
    # A view never widens the caller's scope: the same view in tenant B is empty.
    assert await _ids(world, world.b, view="mine") == set()


async def test_046_ac1_part_of_a_serial_finds_the_asset_with_filters_and_pages(
    world: World,
) -> None:
    a = world.a
    types = await _types(world, a)
    wanted = await _asset(
        world, a, "Picker station", "workstation", serial_number="SN-224F7Q9X", site_id=str(a.s1)
    )
    await _asset(world, a, "Picker laptop", "laptop", serial_number="SN-224F7Q9Y")
    await world.sql(
        "UPDATE assets SET discovered_serial = 'HW-77ZZK1' WHERE id = $1", uuid.UUID(wanted["id"])
    )
    path = f"{BASE}/picker/search"
    for part in ("4F7Q9X", "224f7q", "77ZZK", "Picker sta"):
        found = await world.call("GET", path, a, a.admin, params={"q": part})
        assert found.status_code == 200, found.text
        assert wanted["id"] in {r["id"] for r in found.json()["items"]}, part
    by_type = await world.call(
        "GET", path, a, a.admin, params={"q": "224F7Q", "product_type_id": types["computer"]["id"]}
    )
    assert len(by_type.json()["items"]) == 2  # the node's types: workstation and laptop
    by_site = await world.call(
        "GET", path, a, a.admin, params={"q": "224F7Q", "site_id": str(a.s1)}
    )
    assert [r["id"] for r in by_site.json()["items"]] == [wanted["id"]]
    # Cursor pages, by name.
    first = (await world.call("GET", path, a, a.admin, params={"q": "Picker", "limit": "1"})).json()
    assert len(first["items"]) == 1
    assert first["next_cursor"] is not None
    second = (
        await world.call(
            "GET", path, a, a.admin,
            params={"q": "Picker", "limit": "1", "cursor": first["next_cursor"]},
        )
    ).json()  # fmt: skip
    assert second["items"][0]["id"] != first["items"][0]["id"]
    assert problem(await world.call("GET", path, a, a.admin, params={"cursor": "%%%"}))[0] == 400
    # The classic picker takes the same filters.
    classic = await world.call(
        "GET", f"{BASE}/picker", a, a.admin, params={"q": "224F7Q", "site_id": str(a.s1)}
    )
    assert [r["id"] for r in classic.json()] == [wanted["id"]]


async def test_046_ac2_an_asset_outside_the_users_scope_never_appears(world: World) -> None:
    a = world.a
    role = await world.call(
        "POST", "/roles", a, a.admin,
        json={"name": "Site picker",
              "permissions": [{"permission": "assets.view", "scope": "site"}]},
    )  # fmt: skip
    assert role.status_code == 201, role.text
    granted = await world.call("PUT", f"/users/{a.requester}/roles/{role.json()['id']}", a, a.admin)
    assert granted.status_code in {200, 204}, granted.text
    near = await _asset(world, a, "Scoped near", serial_number="SCOPE-1111", site_id=str(a.s1))
    far = await _asset(world, a, "Scoped far", serial_number="SCOPE-2222", site_id=str(a.s2))
    found = await world.call("GET", f"{BASE}/picker/search", a, a.requester, params={"q": "SCOPE"})
    assert found.status_code == 200, found.text
    ids = {r["id"] for r in found.json()["items"]}
    assert near["id"] in ids
    assert far["id"] not in ids
    # Someone without assets.view sees only what they hold; tenant B sees nothing of A's.
    plain = await world.call("GET", f"{BASE}/picker/search", a, a.requester2, params={"q": "SCOPE"})
    assert plain.json()["items"] == []
    b = world.b
    other = await world.call("GET", f"{BASE}/picker/search", b, b.admin, params={"q": "SCOPE"})
    assert other.json()["items"] == []


async def _fifty_thousand(world: World, org: Org) -> dict[str, dict[str, Any]]:
    await _asset(world, org, "Seed workstation", "workstation")  # seeds the catalogue
    types = await _types(world, org)
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        products = {
            r["product_type_id"]: r["id"]
            for r in await conn.fetch(
                "SELECT DISTINCT ON (product_type_id) product_type_id, id FROM asset_products"
                " WHERE tenant_id = $1",
                org.tenant,
            )
        }
        state = await conn.fetchval(
            "SELECT id FROM asset_states WHERE tenant_id = $1 AND category = 'in_stock' LIMIT 1",
            org.tenant,
        )
        laptop_type = uuid.UUID(types["laptop"]["id"])
        station_type = uuid.UUID(types["workstation"]["id"])
        # Every tenth a workstation (5,000): a mid-sized tree node; the rest laptops.
        await conn.execute(
            "INSERT INTO assets (tenant_id, id, name, product_id, product_type_id, state_id,"
            " serial_number, updated_at)"
            " SELECT $1, gen_random_uuid(), 'Bulk asset ' || n,"
            "   CASE WHEN n % 10 = 0 THEN $6::uuid ELSE $2::uuid END,"
            "   CASE WHEN n % 10 = 0 THEN $7::uuid ELSE $3::uuid END,"
            "   $4, 'BULK-' || n, now() - make_interval(secs => n)"
            " FROM generate_series(1, $5) AS n",
            org.tenant,
            products.get(laptop_type) or await _laptop_product(world, org),
            laptop_type,
            state,
            FIFTY_THOUSAND,
            products[station_type],
            station_type,
        )
        await conn.execute("ANALYZE assets")
    finally:
        await conn.close()
    return types


async def _laptop_product(world: World, org: Org) -> uuid.UUID:
    return uuid.UUID(await _product(world, org, "laptop", "Bulk laptop"))


@pytest.mark.timing
async def test_047_ac3_the_first_page_of_50000_assets_opens_in_under_a_second(
    world: World,
) -> None:
    """The plan uses the tenant-first indexes (default sort; the tree filter), and the API's
    first page answers within 1 s (10 s in pull requests, tooling/timing.py)."""
    a = world.a
    types = await _fifty_thousand(world, a)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        admin = await subject_for(session, a.tenant, a.admin)
        statements: dict[str, str] = {}
        nodes = (
            ("default", None),
            ("branch", uuid.UUID(types["computer"]["id"])),  # holds all 50,000
            ("node", uuid.UUID(types["workstation"]["id"])),  # holds 5,001
        )
        for name, node in nodes:
            rows = await views.rows(session, admin, view=None, product_type=node, trash=False)
            page = (
                rows.where(Asset.tenant_id == a.tenant)  # as RLS adds it for the app role
                .order_by(Asset.updated_at.desc(), Asset.id)
                .limit(51)
            )
            compiled = page.compile(
                dialect=session.get_bind().dialect, compile_kwargs={"literal_binds": True}
            )
            statements[name] = str(compiled)
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        for name, sql in statements.items():
            plan = "\n".join(r[0] for r in await conn.fetch(f"EXPLAIN (ANALYZE, BUFFERS) {sql}"))
            assert "Seq Scan on assets" not in plan, plan
            # The default sort walks ix_assets_updated; a big branch too (the planner's choice:
            # most rows match); a mid-sized node 0140's index, tenant first, in sort order.
            index = "ix_assets_type_updated" if name == "node" else "ix_assets_updated"
            assert index in plan, plan
            took = float(plan.rsplit("Execution Time: ", 1)[1].split(" ")[0])
            timing.record(f"asset_list_50000_{name}_plan", {"execution_ms": took})
    finally:
        await conn.close()
    for params in ({}, {"product_type": types["computer"]["id"]}, {"view": "in_stock"}):
        started = time.perf_counter()
        found = await world.call(
            "GET", BASE, a, a.admin, params={**params, "include_total": "true"}
        )
        elapsed = time.perf_counter() - started
        assert found.status_code == 200, found.text
        assert len(found.json()["items"]) == 50
        timing.record("asset_list_50000_first_page", {"ms": round(elapsed * 1000, 1), **params})
        assert elapsed < timing.limit(1.0), f"{params}: {elapsed:.3f}s"


async def test_044_without_a_port_the_panel_is_not_available(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Linked laptop")
    registered = linked.linked_port()  # work items register theirs at import
    linked.unregister_linked_records()
    try:
        await _not_available(world, a, asset)
    finally:
        if registered is not None:
            linked.register_linked_records(registered)


async def _not_available(world: World, a: Org, asset: dict[str, Any]) -> None:
    found = await world.call("GET", f"{BASE}/{asset['id']}/linked", a, a.admin)
    assert found.status_code == 200, found.text
    assert found.json() == {"available": False, "kinds": []}
    page = await world.call("GET", f"{BASE}/{asset['id']}/linked/incident", a, a.admin)
    assert problem(page) == (404, "linked_records_not_available")
    assert (
        problem(await world.call("GET", f"{BASE}/{asset['id']}/linked", world.b, world.b.admin))[0]
        == 404
    )


async def _envelope(
    world: World, org: Org, event_type: str, payload: dict[str, Any]
) -> EventEnvelope:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 ORDER BY created_at DESC LIMIT 1",
        org.tenant,
    )
    real = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    return real.model_copy(update={"event_type": event_type, "payload": payload})


async def test_045_a_work_item_raised_with_an_asset_adds_a_history_line_and_counts_live(
    world: World,
) -> None:
    a = world.a
    asset = await _asset(world, a, "Raised from")
    incident = await world.create(a, a.admin, subject="Raised with an asset")
    # As lane A's event will carry it: no display ID, the type left out.
    raised = await _envelope(
        world, a, "work_items.asset_link.changed",
        {"work_item_id": incident["id"], "asset_id": asset["id"], "change": "added",
         "at_creation": True},
    )  # fmt: skip
    later = raised.model_copy(update={"payload": {**raised.payload, "at_creation": False}})
    gone = raised.model_copy(
        update={"payload": {**raised.payload, "work_item_id": str(uuid.uuid4())}}
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await linked.on_asset_link_changed(raised, session)
        await linked.on_asset_link_changed(later, session)  # a later link: its own line (AC3)
        await linked.on_asset_link_changed(gone, session)  # a record already gone
    history = (await world.call("GET", f"{BASE}/{asset['id']}/history", a, a.admin)).json()
    lines = [c for e in history["items"] for c in e["changes"] if c["field"] == linked.RAISED_FIELD]
    assert len(lines) == 2
    named = [c["new"] for c in lines if c["new"]["display_id"] is not None]
    # Looked up at write time: the record's own display ID and type (REQ-AST-045 AC1).
    assert named == [
        {"work_item_id": incident["id"], "display_id": incident["display_id"], "type": "incident"}
    ]
    assert [c["new"]["display_id"] for c in lines].count(None) == 1  # the generic line
    # REQ-INC-015 AC3: a link made later, and an unlink, each say so on the asset too.
    unlinked = raised.model_copy(
        update={"payload": {**raised.payload, "at_creation": False, "change": "removed"}}
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await linked.on_asset_link_changed(unlinked, session)
    history = (await world.call("GET", f"{BASE}/{asset['id']}/history", a, a.admin)).json()
    later_lines = [
        c for e in history["items"] for c in e["changes"] if c["field"] == linked.LINKED_FIELD
    ]
    named_line = {
        "work_item_id": incident["id"], "display_id": incident["display_id"], "type": "incident"
    }  # fmt: skip
    assert sorted([(c["old"] is None, c["new"] is None) for c in later_lines]) == [
        (False, True),
        (True, False),
    ]  # one link (new only), one unlink (old only)
    assert all((c["new"] or c["old"]) == named_line for c in later_lines)
    # The panel follows live: the link names the asset (IDs and the field only).
    route = next(r for r in ROUTES if raised.event_type in r.event_types)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(raised, session)
        assert await session.scalar(select(Asset.id).where(Asset.id == uuid.UUID(asset["id"])))
    (published,) = effects.publications
    assert published.channel == record(a.tenant, RECORD_KIND, uuid.UUID(asset["id"]))
    assert (published.type, published.fields) == (ASSET_CHANGED, ("linked",))


def test_the_built_in_views_have_codes_only() -> None:
    assert [v.value for v in AssetView] == [
        "all", "mine", "scan_failures", "loanable", "in_stock", "warranty_expiring",
        "recently_discovered",
    ]  # fmt: skip
