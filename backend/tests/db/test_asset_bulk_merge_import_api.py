"""Asset bulk jobs, merges and imports (WP-049b S4b; 0145).

REQ-AST-051 (bulk actions as background jobs, at most 1,000, each asset checked as the
requester and skipped with a reason), REQ-AST-052 (merge on both assets with assets.manage,
never across tenants, across sites only when both are managed; one audit entry with the field
mapping; the alias; a restore warns) and REQ-AST-053 (imports with a dry run, per-row problems,
WP-021's file limits, the zip-bomb check).

The incident world: org A's admin holds everything; technicians hold assets.view at all and no
assets.manage (D-157). `_site_manager` gives tech A (at site s1) assets.manage at site scope.
"""

import io
import json
import uuid
import zipfile
from typing import Any

import pytest
from sqlalchemy import text

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.assets.service.bulk_jobs import run_asset_bulk_jobs
from app.modules.assets.service.imports import run_asset_imports
from app.modules.assets.service.realtime import BULK_PROGRESS, IMPORT_PROGRESS, ROUTES
from app.shared.events import EventEnvelope
from app.shared.realtime import personal
from tests.db import test_incidents_api
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import BASE as INCIDENTS
from tests.db.test_incidents_api import Org, World, problem, role
from tests.db.test_knowledge_api import _match, _new

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"
NEW_TABLES = ("asset_bulk_jobs", "asset_merges", "asset_imports")


