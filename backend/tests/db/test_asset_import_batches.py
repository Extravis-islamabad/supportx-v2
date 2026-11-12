"""Faster asset imports keep every rule (WP-049b S4c; REQ-AST-053; coordinator 2026-11-12).

The import checks rows first, resolves names through a per-job cache, reads the records a
batch matches in one query, writes a batch's rows in one savepoint (redone row by row when any
is refused) and ends each transaction after 100 rows or about 2 s. These tests hold it to the
row path's outcomes: lookups never shared between jobs, tenants or importers (1), permission
per row (2), exact per-row problems when a batch is redone (3), tag numbers only for saved rows
(4), short locks (5), the same caching for consumables, and a dry run that counts the asset
limit as the run will (lane A, #434).

The incident world: org A's admin holds everything; technicians hold assets.view at all and no
assets.manage (D-157). `_site_manager` gives tech A (at site s1) assets.manage at site scope.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from app.core.database import SESSION_TENANT_KEY
from app.core.tenancy import TenantContext
from app.modules.assets.domain.assets import NAME_MAX, SHARED_COUNTER_KEY
from app.modules.assets.service import imports
from app.modules.assets.service.assets import count_managed_assets
from app.modules.assets.service.imports import Lookups, run_asset_imports
from app.modules.organization import find_site
from app.modules.organization.service import structure
from tests.db import test_incidents_api
from tests.db.test_asset_bulk_merge_import_api import (
    _asset,
    _fresh,
    _import,
    _job,
    _run,
    _site_manager,
)
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import Org, World
from tests.db.test_knowledge_api import _match, _new

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"


async def _run_for_real(
    world: World, org: Org, checked: dict[str, Any], user: uuid.UUID
) -> dict[str, Any]:
    """Run a checked dry run (If-Match) and return the finished import."""
    ran = await world.call(
        "POST", f"{BASE}/imports/{checked['id']}/run", org, user, headers=_match(checked["version"])
    )
    assert ran.status_code == 200, ran.text
    await _run(world, run_asset_imports)
    found = await world.call("GET", f"{BASE}/imports/{checked['id']}", org, user)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def _checked(world: World, org: Org, content: bytes, **kw: Any) -> dict[str, Any]:  # noqa: ANN401 - _import's options
    started = await _import(world, org, content, **kw)
    assert started.status_code == 201, started.text
    await _run(world, run_asset_imports)
    user = kw.get("user") or org.admin
    found = await world.call("GET", f"{BASE}/imports/{started.json()['id']}", org, user)
    assert found.status_code == 200, found.text
    body = dict(found.json())
    assert body["status"] == "checked", body
    return body


def _counts(job: dict[str, Any]) -> tuple[int, int, int]:
    return job["created_count"], job["updated_count"], job["failed_count"]


async def _site(world: World, org: Org, name: str) -> uuid.UUID:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant, org.admin)) as session:
        return (await structure.save_site(session, None, {"name": name})).id


async def _site_name(world: World, org: Org, site_id: uuid.UUID) -> str:
    rows = await world.sql(
        "SELECT name FROM sites WHERE tenant_id = $1 AND id = $2", org.tenant, site_id
    )
    return str(rows[0]["name"])


# --- 1: lookups are the job's own ---------------------------------------------------------------


async def test_lookups_refuse_a_session_of_another_tenant_or_importer() -> None:
    """The cache is made per job for one tenant and importer, and checks it on every use."""
    tenant, importer = uuid.uuid4(), uuid.uuid4()
    lookups = Lookups(tenant=tenant, requester=importer)
    for context in (TenantContext(uuid.uuid4(), importer), TenantContext(tenant, uuid.uuid4())):
        other = cast("AsyncSession", SimpleNamespace(info={SESSION_TENANT_KEY: context}))
        with pytest.raises(RuntimeError, match="own tenant and importer"):
            await lookups.site(other, "Anywhere")
        with pytest.raises(RuntimeError, match="own tenant and importer"):
            await lookups.vendor(other, "Anyone")
        with pytest.raises(RuntimeError, match="own tenant and importer"):
            await lookups.product(other, "Anything")
    # Two jobs never hold the same cache.
    assert Lookups(tenant, importer).sites is not Lookups(tenant, importer).sites


async def test_two_imports_by_different_requesters_never_share_lookup_answers(
    world: World,
) -> None:
    a, b = world.a, world.b
    product = f"S4c lookup laptop {uuid.uuid4().hex[:6]}"
    await _product(world, a, "laptop", product)
    late = f"S4c late site {uuid.uuid4().hex[:6]}"
    csv = f"Name,Product,Serial number,Site\nLate one,{product},S4C-L-1,{late}\n".encode()
    # The admin's job: the site does not exist yet.
    first = await _checked(world, a, csv)
    assert first["problems"] == [{"row": 2, "field": "site", "code": "site_not_found"}]
    # The site is added; another person's job (manage at their site only) finds it: nothing of
    # the first job's answers reached the second.
    await _site(world, a, late)
    manager = await _site_manager(world)
    second = await _checked(world, a, csv, user=manager)
    # The site is found (no site_not_found, so the first job's answer was not reused); creating
    # an asset there is refused only because this manager does not manage it (#423).
    assert (_counts(second), second["problems"]) == (
        (0, 0, 1),
        [{"row": 2, "field": "row", "code": "asset_site_not_managed"}],
    )
    # The same site name in two tenants: each tenant's job finds its own.
    twin = f"S4c twin site {uuid.uuid4().hex[:6]}"
    sites = {org.tenant: await _site(world, org, twin) for org in (a, b)}
    for org in (a, b):
        name = f"S4c twin laptop {uuid.uuid4().hex[:6]}"
        await _product(world, org, "laptop", name)
        serial = f"S4C-T-{uuid.uuid4().hex[:6]}"
        content = f"Name,Product,Serial number,Site\nTwin,{name},{serial},{twin}\n".encode()
        checked = await _checked(world, org, content)
        done = await _run_for_real(world, org, checked, org.admin)
        assert _counts(done) == (1, 0, 0), done
        made = await world.sql(
            "SELECT site_id FROM assets WHERE tenant_id = $1 AND serial_number = $2",
            org.tenant,
            serial,
        )
        assert made[0]["site_id"] == sites[org.tenant]


# --- 2: permission per row --------------------------------------------------------------------


async def test_a_mixed_batch_refuses_the_out_of_scope_rows_one_by_one(world: World) -> None:
    """Tech A manages the assets of site s1 only: the s2 rows are refused, row by row."""
    a = world.a
    manager = await _site_manager(world)
    tag = uuid.uuid4().hex[:6]
    near = [
        await _asset(world, a, f"Near {n}", serial_number=f"S4C-P-{tag}-N{n}", site_id=str(a.s1))
        for n in range(3)
    ]
    far = [
        await _asset(world, a, f"Far {n}", serial_number=f"S4C-P-{tag}-F{n}", site_id=str(a.s2))
        for n in range(3)
    ]
    product = f"S4c scope laptop {tag}"
    await _product(world, a, "laptop", product)
    # New assets go to the manager's own site (s1): since #423 one with no site, or at s2, is
    # beyond a site-scoped manager.
    own = (
        await world.sql("SELECT name FROM sites WHERE tenant_id = $1 AND id = $2", a.tenant, a.s1)
    )[0]["name"]
    lines = ["Name,Product,Serial number,Location,Site"]
    order = [near[0], far[0], near[1], far[1], near[2], far[2]]
    lines += [f",,{asset['serial_number']},Shelf S4c," for asset in order]
    lines += [f"New {n},{product},S4C-P-{tag}-NEW{n},Shelf S4c,{own}" for n in range(2)]
    content = ("\n".join(lines) + "\n").encode()
    refused = [
        {"row": row, "field": "row", "code": "permission_denied"} for row in (3, 5, 7)
    ]  # the far rows, in file order (row 1 is the header)
    checked = await _checked(world, a, content, user=manager)
    assert (_counts(checked), checked["problems"]) == ((2, 3, 3), refused)
    done = await _run_for_real(world, a, checked, manager)
    assert (_counts(done), done["problems"]) == ((2, 3, 3), refused)
    for asset in near:
        assert (await _fresh(world, a, asset))["location"] == "Shelf S4c"
    for asset in far:
        assert (await _fresh(world, a, asset))["location"] is None


# --- 3: one bad row in a full batch ------------------------------------------------------------


async def test_one_refused_row_in_a_full_batch_keeps_the_exact_problems(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A service refusal rolls the batch back and redoes it row by row; the rest are kept."""
    a = world.a
    redone: list[int] = []
    one_by_one = imports._one_by_one  # noqa: SLF001 - counts the redo, then does it

    async def counted(*args: Any, **kw: Any) -> int:  # noqa: ANN401 - passed through
        redone.append(len(args[2]))
        return await one_by_one(*args, **kw)

    monkeypatch.setattr(imports, "_one_by_one", counted)
    monkeypatch.setattr(imports, "BATCH_SECONDS", 120.0)  # one transaction, however loaded
    tag = uuid.uuid4().hex[:6]
    product = f"S4c batch laptop {tag}"
    await _product(world, a, "laptop", product)
    lines = ["Name,Product,Serial number,Acquired on"]
    for n in range(1, imports.BATCH + 1):
        name = "x" * (NAME_MAX + 1) if n == 50 else f"Batch {n}"  # the service refuses it
        acquired = "not a date" if n == 10 else ""  # refused before any write
        lines.append(f"{name},{product},S4C-B-{tag}-{n:03d},{acquired}")
    content = ("\n".join(lines) + "\n").encode()
    problems = [
        {"row": 11, "field": "acquired_on", "code": "invalid_date"},
        {"row": 51, "field": "name", "code": "value_too_long"},
    ]
    checked = await _checked(world, a, content)
    assert (_counts(checked), checked["problems"]) == ((imports.BATCH - 2, 0, 2), problems)
    assert redone == [50]  # the batch up to the refused row was redone row by row, once
    done = await _run_for_real(world, a, checked, a.admin)
    assert (_counts(done), done["problems"]) == ((imports.BATCH - 2, 0, 2), problems)
    stored = await world.sql(
        "SELECT count(*) AS n FROM assets WHERE tenant_id = $1 AND serial_number LIKE $2",
        a.tenant,
        f"S4C-B-{tag}-%",
    )
    assert stored[0]["n"] == imports.BATCH - 2
    # Each saved asset still has its own history, event and audit entry.
    ids = await world.sql(
        "SELECT id FROM assets WHERE tenant_id = $1 AND serial_number LIKE $2",
        a.tenant,
        f"S4C-B-{tag}-%",
    )
    asset_ids = [row["id"] for row in ids]
    by_asset = "WHERE tenant_id = $1 AND {column} = ANY($2::{kind}[])"
    checks = (
        ("field_changes", "record_id", "uuid", asset_ids),
        ("outbox_events", "aggregate_id", "text", [str(i) for i in asset_ids]),
        ("audit_entries", "object_id", "text", [str(i) for i in asset_ids]),
    )
    for table, column, kind, wanted in checks:
        where = by_asset.format(column=column, kind=kind)
        statement = f"SELECT count(DISTINCT {column}) AS n FROM {table} {where}"  # noqa: S608 - fixed names
        found = await world.sql(statement, a.tenant, wanted)
        assert found[0]["n"] == imports.BATCH - 2, table


