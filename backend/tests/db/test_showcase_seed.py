"""The showcase seed (D-124 (5)): only `showcase`, through the API, once, nobody else's data."""

import asyncio
import copy
import json
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest

from app.core.config import Settings
from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.audit.infra.signing import LocalSigner, new_key_config, trusted_keys
from app.modules.audit.service.integrity import seal, verify
from app.shared.events.outbox import OUTBOX_TABLE
from conftest import create_tenant, make_settings
from tooling import db_testing
from tooling import showcase_assets as assets
from tooling import showcase_lane_a as lane_a
from tooling import showcase_seed as seed

# The whole showcase is seeded through the API: about 210 s in CI on a quiet runner (setup
# included), more under load. The shards' 300 s per-test limit (ci.yml) would cut it off, so these
# files get their own, still finite: a real hang here fails and names itself too.
pytestmark = [pytest.mark.db, pytest.mark.timeout(900)]


class FakeKeycloak:
    """Just the admin API calls the seed makes, with state, so a second run finds everything."""

    def __init__(self) -> None:
        self.orgs: list[dict[str, Any]] = []
        self.users: dict[str, dict[str, Any]] = {}
        self.roles: dict[str, set[str]] = {}
        self.members: dict[str, set[str]] = {}
        self.passwords: dict[str, str] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:  # noqa: C901, PLR0911, PLR0912 - one branch per call
        path = request.url.path.removeprefix("/admin/realms/supportx")
        method = request.method
        if request.url.path == "/realms/master/protocol/openid-connect/token":
            return httpx.Response(200, json={"access_token": "t"})
        if path == "/organizations" and method == "GET":
            # Like Keycloak: `search` matches the name (exactly with exact=true), never the alias.
            wanted = request.url.params.get("search", "")
            exact = request.url.params.get("exact") == "true"
            found = [
                o for o in self.orgs if (o["name"] == wanted if exact else wanted in o["name"])
            ]
            # Brief answers, like Keycloak's search: no attributes.
            brief = [{k: v for k, v in o.items() if k != "attributes"} for o in found]
            return httpx.Response(200, json=brief)
        if path.startswith("/organizations/") and path.count("/") == 2 and method == "GET":
            org = next(o for o in self.orgs if o["id"] == path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=org)
        if path == "/organizations" and method == "POST":
            org = {**json.loads(request.content), "id": "org-1"}
            self.orgs.append(org)
            self.members["org-1"] = set()
            return httpx.Response(201, headers={"Location": "/organizations/org-1"})
        if path == "/users" and method == "GET":
            email = request.url.params["email"]
            found = [u for u in self.users.values() if u["email"] == email]
            return httpx.Response(200, json=found)
        if path == "/users" and method == "POST":
            body = json.loads(request.content)
            user_id = str(uuid.uuid4())
            self.users[user_id] = {**body, "id": user_id}
            self.roles[user_id] = set()
            return httpx.Response(201, headers={"Location": f"/users/{user_id}"})
        if path.endswith("/credentials"):
            user_id = path.split("/")[2]
            held = [{"type": "password"}] if user_id in self.passwords else []
            return httpx.Response(200, json=held)
        if path.endswith("/reset-password"):
            self.passwords[path.split("/")[2]] = json.loads(request.content)["value"]
            return httpx.Response(204)
        if path.startswith("/roles/"):
            return httpx.Response(200, json={"name": path.rsplit("/", 1)[-1]})
        if path.endswith("/role-mappings/realm"):
            user_id = path.split("/")[2]
            if method == "GET":
                return httpx.Response(200, json=[{"name": r} for r in self.roles[user_id]])
            self.roles[user_id] |= {r["name"] for r in json.loads(request.content)}
            return httpx.Response(204)
        if path.endswith("/members"):
            org_id = path.split("/")[2]
            if method == "GET":
                return httpx.Response(200, json=[{"id": m} for m in self.members[org_id]])
            self.members[org_id].add(json.loads(request.content))
            return httpx.Response(201)
        return httpx.Response(404, json={"error": f"{method} {path}"})


async def _counts(url: str, tenant: uuid.UUID) -> dict[str, int]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            return {
                table: await conn.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed names
                for table in ("users", "work_items", "sites", "support_groups", "dashboards")
            }
    finally:
        await conn.close()


async def _slas(url: str) -> Counter[str]:
    """Each incident's SLA policy by name; "none" when it has no target clock."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            rows = await conn.fetch(
                "SELECT CASE WHEN EXISTS (SELECT FROM sla_targets t WHERE t.record_id = w.id)"
                " THEN p.name ELSE 'none' END AS name FROM work_items w"
                " LEFT JOIN sla_applications a ON a.record_id = w.id"
                " LEFT JOIN sla_policies p ON p.id = a.policy_id"
                " WHERE w.type = 'incident'"
            )
    finally:
        await conn.close()
    return Counter(r["name"] for r in rows)


async def _states(url: str) -> Counter[str]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            rows = await conn.fetch(
                "SELECT type, status, technician_id, known_error_at IS NOT NULL AS known"
                " FROM work_items WHERE type <> 'release'"
            )
    finally:
        await conn.close()
    return Counter(
        f"{'' if r['type'] == 'incident' else r['type'] + ' '}{r['status']}"
        f"{'' if r['technician_id'] or r['type'] != 'incident' else ' unassigned'}"
        f"{' known error' if r['known'] else ''}"
        for r in rows
    )


async def _without_a_manager(url: str) -> int:
    """QA6-SR-01: people (and the sign-ins) left with nobody to approve their requests."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            found: int = await conn.fetchval(
                "SELECT count(*) FROM users WHERE manager_id IS NULL AND user_type = 'requester'"
            )
    finally:
        await conn.close()
    return found


async def _run(database: db_testing.ThrowawayDatabase, keycloak: FakeKeycloak) -> seed.Report:
    settings = make_settings(
        database_url=database.app_url, migration_database_url=database.migrator_url
    )
    target = seed.KeycloakTarget("http://kc", "admin", "pw", "Showcase-Pass-2026!")
    report = seed.Report()
    report.tenant = await seed.ensure_tenant(database.migrator_url)
    transport = httpx.MockTransport(keycloak.handle)
    async with httpx.AsyncClient(base_url="http://kc", transport=transport) as client:
        found = await seed.ensure_keycloak(client, target)
    report.keycloak = found.made
    await seed.fill(settings, found.subjects, report)
    report.backdated = await seed.backdate(database.migrator_url, report.made)  # step 5
    report.sla_from_creation = await seed.sla_from_creation(  # step 6
        settings, seed.TENANT_ID, report.admin_id, report.without_sla
    )
    return report