async def _asset(world: World, org: Org, name: str, **values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    product = await _product(world, org, "laptop", f"P {name} {uuid.uuid4().hex[:6]}")
    made = await _add(world, org, {"name": name, "product_id": product, **values})
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _fresh(world: World, org: Org, asset: dict[str, Any]) -> dict[str, Any]:
    found = await world.call("GET", f"{BASE}/{asset['id']}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def _site_manager(world: World) -> uuid.UUID:
    """Tech A manages the assets of their own site (s1) only."""
    a = world.a
    made = await role(
        world, a, "Site asset manager", [("assets.view", "all"), ("assets.manage", "site")]
    )
    granted = await world.call("PUT", f"/users/{a.tech_a}/roles/{made}", a, a.admin)
    assert granted.status_code == 204, granted.text
    return a.tech_a


def _database(world: World) -> Database:
    """As the application role (RLS applies), like the consumers worker."""
    return Database(create_engine(world.db.app_url, application_name="test", use_null_pool=True))


async def _run(world: World, runner: Any) -> None:  # noqa: ANN401 - a schedule function
    database = _database(world)
    try:
        await runner(database, world.app.state.settings)
    finally:
        await database.dispose()


async def _bulk(world: World, org: Org, user: uuid.UUID, body: dict[str, Any]) -> Any:  # noqa: ANN401 - httpx response
    return await world.call("POST", f"{BASE}/bulk-jobs", org, user, json=body, headers=_new())


# --- bulk actions (REQ-AST-051) --------------------------------------------------------------


async def test_051_over_the_cap_is_a_422_with_the_cap(world: World) -> None:
    a = world.a
    ids = [str(uuid.uuid4()) for _ in range(1001)]
    refused = await _bulk(world, a, a.admin, {"action": "delete", "asset_ids": ids})
    assert problem(refused) == (422, "asset_bulk_too_many")
    assert refused.json()["params"] == {"max": 1000}
    # Exactly the cap is accepted (unknown assets are each skipped, as not found).
    accepted = await _bulk(world, a, a.admin, {"action": "delete", "asset_ids": ids[:1000]})
    assert accepted.status_code == 202, accepted.text
    # A change the action does not take is refused before anything runs.
    wrong = await _bulk(
        world, a, a.admin,
        {"action": "move", "asset_ids": ids[:1], "changes": {"location": "Here"}},
    )  # fmt: skip
    assert wrong.status_code == 422, wrong.text
    # Bulk is for those who manage assets: a requester may not ask.
    assert (
        problem(await _bulk(world, a, a.requester, {"action": "delete", "asset_ids": ids[:1]}))[0]
        == 403
    )


async def test_051_each_asset_is_checked_as_the_requester_and_skipped_with_the_reason(
    world: World,
) -> None:
    a = world.a
    tech = await _site_manager(world)
    mine = await _asset(world, a, "Bulk near", site_id=str(a.s1))
    other_site = await _asset(world, a, "Bulk far", site_id=str(a.s2))
    also_mine = await _asset(world, a, "Bulk near 2", site_id=str(a.s1))
    started = await _bulk(
        world, a, tech,
        {
            "action": "edit",
            "asset_ids": [mine["id"], other_site["id"], also_mine["id"]],
            "changes": {"location": "Shelf 4", "cost_centre": "CC-9"},
        },
    )  # fmt: skip
    assert started.status_code == 202, started.text
    job = started.json()
    assert (job["status"], job["total"], job["processed"]) == ("queued", 3, 0)
    await _run(world, run_asset_bulk_jobs)
    done = await world.call("GET", f"{BASE}/bulk-jobs/{job['id']}", a, tech)
    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["status"], body["done_count"], body["skipped_count"]) == ("done", 2, 1)
    by_id = {r["id"]: r for r in body["results"]}
    assert by_id[mine["id"]]["outcome"] == "done"
    assert by_id[also_mine["id"]]["outcome"] == "done"
    skipped = by_id[other_site["id"]]
    assert skipped["outcome"] == "skipped"
    assert skipped["code"] == "permission_denied"  # never silently done, never silently left out
    assert skipped["tag"] == other_site["tag"]
    assert (await _fresh(world, a, mine))["location"] == "Shelf 4"
    assert (await _fresh(world, a, other_site))["location"] is None
    # The job is the requester's own: another person does not find it.
    assert (await world.call("GET", f"{BASE}/bulk-jobs/{job['id']}", a, a.admin)).status_code == 404
    # Each asset's history names the job.
    rows = await world.sql(
        "SELECT count(*) AS n FROM field_changes WHERE tenant_id = $1 AND batch_id = $2",
        a.tenant,
        uuid.UUID(job["id"]),
    )
    assert rows[0]["n"] >= 2


async def test_051_an_asset_out_of_sight_is_skipped_as_not_found_and_never_named(
    world: World,
) -> None:
    """Lane B: a job may name any ID; a hidden asset's tag never reaches the results."""
    a = world.a
    made = await role(
        world, a, "Own-site asset keeper", [("assets.view", "site"), ("assets.manage", "site")]
    )
    granted = await world.call("PUT", f"/users/{a.requester2}/roles/{made}", a, a.admin)
    assert granted.status_code == 204, granted.text
    hidden = await _asset(
        world, a, "Bulk hidden", site_id=str(a.s1)
    )  # requester2 works no asset site
    started = await _bulk(
        world, a, a.requester2,
        {"action": "edit", "asset_ids": [hidden["id"]], "changes": {"location": "Shelf 9"}},
    )  # fmt: skip
    assert started.status_code == 202, started.text
    await _run(world, run_asset_bulk_jobs)
    done = await world.call("GET", f"{BASE}/bulk-jobs/{started.json()['id']}", a, a.requester2)
    (skipped,) = done.json()["results"]
    assert (skipped["outcome"], skipped["code"]) == ("skipped", "asset_not_found")
    assert skipped["tag"] is None
    assert hidden["tag"] not in done.text
    assert (await _fresh(world, a, hidden))["location"] is None


async def test_051_move_assign_and_delete_run_through_the_single_asset_rules(
    world: World,
) -> None:
    a = world.a
    states = {
        s["code"]: s["id"] for s in (await world.call("GET", f"{BASE}/states", a, a.admin)).json()
    }
    first = await _asset(world, a, "Bulk move 1")
    second = await _asset(world, a, "Bulk move 2")
    moved = await _bulk(
        world, a, a.admin,
        {"action": "move", "asset_ids": [first["id"], second["id"]],
         "changes": {"to_state_id": states["in_use"]}},
    )  # fmt: skip
    assert moved.status_code == 202, moved.text
    assigned = await _bulk(
        world, a, a.admin,
        {"action": "assign", "asset_ids": [first["id"]],
         "changes": {"holder_kind": "user", "holder_id": str(a.requester)}},
    )  # fmt: skip
    assert assigned.status_code == 202, assigned.text
    deleted = await _bulk(world, a, a.admin, {"action": "delete", "asset_ids": [second["id"]]})
    await _run(world, run_asset_bulk_jobs)
    for job in (moved, assigned, deleted):
        found = (await world.call("GET", f"{BASE}/bulk-jobs/{job.json()['id']}", a, a.admin)).json()
        assert found["status"] == "done", found
        assert found["skipped_count"] == 0, found["results"]
    after = await _fresh(world, a, first)
    assert after["state_id"] == states["in_use"]
    assert after["owner_user_id"] == str(a.requester)
    # Delete is the trash: the row stays, soft-deleted; it can be restored.
    rows = await world.sql(
        "SELECT deleted_at FROM assets WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(second["id"]),
    )
    assert rows
    assert rows[0]["deleted_at"] is not None
    restored = await world.call("POST", f"{BASE}/{second['id']}/restore", a, a.admin)
    assert restored.status_code == 200, restored.text
    listed = await world.call("GET", f"{BASE}/bulk-jobs", a, a.admin)
    assert {j["id"] for j in listed.json()} >= {moved.json()["id"], deleted.json()["id"]}


# --- merging duplicates (REQ-AST-052) -----------------------------------------------------------


async def _merge(
    world: World,
    org: Org,
    user: uuid.UUID,
    survivor: dict[str, Any],
    merged: dict[str, Any],
    choices: dict[str, str] | None = None,
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "POST", f"{BASE}/merges", org, user,
        json={
            "survivor_id": survivor["id"], "survivor_version": survivor["version"],
            "merged_id": merged["id"], "merged_version": merged["version"],
            "choices": choices or {},
        },
        headers=_new(),
    )  # fmt: skip


async def test_052_merge_keeps_the_choice_moves_links_and_writes_one_audit_entry(
    world: World,
) -> None:
    a = world.a
    discovered = await _asset(world, a, "Dell discovered", serial_number="HW-1001")
    await world.sql(
        "UPDATE assets SET discovered_serial = 'HW-1001' WHERE id = $1",
        uuid.UUID(discovered["id"]),
    )
    discovered = await _fresh(world, a, discovered)
    by_po = await _asset(
        world, a, "Dell from PO", serial_number="PO-77", purchase_price="1200.00",
        location="Store", barcode="BC-77",
    )  # fmt: skip
    incident = await world.create(a, a.admin, asset_ids=[by_po["id"]])
    # The preview suggests the discovered one as the survivor, whichever order is asked.
    preview = await world.call(
        "GET", f"{BASE}/merge-preview", a, a.admin,
        params={"first": by_po["id"], "second": discovered["id"]},
    )  # fmt: skip
    assert preview.status_code == 200, preview.text
    shown = preview.json()
    assert (shown["survivor"]["id"], shown["swapped"]) == (discovered["id"], True)
    sides = {f["field"]: f["side"] for f in shown["fields"]}
    assert sides["purchase_price"] == "merged"  # the survivor has none: the PO's cost is kept
    assert sides["name"] == "survivor"
    done = await _merge(world, a, a.admin, discovered, by_po, {"location": "merged"})
    assert done.status_code == 201, done.text
    result = done.json()
    survivor = result["survivor"]
    assert survivor["purchase_price"] == "1200.00"  # AC1: PO cost kept, discovered hardware kept
    assert survivor["serial_number"] == "HW-1001"
    assert survivor["location"] == "Store"
    assert result["moved"]["work_items"] == 1
    # The incident now links the survivor (lane A's repoint, through the port).
    links = await world.call("GET", f"{INCIDENTS}/{incident['id']}/assets", a, a.admin)
    assert [x["asset_id"] for x in links.json()["items"]] == [discovered["id"]]
    # ONE audit entry for the merge, holding the field-by-field mapping (codes only).
    entries = await world.sql(
        "SELECT object_id, details FROM audit_entries"
        " WHERE tenant_id = $1 AND action = 'asset.merged'",
        a.tenant,
    )
    assert len(entries) == 1
    details = (
        json.loads(entries[0]["details"])
        if isinstance(entries[0]["details"], str)
        else entries[0]["details"]
    )
    assert entries[0]["object_id"] == discovered["id"]
    assert details["merged_asset_id"] == by_po["id"]
    mapping = {m["field"]: m["side"] for m in details["mapping"]}
    assert mapping["location"] == "merged"
    assert mapping["purchase_price"] == "merged"
    assert mapping["name"] == "survivor"
    assert "1200" not in json.dumps(details)  # never values
    # AC2: both IDs open the survivor; the merged asset's serial and barcode find it.
    gone = await world.call("GET", f"{BASE}/{by_po['id']}", a, a.admin)
    assert problem(gone) == (404, "asset_merged")
    assert gone.json()["params"] == {"survivor_id": discovered["id"]}
    for text_ in ("PO-77", "bc-77", by_po["tag"]):
        found = await world.call("GET", BASE, a, a.admin, params={"search": text_})
        assert discovered["id"] in {r["id"] for r in found.json()["items"]}, text_
    # The merged asset is in the trash (soft delete), its history says where it went.
    rows = await world.sql(
        "SELECT deleted_at FROM assets WHERE tenant_id = $1 AND id = $2", a.tenant,
        uuid.UUID(by_po["id"]),
    )  # fmt: skip
    assert rows[0]["deleted_at"] is not None
    lines = await world.sql(
        "SELECT field FROM field_changes WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        uuid.UUID(by_po["id"]),
    )
    assert "merged_into" in {r["field"] for r in lines}


async def test_052_the_server_needs_manage_on_both_and_refuses_another_site(
    world: World,
) -> None:
    a = world.a
    near = await _asset(world, a, "Merge near", site_id=str(a.s1))
    far = await _asset(world, a, "Merge far", site_id=str(a.s2))
    # Tech A manages s1's assets (site scope), not s2's.
    tech = await _site_manager(world)
    refused = await _merge(world, a, tech, near, far)
    assert problem(refused) == (403, "asset_merge_site_not_managed")
    reversed_ = await _merge(world, a, tech, far, near)
    assert problem(reversed_)[0] == 403
    preview = await world.call(
        "GET", f"{BASE}/merge-preview", a, tech,
        params={"first": near["id"], "second": far["id"]},
    )  # fmt: skip
    assert problem(preview) == (403, "asset_merge_site_not_managed")
    # Nothing changed.
    assert (await _fresh(world, a, far))["version"] == far["version"]
    # A requester (no assets.manage) may not merge at all.
    assert problem(await _merge(world, a, a.requester, near, far))[0] == 403
    # Someone who manages both sites may (the admin).
    assert (await _merge(world, a, a.admin, near, far)).status_code == 201
    # The same asset twice, or a stale version, is refused.
    one = await _asset(world, a, "Merge self")
    assert problem(await _merge(world, a, a.admin, one, one)) == (409, "asset_merge_same")


async def test_052_a_merge_never_crosses_tenants(world: World) -> None:
    a, b = world.a, world.b
    mine = await _asset(world, a, "Tenant A asset")
    theirs = await _asset(world, b, "Tenant B asset")
    refused = await _merge(world, a, a.admin, mine, theirs)
    assert problem(refused) == (404, "asset_not_found")
    preview = await world.call(
        "GET", f"{BASE}/merge-preview", a, a.admin,
        params={"first": mine["id"], "second": theirs["id"]},
    )  # fmt: skip
    assert problem(preview) == (404, "asset_not_found")
    assert (await _fresh(world, b, theirs))["version"] == theirs["version"]


async def test_052_restoring_the_merged_asset_warns_and_never_undoes_the_merge(
    world: World,
) -> None:
    a = world.a
    keep = await _asset(world, a, "Keeper")
    dupe = await _asset(world, a, "Duplicate", serial_number="DUP-5")
    incident = await world.create(a, a.admin, asset_ids=[dupe["id"]])
    assert (await _merge(world, a, a.admin, keep, dupe)).status_code == 201
    warned = await world.call("POST", f"{BASE}/{dupe['id']}/restore", a, a.admin)
    assert problem(warned) == (409, "asset_restore_merged")
    assert warned.json()["params"] == {"asset": keep["tag"]}
    restored = await world.call(
        "POST", f"{BASE}/{dupe['id']}/restore", a, a.admin, params={"confirm_merged": "true"}
    )
    assert restored.status_code == 200, restored.text
    # The links stay with the survivor; the restored asset's own serial finds it again.
    links = await world.call("GET", f"{INCIDENTS}/{incident['id']}/assets", a, a.admin)
    assert [x["asset_id"] for x in links.json()["items"]] == [keep["id"]]
    found = await world.call("GET", BASE, a, a.admin, params={"search": "DUP-5"})
    assert {r["id"] for r in found.json()["items"]} == {dupe["id"]}
    assert (await world.call("GET", f"{BASE}/{dupe['id']}", a, a.admin)).status_code == 200


# --- imports (REQ-AST-053) -----------------------------------------------------------------------


async def _import(
    world: World,
    org: Org,
    content: bytes,
    *,
    name: str = "assets.csv",
    kind: str = "assets",
    mode: str = "add_update",
    match_on: str = "serial_number",
    user: uuid.UUID | None = None,
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "POST", f"{BASE}/imports", org, user or org.admin,
        params={"name": name, "kind": kind, "mode": mode, "match_on": match_on},
        content=content,
        headers={**_new(), "Content-Type": "application/octet-stream"},
    )  # fmt: skip


async def _job(world: World, org: Org, job: dict[str, Any]) -> dict[str, Any]:
    found = await world.call("GET", f"{BASE}/imports/{job['id']}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def test_053_a_dry_run_changes_nothing_then_the_run_adds_and_updates(world: World) -> None:
    a = world.a
    product = "Import laptop model"
    types = (await world.call("GET", f"{BASE}/product-types", a, a.admin)).json()
    laptop_type = next(t["id"] for t in types if t["api_name"] == "laptop")
    made = await world.call(
        "POST", f"{BASE}/products", a, a.admin,
        json={"product_type_id": laptop_type, "name": product},
        headers=_new(),
    )  # fmt: skip
    assert made.status_code == 201, made.text
    existing = await _asset(world, a, "Already here", serial_number="IMP-1")
    csv = (
        "Name,Product,Serial number,Location,Site\n"
        f"Updated name,{product},IMP-1,Rack 1,\n"
        f"New one,{product},IMP-2,Rack 2,\n"
        f"Bad site,{product},IMP-3,,Nowhere\n"
    ).encode()
    started = await _import(world, a, csv)
    assert started.status_code == 201, started.text
    assert started.json()["dry_run"] is True
    before = await world.sql("SELECT count(*) AS n FROM assets WHERE tenant_id = $1", a.tenant)
    await _run(world, run_asset_imports)
    checked = await _job(world, a, started.json())
    assert checked["status"] == "checked"
    assert (checked["created_count"], checked["updated_count"], checked["failed_count"]) == (
        1,
        1,
        1,
    )
    assert checked["problems"] == [{"row": 4, "field": "site", "code": "site_not_found"}]
    after = await world.sql("SELECT count(*) AS n FROM assets WHERE tenant_id = $1", a.tenant)
    assert after[0]["n"] == before[0]["n"]  # AC2: nothing changed
    assert (await _fresh(world, a, existing))["name"] == "Already here"
    # Run it for real (If-Match on the import).
    ran = await world.call(
        "POST", f"{BASE}/imports/{checked['id']}/run", a, a.admin,
        headers=_match(checked["version"]),
    )  # fmt: skip
    assert ran.status_code == 200, ran.text
    await _run(world, run_asset_imports)
    done = await _job(world, a, checked)
    assert done["status"] == "done"
    assert (done["created_count"], done["updated_count"], done["failed_count"]) == (1, 1, 1)
    # AC3: matched by serial number, updated in "add and update" mode.
    updated = await _fresh(world, a, existing)
    assert (updated["name"], updated["location"]) == ("Updated name", "Rack 1")
    found = await world.call("GET", BASE, a, a.admin, params={"search": "IMP-2"})
    assert [r["name"] for r in found.json()["items"]] == ["New one"]
    # The file is not kept once read.
    content = await world.sql(
        "SELECT content FROM asset_imports WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(done["id"]),
    )
    assert content[0]["content"] is None
    # A run of a finished import is refused.
    again = await world.call(
        "POST", f"{BASE}/imports/{done['id']}/run", a, a.admin, headers=_match(done["version"])
    )
    assert problem(again) == (409, "asset_import_not_checked")


async def test_053_modes_and_vendors(world: World) -> None:
    a = world.a
    vendors = b"Name,Email,Currency\nAcme Supplies,sales@acme.test,usd\nGlobex,,EUR\n"
    started = await world.call(
        "POST", f"{BASE}/imports", a, a.admin,
        params={"name": "v.csv", "kind": "vendors", "mode": "add", "match_on": "name",
                "dry_run": "false"},
        content=vendors, headers={**_new(), "Content-Type": "text/csv"},
    )  # fmt: skip
    assert started.status_code == 201, started.text
    await _run(world, run_asset_imports)
    done = await _job(world, a, started.json())
    assert (done["status"], done["created_count"], done["failed_count"]) == ("done", 2, 0)
    # Add only: a name that exists is refused for that row.
    again = await world.call(
        "POST", f"{BASE}/imports", a, a.admin,
        params={"name": "v.csv", "kind": "vendors", "mode": "add", "match_on": "name",
                "dry_run": "false"},
        content=b"Name\nacme supplies\n", headers={**_new(), "Content-Type": "text/csv"},
    )  # fmt: skip
    await _run(world, run_asset_imports)
    refused = await _job(world, a, again.json())
    assert refused["problems"] == [{"row": 2, "field": "name", "code": "asset_import_exists"}]
    # Update only: an unknown serial is refused for that row.
    update_only = await _import(world, a, b"Serial number,Location\nNOPE-1,X\n", mode="update")
    await _run(world, run_asset_imports)
    missing = await _job(world, a, update_only.json())
    assert missing["problems"] == [
        {"row": 2, "field": "serial_number", "code": "asset_import_no_match"}
    ]
    # A match the kind does not have is refused at once.
    wrong = await _import(world, a, b"Name\nx\n", kind="vendors", match_on="tag")
    assert problem(wrong) == (422, "asset_import_match_invalid")
    # Vendors need the vendor rights: an asset manager without them may not import them.
    manager = await _site_manager(world)
    tech = await _import(world, a, b"Name\nx\n", kind="vendors", match_on="name", user=manager)
    assert problem(tech)[0] == 403


def _xlsx(rows: list[list[str]]) -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415 - only this test writes workbooks

    book = Workbook()
    sheet = book.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _bomb() -> bytes:
    """A valid-looking xlsx whose one entry unpacks to far more than it weighs."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", "0" * 20_000_000)
    return out.getvalue()


async def test_053_file_limits_a_zip_bomb_and_a_broken_file_are_refused(world: World) -> None:
    a = world.a
    cases = [
        (_bomb(), "bomb.xlsx", "file_unsafe"),
        (b"PK\x03\x04 not really a zip", "broken.xlsx", "file_not_readable"),
        (b"Serial number\n" + b"S-1\n" * 20_001, "big.csv", "too_many_rows"),
        (b"Serial number,Colour\nS-1,red\n", "odd.csv", "unknown_column"),
        (b"Name\nNo key\n", "nokey.csv", "no_key_column"),
        ("Serial number\n".encode("utf-16"), "utf16.csv", "file_not_utf8"),
    ]
    for content, name, failure in cases:
        started = await _import(world, a, content, name=name)
        assert started.status_code == 201, (name, started.text)
        await _run(world, run_asset_imports)
        done = await _job(world, a, started.json())
        assert (done["status"], done["failure"]) == ("failed", failure), name
    # Too large is refused at the door, with no import made.
    big = await _import(world, a, b"x" * (5 * 1024 * 1024 + 1))
    assert problem(big) == (422, "asset_import_file_too_large")
    # A real workbook is read (values only).
    book = _xlsx([["Serial number", "Name", "Product"], ["X-1", "From Excel", "nope"]])
    started = await _import(world, a, book, name="ok.xlsx")
    await _run(world, run_asset_imports)
    done = await _job(world, a, started.json())
    assert done["status"] == "checked"
    assert done["problems"] == [{"row": 2, "field": "product", "code": "asset_product_not_found"}]


# --- live progress ----------------------------------------------------------------------------


async def test_progress_reaches_only_the_requesters_channel_with_ids_only(world: World) -> None:
    a = world.a
    one = await _asset(world, a, "Live one")
    assert (
        await _bulk(world, a, a.admin, {"action": "delete", "asset_ids": [one["id"]]})
    ).status_code == 202
    assert (await _import(world, a, b"Serial number\nL-1\n")).status_code == 201
    for event_type, kind in (
        ("assets.bulk_job.progressed", BULK_PROGRESS),
        ("assets.import.progressed", IMPORT_PROGRESS),
    ):
        rows = await world.sql(
            "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2",
            a.tenant,
            event_type,
        )
        envelope = EventEnvelope.model_validate(json.loads(rows[-1]["envelope"]))
        # Counts, codes and IDs only (§8.2).
        assert set(envelope.payload) <= {
            "job_id", "import_id", "requested_by", "status", "processed", "total",
        }  # fmt: skip
        route = next(r for r in ROUTES if event_type in r.event_types)
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            effects = await route.route(envelope, session)
        assert [(p.channel, p.type) for p in effects.publications] == [
            (personal(a.tenant, a.admin), kind)
        ]


# --- isolation --------------------------------------------------------------------------------


async def test_new_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    one = await _asset(world, a, "RLS one")
    two = await _asset(world, a, "RLS two")
    assert (await _merge(world, a, a.admin, one, two)).status_code == 201
    assert (
        await _bulk(world, a, a.admin, {"action": "delete", "asset_ids": [one["id"]]})
    ).status_code == 202
    assert (await _import(world, a, b"Serial number\nR-1\n")).status_code == 201
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in NEW_TABLES:
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608 - fixed names
            changed = await session.execute(text(f"UPDATE {table} SET version = version + 1"))  # noqa: S608 - fixed names
            assert changed.rowcount == 0
        # Nor can tenant B write a row for tenant A.
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO asset_imports (tenant_id, id, kind, mode, match_on, file_name,"
                    " file_format) VALUES (:t, :i, 'assets', 'add', 'tag', 'x.csv', 'csv')"
                ),
                {"t": a.tenant, "i": uuid.uuid4()},
            )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        for table in NEW_TABLES:
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) >= 1  # noqa: S608 - fixed names
    # Tenant B's people find nothing of A's through the API either.
    assert (await world.call("GET", f"{BASE}/imports", b, b.admin)).json() == []
    assert (await world.call("GET", f"{BASE}/bulk-jobs", b, b.admin)).json() == []