# --- 4: tag numbers ---------------------------------------------------------------------------


async def _tag_numbers(world: World, org: Org) -> int:
    """Every asset tag number the tenant's counters handed out (the shared and per-type ones)."""
    rows = await world.sql(
        "SELECT coalesce(sum(last_value), 0) AS n FROM display_id_sequences "
        "WHERE tenant_id = $1 AND (prefix = $2 OR prefix LIKE 'AT\\_%')",
        org.tenant,
        SHARED_COUNTER_KEY,
    )
    return int(rows[0]["n"])


async def test_a_dry_run_never_takes_tag_numbers_and_a_run_only_for_saved_rows(
    world: World,
) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    product = f"S4c tag laptop {tag}"
    await _product(world, a, "laptop", product)
    rows = 30
    lines = ["Name,Product,Serial number"]
    for n in range(1, rows + 1):
        name = "y" * (NAME_MAX + 1) if n == 20 else f"Tagged {n}"  # refused after rows took tags
        lines.append(f"{name},{product},S4C-G-{tag}-{n:03d}")
    content = ("\n".join(lines) + "\n").encode()
    before = await _tag_numbers(world, a)
    checked = await _checked(world, a, content)
    assert _counts(checked) == (rows - 1, 0, 1)
    assert await _tag_numbers(world, a) == before  # nothing handed out by the dry run
    done = await _run_for_real(world, a, checked, a.admin)
    assert _counts(done) == (rows - 1, 0, 1)
    assert await _tag_numbers(world, a) == before + rows - 1  # one per saved asset, no gaps
    tags = await world.sql(
        "SELECT tag FROM assets WHERE tenant_id = $1 AND serial_number LIKE $2",
        a.tenant,
        f"S4C-G-{tag}-%",
    )
    assert len({row["tag"] for row in tags}) == rows - 1