async def _by_hand(database: db_testing.ThrowawayDatabase) -> str:
    """An incident the showcase admin makes at the console (not the seed), with an edit."""
    conn = await asyncpg.connect(database.migrator_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            admin: uuid.UUID = await conn.fetchval(
                "SELECT id FROM users WHERE email = $1", seed.ADMIN.email
            )
    finally:
        await conn.close()
    settings = make_settings(
        database_url=database.app_url, migration_database_url=database.migrator_url
    )
    contexts = {admin: TenantContext(seed.TENANT_ID, admin, roles=frozenset(seed.ADMIN.roles))}
    async with seed.console_api(settings, contexts) as client:
        person = seed.Api(client, admin)  # its own helper: nothing it makes is the seed's
        record = await person.call(
            "POST",
            "/api/v1/incidents",
            json={"subject": "QA-2026-11-09 made by hand", "requester_id": str(admin)},
            idempotency=str(uuid.uuid4()),
        )
        await person.call(
            "PATCH",
            f"/api/v1/incidents/{record['id']}",
            json={"urgency": "high"},
            version=record["version"],
        )
    return str(record["id"])


@dataclass(frozen=True)
class SeedAssets:
    """The seed's assets as the database has them (lane B's section, tooling/showcase_assets)."""

    holders: dict[str, str | None]  # tag -> "user <email>", "department <name>", "asset <tag>"
    versions: dict[str, int]
    trashed: set[str]
    loans: dict[str, str]  # tag of an asset out on an open loan -> the borrower's e-mail
    groups: dict[str, set[str]]  # static group name -> its members' tags
    products: set[str]


async def _seed_assets(url: str) -> SeedAssets:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            rows = await conn.fetch(
                "SELECT a.tag, a.version, a.deleted_at IS NOT NULL AS trashed, u.email,"
                " d.name AS department, p.tag AS parent FROM assets a"
                " LEFT JOIN users u ON u.id = a.owner_user_id"
                " LEFT JOIN departments d ON d.id = a.department_id"
                " LEFT JOIN assets p ON p.id = a.parent_asset_id"
                " WHERE a.tag LIKE 'SX-%'"
            )
            loans = await conn.fetch(
                "SELECT a.tag, u.email FROM asset_loans l"
                " JOIN asset_loan_items i ON i.loan_id = l.id AND i.returned_at IS NULL"
                " JOIN assets a ON a.id = i.asset_id JOIN users u ON u.id = l.borrower_id"
                " WHERE l.closed_at IS NULL"
            )
            members = await conn.fetch(
                "SELECT g.name, a.tag FROM asset_groups g"
                " JOIN asset_group_members m ON m.group_id = g.id"
                " JOIN assets a ON a.id = m.asset_id"
                " WHERE g.kind = 'static' AND g.deleted_at IS NULL"
            )
            products = await conn.fetch("SELECT name FROM asset_products WHERE deleted_at IS NULL")
    finally:
        await conn.close()

    def holder(r: asyncpg.Record) -> str | None:
        if r["email"]:
            return f"user {r['email']}"
        if r["department"]:
            return f"department {r['department']}"
        return f"asset {r['parent']}" if r["parent"] else None

    groups: dict[str, set[str]] = {}
    for m in members:
        groups.setdefault(m["name"], set()).add(m["tag"])
    return SeedAssets(
        holders={r["tag"]: holder(r) for r in rows if not r["trashed"]},
        versions={r["tag"]: r["version"] for r in rows},
        trashed={r["tag"] for r in rows if r["trashed"]},
        loans={r["tag"]: r["email"] for r in loans},
        groups=groups,
        products={r["name"] for r in products},
    )


async def _first_assets(first: seed.Report, url: str) -> SeedAssets:
    """Lane B: assets to show (the visual matrix's asset screen), as the first run made them."""
    # The products, the assets, three holders (a person, a department, the monitor's desktop),
    # the loanable mark, the loan, the group and its three members.
    assert first.assets == len(assets.PRODUCTS) + len(assets.ASSETS) + 3 + 1 + 1 + 1 + 3 == 22
    found = await _seed_assets(url)
    assert found.products == {p.name for p in assets.PRODUCTS} | {
        c.product.name for c in assets.CONSUMABLES
    }
    assert found.holders == {
        "SX-LAP-001": f"user {seed.REQUESTER.email}",
        "SX-DSK-001": f"department {assets.DEPARTMENT}",
        "SX-MON-001": "asset SX-DSK-001",  # the component
        "SX-LAP-002": f"user {seed.NEW_STARTER.email}",  # the loan gives it to the borrower
        "SX-LAP-003": None,
        "SX-PHN-001": None,
        "SX-PRN-001": None,
        "SX-MON-002": None,
    }
    assert found.loans == {"SX-LAP-002": seed.NEW_STARTER.email}
    assert found.groups == {assets.GROUP: set(assets.GROUP_MEMBERS)}
    assert found.trashed == set()
    assert found.versions["SX-PRN-001"] == assets.CREATED  # the seed's own, never saved again
    return found


@dataclass(frozen=True)
class SeedStock:
    """The seed's consumables as the database has them (WP-049b s1, tooling/showcase_assets)."""

    consumables: dict[str, bool]  # product name -> batch tracked
    stocks: dict[tuple[str, str], str]  # (product, site) -> quantity
    lots: dict[str, tuple[str, int]]  # product -> (lot number, days from today to expiry)
    movements: dict[tuple[str, str], int]  # (product, kind) -> how many
    rules: dict[str, tuple[str, str]]  # product -> (site, minimum)
    bookings: dict[str, tuple[str, str, int]]  # asset tag -> (borrower, status, days ahead)


def _qty(value: Any) -> str:  # noqa: ANN401 - asyncpg's Decimal
    return f"{value.normalize():f}"


async def _seed_stock(url: str) -> SeedStock:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            consumables = await conn.fetch(
                "SELECT p.name, c.batch_tracked FROM asset_consumables c"
                " JOIN asset_products p ON p.id = c.product_id"
                " WHERE c.tenant_id = $1 AND c.deleted_at IS NULL",
                seed.TENANT_ID,
            )
            stocks = await conn.fetch(
                "SELECT p.name, s2.name AS site, s.quantity FROM asset_consumable_stocks s"
                " JOIN asset_consumables c ON c.id = s.consumable_id"
                " JOIN asset_products p ON p.id = c.product_id"
                " JOIN sites s2 ON s2.id = s.site_id"
                " WHERE c.tenant_id = $1 AND c.deleted_at IS NULL",
                seed.TENANT_ID,
            )
            lots = await conn.fetch(
                "SELECT p.name, b.lot_number, b.expires_on - current_date AS days"
                " FROM asset_consumable_batches b"
                " JOIN asset_consumables c ON c.id = b.consumable_id"
                " JOIN asset_products p ON p.id = c.product_id"
                " WHERE c.tenant_id = $1 AND c.deleted_at IS NULL",
                seed.TENANT_ID,
            )
            movements = await conn.fetch(
                "SELECT p.name, m.kind, count(*) AS n FROM asset_consumable_movements m"
                " JOIN asset_consumables c ON c.id = m.consumable_id"
                " JOIN asset_products p ON p.id = c.product_id"
                " WHERE c.tenant_id = $1 AND c.deleted_at IS NULL"
                " GROUP BY p.name, m.kind",
                seed.TENANT_ID,
            )
            rules = await conn.fetch(
                "SELECT p.name, s.name AS site, r.min_quantity FROM asset_stock_rules r"
                " JOIN asset_products p ON p.id = r.product_id JOIN sites s ON s.id = r.site_id"
                " WHERE r.tenant_id = $1 AND r.deleted_at IS NULL",
                seed.TENANT_ID,
            )
            bookings = await conn.fetch(
                "SELECT a.tag, u.email, b.status,"
                # Rounded, not truncated: a booking made 14 days ahead is 13 days 23:59:59 away
                # a moment later, so truncating made the reads before and after the re-run
                # differ by one whenever a second passed between them (flake, 2026-11-12).
                " round(extract(epoch FROM b.starts_at - now()) / 86400)::int AS days"
                " FROM asset_bookings b"
                " JOIN assets a ON a.id = b.asset_id JOIN users u ON u.id = b.borrower_id"
                " WHERE b.tenant_id = $1 AND b.deleted_at IS NULL",
                seed.TENANT_ID,
            )
    finally:
        await conn.close()
    return SeedStock(
        consumables={r["name"]: r["batch_tracked"] for r in consumables},
        stocks={(r["name"], r["site"]): _qty(r["quantity"]) for r in stocks},
        lots={r["name"]: (r["lot_number"], r["days"]) for r in lots},
        movements={(r["name"], r["kind"]): r["n"] for r in movements},
        rules={r["name"]: (r["site"], _qty(r["min_quantity"])) for r in rules},
        bookings={r["tag"]: (r["email"], r["status"], r["days"]) for r in bookings},
    )


async def _seed_audit(url: str) -> tuple[str, int, list[str], int]:
    """The seed's audit (state, marked items, their results) and the laptop's scans."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            state = await conn.fetchval(
                "SELECT state FROM asset_audits WHERE name = $1", assets.AUDIT
            )
            results = await conn.fetch(
                "SELECT i.result FROM asset_audit_items i JOIN asset_audits a ON a.id = i.audit_id"
                " WHERE a.name = $1 AND i.result IS NOT NULL ORDER BY i.result",
                assets.AUDIT,
            )
            scans = await conn.fetchval(
                "SELECT count(*) FROM asset_scans s JOIN assets a ON a.id = s.asset_id"
                " WHERE a.tag = $1",
                assets.SCANNED,
            )
    finally:
        await conn.close()
    return str(state), len(results), [r["result"] for r in results], int(scans)


def _first_audit(first: seed.Report, database: db_testing.ThrowawayDatabase) -> Any:  # noqa: ANN401 - the row
    """WP-049b s3: a running audit (made, started, three marks) and two scans to show."""
    assert (first.audit, first.scans) == (2 + len(assets.AUDIT_MARKS), 2)
    audit = asyncio.run(_seed_audit(database.migrator_url))
    assert audit == ("running", 3, ["damaged", "found", "wrong_place"], 2)
    return audit


async def _consumables_listed(database: db_testing.ThrowawayDatabase) -> list[dict[str, Any]]:
    """The consumables list as the console (and the visual matrix's lookup) gets it."""
    conn = await asyncpg.connect(database.migrator_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            admin: uuid.UUID = await conn.fetchval(
                "SELECT id FROM users WHERE email = $1", seed.ADMIN.email
            )
    finally:
        await conn.close()
    settings = make_settings(
        database_url=database.app_url, migration_database_url=database.migrator_url
    )
    contexts = {admin: TenantContext(seed.TENANT_ID, admin, roles=frozenset(seed.ADMIN.roles))}
    async with seed.console_api(settings, contexts) as client:
        listed: list[dict[str, Any]] = await seed.Api(client, admin).call(
            "GET", "/api/v1/assets/consumables"
        )
        return listed


async def _first_stock(first: seed.Report, database: db_testing.ThrowawayDatabase) -> SeedStock:
    """WP-049b s1: consumables to show (the visual matrix's consumable screen), as made first."""
    # Three products, three consumables, seven movements, the minimum and the booking.
    assert first.stock == 3 + 3 + 7 + 1 + 1 == 15
    found = await _seed_stock(database.migrator_url)
    toner, paper, keys = (c.product.name for c in assets.CONSUMABLES)
    hq, dubai = assets.HQ, assets.DUBAI
    assert found.consumables == {toner: True, paper: False, keys: False}
    assert found.stocks == {
        (toner, hq): "4",
        (paper, hq): "35",
        (paper, dubai): "25",
        (keys, hq): "9",
    }
    assert found.lots == {toner: ("CF259A-LOT-01", 300)}  # relative to today
    assert found.movements == {
        (toner, "receive"): 1, (toner, "allocate"): 1,
        (paper, "receive"): 2, (paper, "allocate"): 1,
        (keys, "receive"): 1, (keys, "allocate"): 1,
    }  # fmt: skip
    assert found.rules == {toner: (hq, "5")}
    borrower, status, days = found.bookings[assets.BOOKED]
    assert (borrower, status) == (seed.REQUESTER.email, "booked")
    assert assets.LOAN_DAYS < days <= assets.BOOKING_IN_DAYS  # after the loan, from now
    assert len(found.bookings) == 1
    # The visual matrix's `consumable` lookup: the first of this list, with the "low" state.
    listed = await _consumables_listed(database)
    assert {c["product_name"] for c in listed} == {toner, paper, keys}
    low = {(c["product_name"], s["low"]) for c in listed for s in c["stocks"] if s["low"]}
    assert low == {(toner, True)}
    return found


async def _assets_by_hand(database: db_testing.ThrowawayDatabase) -> None:
    """The showcase admin at the console changes three of the seed's assets.

    Takes the person's laptop back (held by no one now), takes the loaned laptop back early (the
    loan closes; the asset is unheld and still loanable) and puts the printer in the trash: each
    a state the seed's own steps would act on, were it still as the seed left it.
    """
    conn = await asyncpg.connect(database.migrator_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            admin: uuid.UUID = await conn.fetchval(
                "SELECT id FROM users WHERE email = $1", seed.ADMIN.email
            )
    finally:
        await conn.close()
    settings = make_settings(
        database_url=database.app_url, migration_database_url=database.migrator_url
    )
    contexts = {admin: TenantContext(seed.TENANT_ID, admin, roles=frozenset(seed.ADMIN.roles))}
    async with seed.console_api(settings, contexts) as client:
        person = seed.Api(client, admin)  # its own helper: nothing it does is the seed's
        tags = {a["tag"]: a for a in await person.all_pages("/api/v1/assets")}
        laptop = tags["SX-LAP-001"]
        await person.call(
            "DELETE", f"/api/v1/assets/{laptop['id']}/holder", version=laptop["version"]
        )
        loaner = tags["SX-LAP-002"]
        loan = next(
            loan
            for loan in await person.call("GET", "/api/v1/assets/loans")
            if any(a["id"] == loaner["id"] for a in loan["assets"])
        )
        await person.call(
            "POST",
            f"/api/v1/assets/loans/{loan['id']}/returns",
            json={"asset_ids": [loaner["id"]]},
        )
        printer = tags["SX-PRN-001"]
        await person.call("DELETE", f"/api/v1/assets/{printer['id']}", version=printer["version"])


async def _times_of(url: str, record_id: str) -> tuple[Any, ...]:
    """The incident's own times and every history row's time, to compare after a run."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            row = await conn.fetchrow(
                "SELECT created_at, updated_at FROM work_items WHERE id = $1", uuid.UUID(record_id)
            )
            history = await conn.fetch(
                "SELECT id, occurred_at FROM field_changes"
                " WHERE record_type = 'work_item' AND record_id = $1 ORDER BY id",
                uuid.UUID(record_id),
            )
    finally:
        await conn.close()
    assert row is not None
    return (row["created_at"], row["updated_at"], [tuple(h) for h in history])


def test_a_weak_password_is_named_before_keycloak_is_asked() -> None:
    assert seed.password_problem("short") == "must be set, 12 characters or more"
    assert seed.password_problem("0123456789abcdef") == (
        "needs an upper-case letter, a special character"
    )
    assert seed.password_problem("Showcase-Pass-2026!") is None


def test_refuses_every_slug_but_showcase(production_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    for slug in ("demo", "other", "showcase2", ""):
        assert seed.refuse(slug, settings) is not None
    assert seed.refuse("showcase", settings) is None
    assert seed.refuse("showcase", production_settings()) is not None


async def _audit_chain(app_url: str) -> str:
    """Seal the showcase tenant's queued audit entries and verify its whole hash chain."""
    database = Database.from_settings(make_settings(database_url=app_url))
    assert database is not None
    signer = LocalSigner.from_config(new_key_config("showcase-test"))
    try:
        async with database.tenant_session(TenantContext(seed.TENANT_ID)) as session:
            await seal(session, 500)
        async with database.tenant_session(TenantContext(seed.TENANT_ID)) as session:
            result = await verify(session, kind="on_demand", trusted_keys=trusted_keys("", signer))
    finally:
        await database.dispose()
    return str(result.status)


async def _shift_one_audit_entry(admin_url: str) -> str:
    """Move one showcase audit entry back a day: 'shifted', or 'refused' by the database."""
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(
            "UPDATE audit_entries SET occurred_at = occurred_at - interval '1 day'"
            " WHERE id = (SELECT id FROM audit_entries WHERE tenant_id = $1 LIMIT 1)",
            seed.TENANT_ID,
        )
    except asyncpg.PostgresError:
        return "refused"
    finally:
        await conn.close()
    return "shifted"


async def _backdating_is_consistent(url: str) -> list[str]:
    """What is wrong with the showcase dates after step 5, as readable lines (empty: fine)."""
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(seed.TENANT_ID))
        rows = await conn.fetch(
            "SELECT w.display_id, w.created_at, w.first_responded_at, w.resolved_at,"
            " w.closed_at, t.created_at AS tenant_created"
            " FROM work_items w JOIN tenants t ON t.id = w.tenant_id"
            " WHERE w.tenant_id = $1 AND w.type = 'incident'",  # what step 5 spreads
            seed.TENANT_ID,
        )
        history_ahead = await conn.fetchval(
            "SELECT count(*) FROM field_changes f JOIN work_items w ON w.id = f.record_id"
            " WHERE f.record_type = 'work_item' AND w.tenant_id = $1 AND w.type = 'incident'"
            " AND f.occurred_at < w.created_at - interval '1 second'",
            seed.TENANT_ID,
        )
    finally:
        await conn.close()
    wrong = [f"history before its incident: {history_ahead}"] if history_ahead else []
    days = {r["created_at"].date() for r in rows}
    if len(days) < 10:
        wrong.append(f"only {len(days)} distinct days")
    for r in rows:
        window = r["tenant_created"] - timedelta(days=31)
        if not window <= r["created_at"] < r["tenant_created"]:
            wrong.append(f"{r['display_id']} outside the 30 days")
        times = [r["created_at"], r["first_responded_at"], r["resolved_at"], r["closed_at"]]
        present = [t for t in times if t is not None]
        if present != sorted(present):
            wrong.append(f"{r['display_id']} times out of order")
    return wrong


IMPORTED = "imported-tech"


@dataclass(frozen=True)
class Seeded:
    """The first seed run, made once per module (~a minute); every test copies it."""

    template: db_testing.ThrowawayDatabase
    keycloak: FakeKeycloak
    first: seed.Report
    bystander: uuid.UUID
    before: dict[str, int]


@pytest.fixture(scope="module")
def seeded(db_config: db_testing.DbTestConfig) -> Iterator[Seeded]:
    """A bystander tenant, then the seed's first run, as the template of each test's database.

    Only the first run is shared. Every later run (the "nothing changes" re-runs, the step-6
    run after a hand-made record) runs again in each test, on that test's own copy.
    """
    template = db_testing.create(db_config)
    try:
        bystander = asyncio.run(create_tenant(template.migrator_url, "Bystander"))
        before = asyncio.run(_counts(template.migrator_url, bystander))
        keycloak = FakeKeycloak()
        # The technician came from the dev realm file without a password: the seed gives one.
        keycloak.users[IMPORTED] = {"id": IMPORTED, "email": seed.TECHNICIAN.email}
        keycloak.roles[IMPORTED] = set()
        first = asyncio.run(_run(template, keycloak))
        yield Seeded(template, keycloak, first, bystander, before)
    finally:
        db_testing.destroy(db_config, template)


@pytest.fixture
def seeded_copy(
    db_config: db_testing.DbTestConfig, seeded: Seeded
) -> Iterator[tuple[db_testing.ThrowawayDatabase, FakeKeycloak]]:
    """This test's own copy of the seeded database and of Keycloak's state."""
    database = db_testing.clone(db_config, seeded.template)
    try:
        yield database, copy.deepcopy(seeded.keycloak)
    finally:
        db_testing.destroy(db_config, database)


def test_fills_showcase_through_the_api_once_and_leaves_other_tenants_alone(
    seeded: Seeded, seeded_copy: tuple[db_testing.ThrowawayDatabase, FakeKeycloak]
) -> None:
    database, keycloak = seeded_copy
    first, bystander, before, imported = seeded.first, seeded.bystander, seeded.before, IMPORTED
    assert first.tenant == ["tenant", "subscription", "starter_catalog"]
    assert first.catalog_published == 14  # the starter catalog (D-138), with its group
    assert first.incidents == len(seed.STATES) == 60
    # QA6-DATA-01: service requests in every state, problems with known errors.
    # And three in Arabic and Urdu, with two problems (right-to-left records to show).
    assert first.service_requests == len(lane_a.REQUESTS) + len(lane_a.LOCAL_REQUESTS) == 10
    assert first.problems == len(lane_a.PROBLEMS) == 5
    assert first.featured == len(lane_a.FEATURED) == 3
    assert first.rules == len(lane_a.RULES) == 3
    assert first.managers == sum(p.user_type == "requester" for p in seed.PEOPLE) + 1
    assert first.dashboard
    # QA6-DATA-01: knowledge and releases to show, not empty modules.
    assert first.articles == len(seed.KB_ARTICLES) == 5
    assert first.releases == len(seed.RELEASES) == 2
    found = asyncio.run(_first_assets(first, database.migrator_url))
    stock = asyncio.run(_first_stock(first, database))
    audit = _first_audit(first, database)
    assert first.backdated == 75  # spread over the past 30 days (choice (b)); not releases
    assert asyncio.run(_backdating_is_consistent(database.migrator_url)) == []
    assert asyncio.run(_audit_chain(database.app_url)) == "passed"  # never shifted
    # The password is the environment's, set only on the users made here.
    assert keycloak.passwords == dict.fromkeys(keycloak.users, "Showcase-Pass-2026!")
    assert any(f"password {seed.TECHNICIAN.email}" == m for m in first.keycloak)
    keycloak.passwords[imported] = "Changed-By-Hand-1!"  # never overwritten
    assert {u["email"] for u in keycloak.users.values()} == {s.email for s in seed.SIGN_INS}
    counts = asyncio.run(_counts(database.migrator_url, seed.TENANT_ID))
    assert counts["users"] == len(seed.PEOPLE) + len(seed.SIGN_INS)
    assert counts["work_items"] == 75 + len(seed.RELEASES)
    assert asyncio.run(_without_a_manager(database.migrator_url)) == 0
    # Named SLAs with live countdowns, not "No SLA applies" (QA9, Haider): every incident
    # has targets, the urgent ones and the network ones on the showcase's own policies.
    assert first.sla_policies == len(lane_a.SLA_POLICIES) == 2
    assert first.sla_from_creation == 0  # every new incident took its SLA when created
    slas = asyncio.run(_slas(database.migrator_url))
    assert slas["none"] == 0
    assert slas["Critical and high incidents"] == 10  # p1 and p2
    assert slas["Network and access faults"] > 0
    assert asyncio.run(_states(database.migrator_url)) == {
        "service_request awaiting_approval": 3,
        "service_request in_progress": 2,
        "service_request fulfilled": 2,
        "service_request closed": 1,
        "service_request rejected": 1,
        "service_request canceled": 1,
        "problem assigned known error": 3,  # the creator owns a new problem (#267)
        "problem assigned": 2,
        "new unassigned": 10,
        "assigned": 14,
        "in_progress": 12,
        "awaiting_requester": 6,
        "resolved": 10,
        "closed": 8,
    }

    # QA 2026-11-09 (INC-62): a record someone else made keeps its times and its history.
    by_hand = asyncio.run(_by_hand(database))
    untouched = asyncio.run(_times_of(database.migrator_url, by_hand))
    assert untouched[2], "the edit wrote history to compare"

    second = asyncio.run(_run(database, keycloak))
    assert asyncio.run(_times_of(database.migrator_url, by_hand)) == untouched
    assert (
        second.tenant,
        second.keycloak,
        second.incidents,
        second.dashboard,
        second.catalog_published,
        second.articles,
        second.releases,
        second.assets,
        second.stock,
        second.service_requests,
        second.problems,
        second.managers,
        second.rules,
        second.featured,
        second.sla_policies,
        second.sla_from_creation,
        second.audit,
        second.scans,
    ) == ([], [], 0, False, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    assert asyncio.run(_seed_audit(database.migrator_url)) == audit
    assert second.backdated == 0  # nothing made now, so nothing moved
    assert asyncio.run(_seed_assets(database.migrator_url)) == found
    assert asyncio.run(_seed_stock(database.migrator_url)) == stock
    assert asyncio.run(_audit_chain(database.app_url)) == "passed"
    # The check has teeth: an audit entry shifted as step 5 must never do is caught (or the
    # database refuses the change outright).
    if asyncio.run(_shift_one_audit_entry(database.admin_url)) == "shifted":
        assert asyncio.run(_audit_chain(database.app_url)) == "failed"
    assert asyncio.run(_counts(database.migrator_url, seed.TENANT_ID)) == {
        **counts,
        "work_items": counts["work_items"] + 1,  # the one made by hand
    }
    assert asyncio.run(_counts(database.migrator_url, bystander)) == before
    assert keycloak.passwords[imported] == "Changed-By-Hand-1!"


def test_seed_assets_changed_by_hand_stay_as_the_person_left_them(
    seeded_copy: tuple[db_testing.ThrowawayDatabase, FakeKeycloak],
) -> None:
    """Rule 3 (lanes A and C): never given back, lent again or remade after a person's change."""
    database, keycloak = seeded_copy
    asyncio.run(_assets_by_hand(database))
    by_hand = asyncio.run(_seed_assets(database.migrator_url))
    # Each is now in a state the seed's steps would act on, were it still as the seed left it.
    assert by_hand.holders["SX-LAP-001"] is None
    assert by_hand.holders["SX-LAP-002"] is None
    assert by_hand.loans == {}
    assert by_hand.trashed == {"SX-PRN-001"}

    stock = asyncio.run(_seed_stock(database.migrator_url))

    again = asyncio.run(_run(database, keycloak))
    assert (again.assets, again.stock) == (0, 0)
    assert asyncio.run(_seed_assets(database.migrator_url)) == by_hand
    assert asyncio.run(_seed_stock(database.migrator_url)) == stock  # the booking stays too


# --- step 6: SLAs from creation for incidents made before any SLA (Haider, 2026-11-09) --------

_SLA_ROWS = """
WITH r AS (SELECT unnest($1::uuid[]) AS id),
t AS (SELECT s.id FROM sla_targets s JOIN r ON s.record_id = r.id),
e AS (DELETE FROM sla_escalation_runs WHERE target_id IN (SELECT id FROM t)),
p AS (DELETE FROM sla_pauses WHERE target_id IN (SELECT id FROM t)),
d AS (DELETE FROM sla_targets WHERE id IN (SELECT id FROM t))
DELETE FROM sla_applications WHERE record_id IN (SELECT id FROM r)
"""


async def _hand_made(database: db_testing.ThrowawayDatabase) -> uuid.UUID:
    """An incident a person makes through the API: the technician, a seed subject and requester."""
    settings = make_settings(
        database_url=database.app_url, migration_database_url=database.migrator_url
    )
    conn = await asyncpg.connect(database.admin_url)
    try:
        tech = await conn.fetchval(
            "SELECT id FROM users WHERE tenant_id = $1 AND email = $2",
            seed.TENANT_ID,
            seed.TECHNICIAN.email,
        )
        requester = await conn.fetchval(
            "SELECT requester_id FROM work_items WHERE tenant_id = $1 AND type = 'incident'"
            " AND subject = $2 LIMIT 1",
            seed.TENANT_ID,
            seed.SUBJECTS[0][0],
        )
    finally:
        await conn.close()
    contexts = {tech: TenantContext(seed.TENANT_ID, tech, roles=frozenset(seed.TECHNICIAN.roles))}
    async with seed.console_api(settings, contexts) as client:
        made = await seed.Api(client, tech).call(
            "POST",
            "/api/v1/incidents",
            json={
                "subject": seed.SUBJECTS[0][0],
                "requester_id": str(requester),
                "confirm_lose_access": True,  # outside their group: they keep following
                "keep_following": True,
            },
            idempotency=str(uuid.uuid4()),
        )
    return uuid.UUID(made["id"])


async def _row_and_history(url: str, record_id: uuid.UUID) -> tuple[Any, ...]:
    """A record's times, SLA columns and history, to prove nothing about it changed."""
    conn = await asyncpg.connect(url)
    try:
        row = await conn.fetchrow(
            "SELECT version, created_at, updated_at, sla_policy_id, resolution_due_at"
            " FROM work_items WHERE id = $1",
            record_id,
        )
        history = await conn.fetch(
            "SELECT id, occurred_at FROM field_changes WHERE record_id = $1 ORDER BY id", record_id
        )
        slas = await conn.fetchval(
            "SELECT count(*) FROM sla_targets WHERE record_id = $1", record_id
        )
    finally:
        await conn.close()
    assert row is not None
    return (tuple(row), [tuple(h) for h in history], slas)


async def _as_before_slas(url: str, extra: Sequence[uuid.UUID] = ()) -> tuple[uuid.UUID, uuid.UUID]:
    """Test data only: two seeded incidents as the shared stack's older ones are, with no SLA.

    One urgent (4 h to resolve) and open since its backdated creation days ago; one answered in
    5 and resolved in 20 minutes. Returns (open, quick).
    """
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            open_id = await conn.fetchval(
                "SELECT id FROM work_items WHERE type = 'incident' AND status_category = 'open'"
                " AND priority IN ('p1', 'p2') AND created_at < now() - interval '2 days'"
                " ORDER BY display_id LIMIT 1"
            )
            quick_id = await conn.fetchval(
                "SELECT id FROM work_items WHERE type = 'incident' AND status = 'resolved'"
                " ORDER BY display_id LIMIT 1"
            )
            ids = [open_id, quick_id, *extra]
            assert None not in ids, ids
            await conn.execute(_SLA_ROWS, ids)
            await conn.execute(
                "UPDATE work_items SET sla_policy_id = NULL, first_response_due_at = NULL,"
                " resolution_due_at = NULL, first_response_sla_state = NULL,"
                " resolution_sla_state = NULL, first_response_breached = false,"
                " resolution_breached = false WHERE id = ANY($1::uuid[])",
                ids,
            )
            await conn.execute(
                "UPDATE work_items SET first_responded_at = created_at + interval '5 minutes',"
                " resolved_at = created_at + interval '20 minutes' WHERE id = $1",
                quick_id,
            )
    finally:
        await conn.close()
    return open_id, quick_id


async def _clocks(url: str, ids: Sequence[uuid.UUID]) -> dict[tuple[uuid.UUID, str], str]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            rows = await conn.fetch(
                "SELECT record_id, kind, met_at, breached_at FROM sla_targets t"
                " WHERE record_id = ANY($1::uuid[])",
                list(ids),
            )
    finally:
        await conn.close()
    return {
        (r["record_id"], r["kind"]): "breached"
        if r["breached_at"] is not None
        else ("met" if r["met_at"] is not None else "running")
        for r in rows
    }


async def _audit(url: str, tenant: uuid.UUID) -> list[tuple[Any, ...]]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT id, action, object_id, occurred_at FROM audit_entries WHERE tenant_id = $1",
            tenant,
        )
    finally:
        await conn.close()
    return sorted(tuple(r) for r in rows)


def test_older_incidents_get_their_sla_from_creation_once(
    seeded: Seeded, seeded_copy: tuple[db_testing.ThrowawayDatabase, FakeKeycloak]
) -> None:
    database, keycloak = seeded_copy
    bystander = seeded.bystander
    # A person's own incident, the worst case: a seed subject and requester, made by the
    # technician (not the seed's admin), and with no SLA either. Step 6 never touches it.
    hand_made = asyncio.run(_hand_made(database))
    open_id, quick_id = asyncio.run(_as_before_slas(database.admin_url, extra=[hand_made]))
    hand_before = asyncio.run(_row_and_history(database.admin_url, hand_made))
    audit_before = asyncio.run(_audit(database.admin_url, seed.TENANT_ID))
    bystander_before = asyncio.run(_counts(database.migrator_url, bystander))

    again = asyncio.run(_run(database, keycloak))
    assert again.sla_from_creation == 2  # not the hand-made one
    assert asyncio.run(_row_and_history(database.admin_url, hand_made)) == hand_before
    clocks = asyncio.run(_clocks(database.migrator_url, [open_id, quick_id]))
    # From creation, never from now: open for days, its 4 hours ran out long ago.
    assert clocks[(open_id, "resolution")] == "breached"
    assert clocks[(quick_id, "first_response")] == "met"
    assert clocks[(quick_id, "resolution")] == "met"
    # New audit entries, one per incident; the old ones are exactly as they were.
    audit_after = asyncio.run(_audit(database.admin_url, seed.TENANT_ID))
    assert set(audit_before) <= set(audit_after)
    added = [e for e in audit_after if e not in set(audit_before)]
    applied = [e for e in added if e[1] == "incident.sla_applied_from_creation"]
    assert sorted(e[2] for e in applied) == sorted(str(i) for i in (open_id, quick_id))
    assert asyncio.run(_audit_chain(database.app_url)) == "passed"
    history = asyncio.run(_history_sources(database.migrator_url, open_id))
    assert "api" in history

    # A re-run changes nothing; another tenant is never touched, nor can be asked for.
    third = asyncio.run(_run(database, keycloak))
    assert third.sla_from_creation == 0
    assert asyncio.run(_clocks(database.migrator_url, [open_id, quick_id])) == clocks
    assert asyncio.run(_counts(database.migrator_url, bystander)) == bystander_before
    settings = make_settings(database_url=database.app_url)
    with pytest.raises(seed.SeedError):
        asyncio.run(seed.sla_from_creation(settings, bystander, uuid.uuid4(), [open_id]))


async def _history_sources(url: str, record_id: uuid.UUID) -> set[str]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            rows = await conn.fetch(
                "SELECT source FROM field_changes WHERE record_id = $1", record_id
            )
    finally:
        await conn.close()
    return {r["source"] for r in rows}


# --- step 7: fresh dates (Haider, 2026-11-10) ------------------------------------------------


async def _seed_open_latest(url: str) -> list[Any]:
    """The latest time of each open seed incident (made by the seed's admin)."""
    conn = await asyncpg.connect(url)
    try:
        # The migrator is held to RLS like the app (business tables force it): say the tenant.
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(seed.TENANT_ID))
        rows = await conn.fetch(
            "SELECT greatest(w.created_at, w.updated_at) AS latest FROM work_items w"
            " JOIN users u ON u.id = w.created_by"
            " WHERE w.tenant_id = $1 AND w.type = 'incident' AND u.email = $2"
            " AND w.status_category NOT IN ('resolved', 'closed', 'canceled')",
            seed.TENANT_ID,
            seed.ADMIN.email,
        )
    finally:
        await conn.close()
    return [r["latest"] for r in rows]


async def _target_states(url: str) -> dict[tuple[Any, str], str]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT record_id, kind, state FROM sla_targets WHERE tenant_id = $1", seed.TENANT_ID
        )
    finally:
        await conn.close()
    return {(r["record_id"], r["kind"]): r["state"] for r in rows}


async def _breach_all_running(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "UPDATE sla_targets SET state = 'breached', breached_at = due_at"
            " WHERE tenant_id = $1 AND state = 'running' AND due_at IS NOT NULL",
            seed.TENANT_ID,
        )
    finally:
        await conn.close()


async def _outbox(url: str) -> int:
    conn = await asyncpg.connect(url)
    try:
        return int(
            await conn.fetchval(
                f"SELECT count(*) FROM {OUTBOX_TABLE} WHERE tenant_id = $1",  # noqa: S608 - fixed name
                seed.TENANT_ID,
            )
        )
    finally:
        await conn.close()


def test_step7_brings_the_seeds_own_records_to_today_silently_and_once(
    seeded_copy: tuple[db_testing.ThrowawayDatabase, FakeKeycloak],
) -> None:
    database, _ = seeded_copy
    settings = make_settings(
        database_url=database.app_url, migration_database_url=database.migrator_url
    )
    hand_made = asyncio.run(_by_hand(database))  # a person's incident, edited: never moved
    hand_before = asyncio.run(_times_of(database.migrator_url, hand_made))
    # As on a stack whose waker ran on the old dates: every running target already breached.
    asyncio.run(_breach_all_running(database.admin_url))
    audit_before = asyncio.run(_audit(database.admin_url, seed.TENANT_ID))
    outbox_before = asyncio.run(_outbox(database.admin_url))
    states_before = asyncio.run(_target_states(database.admin_url))
    now = datetime.now(UTC)

    moved = asyncio.run(seed.freshen(settings, seed.TENANT_ID, now=now))
    assert moved > 0
    # Open seed incidents read as of today: their latest time within the last three days.
    latest = asyncio.run(_seed_open_latest(database.migrator_url))
    assert latest
    assert all(now - timedelta(hours=21) <= t <= now for t in latest)
    assert asyncio.run(_times_of(database.migrator_url, hand_made)) == hand_before
    # Clocks set right from now: a target breached on the old dates runs again when its due
    # moment is now ahead (lane C's case), silently: no event, no audit entry.
    states_after = asyncio.run(_target_states(database.admin_url))
    moves = Counter(
        (states_before[key], state) for key, state in states_after.items() if key in states_before
    )
    # Most run again from today; only a few with the shortest targets are still past due.
    assert moves[("breached", "running")] > moves[("breached", "breached")], moves
    assert asyncio.run(_outbox(database.admin_url)) == outbox_before
    assert asyncio.run(_audit(database.admin_url, seed.TENANT_ID)) == audit_before
    assert asyncio.run(_audit_chain(database.app_url)) == "passed"
    # Once: the same day again moves nothing; another tenant is refused. A clock left wrong
    # (as if an earlier rebase had failed after its move) is still set right by the re-run.
    asyncio.run(_breach_all_running(database.admin_url))
    assert asyncio.run(seed.freshen(settings, seed.TENANT_ID, now=now)) == 0
    healed = asyncio.run(_target_states(database.admin_url))
    assert Counter(healed.values()) == Counter(states_after.values())
    with pytest.raises(seed.SeedError, match="showcase tenant"):
        asyncio.run(seed.freshen(settings, uuid.uuid4(), now=now))


# --- E1 repair (Haider, 2026-11-10): requests fulfilled with nobody on them --------------------


async def _updates_of(url: str, record: uuid.UUID) -> list[Any]:
    """The changed fields of each `work_item.updated` event of the record in the outbox."""
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            f"SELECT envelope->'payload'->'changed_fields' AS fields FROM {OUTBOX_TABLE}"  # noqa: S608 - fixed name
            " WHERE event_type = 'work_items.work_item.updated'"
            " AND envelope->'payload'->>'work_item_id' = $1 ORDER BY id",
            str(record),
        )
    finally:
        await conn.close()
    return [json.loads(r["fields"]) for r in rows]


async def _orphan_one_fulfilled_request(url: str) -> uuid.UUID:
    """As SR-11 on the shared stack: a fulfilled request whose technician is empty."""
    conn = await asyncpg.connect(url)
    try:
        record: uuid.UUID = await conn.fetchval(
            "UPDATE work_items SET technician_id = NULL WHERE id = ("
            "  SELECT id FROM work_items WHERE tenant_id = $1 AND type = 'service_request'"
            "  AND status_category = 'resolved' ORDER BY display_number LIMIT 1"
            ") RETURNING id",
            seed.TENANT_ID,
        )
    finally:
        await conn.close()
    return record


def test_e1_repair_gives_a_fulfilled_request_its_fulfiller_once_and_audits_it(
    seeded_copy: tuple[db_testing.ThrowawayDatabase, FakeKeycloak],
) -> None:
    from tooling import repair_showcase_fulfillers as repair  # noqa: PLC0415 - the tool under test

    database, _ = seeded_copy
    settings = make_settings(
        database_url=database.app_url, migration_database_url=database.migrator_url
    )
    orphan = asyncio.run(_orphan_one_fulfilled_request(database.admin_url))
    assert orphan is not None
    audit_before = asyncio.run(_audit(database.admin_url, seed.TENANT_ID))
    planned = asyncio.run(repair.run(settings, write=False))
    assert [p.record_id for p in planned] == [orphan], [p.line() for p in planned]
    assert asyncio.run(_audit(database.admin_url, seed.TENANT_ID)) == audit_before  # dry run
    asyncio.run(repair.run(settings, write=True))

    async def after() -> tuple[Any, Any]:
        conn = await asyncpg.connect(database.admin_url)
        try:
            row = await conn.fetchrow(
                "SELECT w.technician_id, w.group_id,"
                " EXISTS (SELECT 1 FROM group_members m WHERE m.group_id = w.group_id"
                "         AND m.user_id = w.technician_id) AS in_group"
                " FROM work_items w WHERE w.id = $1",
                orphan,
            )
            history = await conn.fetchval(
                "SELECT count(*) FROM field_changes WHERE record_id = $1"
                " AND field = 'technician_id' AND new_value IS NOT NULL",
                orphan,
            )
        finally:
            await conn.close()
        return row, history

    row, history = asyncio.run(after())
    assert row["technician_id"] is not None
    assert row["group_id"] is None or row["in_group"]  # D-154a: someone of its own group
    assert history >= 1
    added = [
        e
        for e in asyncio.run(_audit(database.admin_url, seed.TENANT_ID))
        if e not in set(audit_before)
    ]
    # The repair's own entry; with WP-064 (#340) the save's lifecycle entry joins it.
    actions = [e[1] for e in added]
    assert actions.count("service_request.fulfiller_repaired") == 1, actions
    assert all(a.startswith("service_request.") for a in actions), actions
    # Its update event too, so open screens and search follow (rule 5b, lane B).
    events = asyncio.run(_updates_of(database.admin_url, orphan))
    assert events == [["technician_id"]]
    assert asyncio.run(_audit_chain(database.app_url)) == "passed"
    assert asyncio.run(repair.run(settings, write=False)) == []  # once
    assert repair.refuse("other", settings) is not None