# --- 5: short locks ---------------------------------------------------------------------------


async def test_a_manual_asset_waits_at_most_about_one_transaction_of_a_running_import(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tag counter and the limit's lock are held until commit: the time bound keeps it short."""
    a = world.a
    monkeypatch.setattr(imports, "BATCH", 100_000)  # only the time bound ends a transaction
    tag = uuid.uuid4().hex[:6]
    product = f"S4c lock laptop {tag}"
    product_id = await _product(world, a, "laptop", product)
    rows = 600
    lines = ["Name,Product,Serial number"]
    lines += [f"Locked {n},{product},S4C-K-{tag}-{n:04d}" for n in range(1, rows + 1)]
    started = await world.call(
        "POST", f"{BASE}/imports", a, a.admin,
        params={"name": "lock.csv", "kind": "assets", "mode": "add", "match_on": "serial_number",
                "dry_run": "false"},
        content=("\n".join(lines) + "\n").encode(),
        headers={**_new(), "Content-Type": "text/csv"},
    )  # fmt: skip
    assert started.status_code == 201, started.text
    job = started.json()
    running = asyncio.create_task(_run(world, run_asset_imports))
    try:
        # Wait for the first commit: the import is then inside a later transaction.
        for _ in range(600):
            now = await _job(world, a, job)
            if now["processed"] > 0:
                break
            await asyncio.sleep(0.05)
        else:  # pragma: no cover - the import never committed
            pytest.fail("the import never committed a batch")
        assert now["processed"] < rows, "the import ended before the manual add could overlap"
        began = time.monotonic()
        made = await _add(world, a, {"name": "Manual meanwhile", "product_id": product_id})
        waited = time.monotonic() - began
        assert made.status_code == 201, made.text
        after = await _job(world, a, job)
        assert after["status"] == "running", "the import ended before the manual add finished"
        assert waited <= 3.0, f"the manual add waited {waited:.2f} s"
    finally:
        await running
    done = await _job(world, a, job)
    assert (done["status"], done["created_count"]) == ("done", rows)


# --- consumables -----------------------------------------------------------------------------


async def test_consumables_are_matched_by_product_and_checked_as_before(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    paper, toner = f"S4c paper {tag}", f"S4c toner {tag}"
    await _product(world, a, "paper", paper)
    await _product(world, a, "toner_and_ink", toner)
    kept = f"S4c kept {tag}"
    kept_id = await _product(world, a, "paper", kept)
    made = await world.call(
        "POST", f"{BASE}/consumables", a, a.admin,
        json={"product_id": kept_id, "batch_tracked": False}, headers=_new(),
    )  # fmt: skip
    assert made.status_code == 201, made.text
    csv = (
        "Product,Barcode,Unit cost,Batch tracked\n"
        f"{kept},KEPT-1,2.50,\n"
        f"{paper},PAPER-1,1.00,no\n"
        f"Nothing {tag},,,\n"
        f"{toner},,abc,\n"
        f"{paper},PAPER-2,,\n"
    ).encode()
    problems = [
        {"row": 4, "field": "product", "code": "asset_product_not_found"},
        {"row": 5, "field": "unit_cost", "code": "invalid_number"},
    ]
    # Dry run: the second paper row also "creates" (each row sees what was there before).
    checked = await _checked(world, a, csv, kind="consumables", match_on="product")
    assert (_counts(checked), checked["problems"]) == ((2, 1, 2), problems)
    # The run: the second paper row finds the one the first just made and updates it.
    done = await _run_for_real(world, a, checked, a.admin)
    assert (_counts(done), done["problems"]) == ((1, 2, 2), problems)
    stored = await world.sql(
        "SELECT c.barcode FROM asset_consumables c JOIN asset_products p ON p.id = c.product_id "
        "WHERE c.tenant_id = $1 AND p.name = $2",
        a.tenant,
        paper,
    )
    assert [row["barcode"] for row in stored] == ["PAPER-2"]


async def test_the_lookups_cache_answers_as_find_site_does(world: World) -> None:
    """Tech A is no member of site s2; the cache finds it as `find_site` does (no scope)."""
    a = world.a
    site_name = await _site_name(world, a, a.s2)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant, a.tech_a)) as session:
        assert await find_site(session, site_name) == a.s2
        lookups = Lookups(tenant=a.tenant, requester=a.tech_a)
        assert await lookups.site(session, f"  {site_name.upper()} ") == a.s2
        assert await lookups.site(session, site_name) == a.s2
        assert await lookups.site(session, f"Nowhere {uuid.uuid4().hex[:6]}") is None
        assert len(lookups.sites) == 2  # one entry per name as compared, answers kept


# --- the asset limit (lane A's #434 review) -----------------------------------------------------
#
# A dry run rolls every row back, so the service's own reservation never sees the slots the
# earlier rows would take; the import's plan takes and frees them in file order instead (dry
# runs only; a real run's `reserve_capacity` under the lock stays the judge). Imports set no
# state, so only a create and a product change (IT asset <-> non-IT) switch counting.


@asynccontextmanager
async def _asset_limit(world: World, org: Org, free: int) -> AsyncIterator[None]:
    """The tenant's asset limit at what it uses now plus `free`, restored afterwards."""
    before = await world.sql(
        "SELECT limits FROM tenant_subscriptions WHERE tenant_id = $1", org.tenant
    )
    async with world.app.state.db.tenant_session(TenantContext(org.tenant, org.admin)) as session:
        used = await count_managed_assets(session)
    await world.sql(
        "UPDATE tenant_subscriptions SET limits = jsonb_set(coalesce(limits, '{}'::jsonb),"
        " '{assets}', to_jsonb($2::int)) WHERE tenant_id = $1",
        org.tenant,
        used + free,
    )
    await world.app.state.entitlements.invalidate(org.tenant)
    try:
        yield
    finally:
        await world.sql(
            "UPDATE tenant_subscriptions SET limits = $2::jsonb WHERE tenant_id = $1",
            org.tenant,
            before[0]["limits"],
        )
        await world.app.state.entitlements.invalidate(org.tenant)


async def _both_runs(
    world: World, org: Org, content: bytes
) -> tuple[dict[str, Any], dict[str, Any]]:
    checked = await _checked(world, org, content)
    return checked, await _run_for_real(world, org, checked, org.admin)


async def _over_the_limit(world: World) -> None:
    a = world.a
    product = f"S4c limit laptop {uuid.uuid4().hex[:6]}"
    await _product(world, a, "laptop", product)
    tag = uuid.uuid4().hex[:6]
    lines = ["Name,Product,Serial number"]
    lines += [f"Limit {n},{product},S4C-LIM-{tag}-{n}" for n in range(4)]
    content = ("\n".join(lines) + "\n").encode()
    refused = [{"row": row, "field": "row", "code": "asset_limit_reached"} for row in (4, 5)]
    async with _asset_limit(world, a, 2):
        checked, done = await _both_runs(world, a, content)
    assert (_counts(checked), checked["problems"]) == ((2, 0, 2), refused)  # the dry run knew
    assert (_counts(done), done["problems"]) == ((2, 0, 2), refused)
    made = await world.sql(
        "SELECT count(*) AS n FROM assets WHERE tenant_id = $1 AND serial_number LIKE $2",
        a.tenant,
        f"S4C-LIM-{tag}-%",
    )
    assert made[0]["n"] == 2  # nothing past the limit was kept


async def test_an_import_that_crosses_the_asset_limit_in_one_batch_stops_where_the_row_path_does(
    world: World,
) -> None:
    """Limit at existing + 2, four new IT assets: rows 4 and 5 refused, dry run and run alike."""
    await _over_the_limit(world)


async def test_the_dry_run_counts_the_asset_limit_across_batches(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two rows a batch: the dry run's second batch knows the slots the first one took."""
    monkeypatch.setattr(imports, "BATCH", 2)
    await _over_the_limit(world)


async def test_a_slot_freed_by_an_earlier_row_lets_a_later_new_asset_in(world: World) -> None:
    """Row 2 moves a counting asset to a non-IT product; row 5's new IT asset then fits."""
    a = world.a
    tag = uuid.uuid4().hex[:6]
    laptop, desk = f"S4c free laptop {tag}", f"S4c free desk {tag}"
    await _product(world, a, "laptop", laptop)
    await _product(world, a, "furniture", desk)
    moved = await _asset(world, a, "Moves to furniture", serial_number=f"S4C-FREE-{tag}-0")
    lines = [
        "Name,Product,Serial number",
        f",{desk},S4C-FREE-{tag}-0",  # row 2: frees its slot
        f"New 1,{laptop},S4C-FREE-{tag}-1",  # row 3: takes the one free slot
        f"Desk,{desk},S4C-FREE-{tag}-2",  # row 4: never counts
        f"New 2,{laptop},S4C-FREE-{tag}-3",  # row 5: takes the freed slot
        f"New 3,{laptop},S4C-FREE-{tag}-4",  # row 6: none left
    ]
    content = ("\n".join(lines) + "\n").encode()
    refused = [{"row": 6, "field": "row", "code": "asset_limit_reached"}]
    async with _asset_limit(world, a, 1):
        checked, done = await _both_runs(world, a, content)
    assert (_counts(checked), checked["problems"]) == ((3, 1, 1), refused)
    assert (_counts(done), done["problems"]) == ((3, 1, 1), refused)
    assert (await _fresh(world, a, moved))["product_id"] != moved["product_id"]
