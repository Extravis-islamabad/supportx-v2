"""Lane B's showcase data: assets, so the asset screens show real records (visual matrix, QA).

Called from tooling/showcase_seed.py's `fill`, through the public API as the showcase admin
(P2), like tooling/showcase_lane_a.py. Products of the default product types; eight assets with
fixed `SX-` tags and filled properties (one named in Arabic, one in Urdu, for right-to-left
records); a laptop held by a person, a desktop held by a department with its monitor fitted to
it (a component), a laptop out on a loan, and a static group.

The seed rules (lanes A and C):

- **A stable key per thing.** Every create sends `seed_key("asset", ...)`, the seed's uuid5.
- **Idempotent.** What exists is found first (products by name, assets by their fixed tag, the
  group by name, the loan by its asset) and left alone; the count returned is what this run made.
- **Never someone else's work.** The holder, loanable mark and loan go only on an asset the seed
  made (its fixed tag) and only while it is exactly as the seed left it: the version the seed's
  last step left, with no holder. Any change by hand (a holder, a move, a disposal, an edit)
  raises the version, so the seed leaves it as it is. An asset in the trash is never made again;
  a product is made only for an asset made now, and the group only in the run that made its
  members, so one deleted by hand is not made again.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from tooling.showcase_lane_a import Api

BASE = "/api/v1/assets"
# An asset's version when created; each later save adds one (assets service `_saved`).
CREATED = 1


@dataclass(frozen=True)
class Product:
    """A product of a default product type (its api_name)."""

    name: str
    type_api_name: str
    manufacturer: str
    part_number: str
    price: str


PRODUCTS = (
    Product("Latitude 7440 laptop", "laptop", "Dell", "LAT-7440", "1450.00"),
    Product("OptiPlex 7010 desktop", "workstation", "Dell", "OPT-7010", "980.00"),
    Product("P2423D 24-inch monitor", "monitor", "Dell", "P2423D", "260.00"),
    Product("LaserJet Pro M404dn printer", "printer", "HP", "W1A53A", "420.00"),
    Product("Galaxy A55 phone", "phone", "Samsung", "SM-A556E", "450.00"),
)


@dataclass(frozen=True)
class Seeded:
    """One asset; `holder`: what the seed gives it once (see `_follow_up`)."""

    tag: str
    name: str
    product: str
    serial: str
    site: str
    location: str
    acquired_on: str
    warranty_expires_on: str
    price: str
    description: str
    holder: str | None = None  # "user", "department", "asset:<tag>" or "loan"


HQ, DUBAI = "Islamabad headquarters", "Dubai office"
ASSETS = (
    Seeded(
        "SX-LAP-001", "Finance laptop 01", "Latitude 7440 laptop", "5CG3471KQ2", HQ,
        "Floor 2, Finance", "2025-03-14", "2028-03-14", "1450.00",
        "Rabia's work laptop, with the finance applications.", holder="user",
    ),
    Seeded(
        "SX-DSK-001", "IT help desk workstation", "OptiPlex 7010 desktop", "7H2KX93", HQ,
        "Floor 1, IT service desk", "2024-11-02", "2027-11-02", "980.00",
        "The shared service desk workstation.", holder="department",
    ),
    Seeded(
        "SX-MON-001", "IT help desk monitor", "P2423D 24-inch monitor", "CN0D2T9K", HQ,
        "Floor 1, IT service desk", "2024-11-02", "2027-11-02", "260.00",
        "Fitted to the service desk workstation.", holder="asset:SX-DSK-001",
    ),
    Seeded(
        "SX-LAP-002", "Loaner laptop 02", "Latitude 7440 laptop", "5CG3471KR7", HQ,
        "IT store room", "2025-06-01", "2028-06-01", "1450.00",
        "For short loans to new starters and visitors.", holder="loan",
    ),
    Seeded(
        "SX-LAP-003", "حاسوب مكتب دبي", "Latitude 7440 laptop", "5CG3471KT1", DUBAI,
        "مكتب دبي، الطابق الأول", "2025-08-20", "2028-08-20", "1450.00",
        "حاسوب محمول لفريق مكتب دبي.",
    ),
    Seeded(
        "SX-PHN-001", "سروس ڈیسک کا فون", "Galaxy A55 phone", "R58W30ABCD", HQ,
        "پہلی منزل، سروس ڈیسک", "2025-09-10", "2027-09-10", "450.00",
        "سروس ڈیسک کا آن کال فون",
    ),
    Seeded(
        "SX-PRN-001", "Second floor printer", "LaserJet Pro M404dn printer", "PHB8K12345", HQ,
        "Floor 2, print corner", "2024-05-18", "2027-05-18", "420.00",
        "Shared by Finance and HR.",
    ),
    Seeded(
        "SX-MON-002", "Spare monitor", "P2423D 24-inch monitor", "CN0D2T9M", DUBAI,
        "Dubai office store", "2025-08-20", "2028-08-20", "260.00",
        "A spare for desks in the Dubai office.",
    ),
)  # fmt: skip
GROUP = "Service desk equipment"
GROUP_MEMBERS = ("SX-DSK-001", "SX-MON-001", "SX-LAP-002")
DEPARTMENT = "Information technology"
LOAN_DAYS = 7


@dataclass(frozen=True)
class Run:
    """One run: the API, the seed's keys, who the assets go to, and the assets by tag."""

    api: Api
    key: Callable[..., str]
    holder: str
    borrower: str
    departments: Mapping[str, str]
    rows: Mapping[str, dict[str, Any]]


async def _products(
    api: Api, seed_key: Callable[..., str], needed: set[str]
) -> tuple[dict[str, str], int]:
    """The products by name; one is made only when missing and an asset made now needs it."""
    have = {p["name"]: p["id"] for p in await api.all_pages(f"{BASE}/products")}
    if not needed - have.keys():
        return have, 0
    types = {t["api_name"]: t["id"] for t in await api.call("GET", f"{BASE}/product-types")}
    made = 0
    for product in PRODUCTS:
        if product.name in have or product.name not in needed or product.type_api_name not in types:
            continue
        row = await api.call(
            "POST",
            f"{BASE}/products",
            json={
                "product_type_id": types[product.type_api_name],
                "name": product.name,
                "manufacturer": product.manufacturer,
                "part_number": product.part_number,
                "price": product.price,
                "currency": "USD",
            },
            idempotency=seed_key("asset", "product", product.name),
        )
        have[product.name] = row["id"]
        made += 1
    return have, made


def _unheld(row: Mapping[str, Any]) -> bool:
    return not (row["owner_user_id"] or row["department_id"] or row["parent_asset_id"])


async def _follow_up(run: Run, spec: Seeded, row: dict[str, Any]) -> int:
    """The holder, or the loan, once: only while the asset is exactly as the seed left it."""
    if spec.holder is None or not _unheld(row):
        return 0
    if spec.holder == "loan":
        return await _lend(run, spec, row)
    if row["version"] != CREATED:
        return 0  # changed by hand since the seed made it
    if spec.holder == "user":
        holder = {"kind": "user", "id": run.holder}
    elif spec.holder == "department":
        if DEPARTMENT not in run.departments:
            return 0
        holder = {"kind": "department", "id": run.departments[DEPARTMENT]}
    else:
        parent = run.rows.get(spec.holder.removeprefix("asset:"))
        if parent is None:
            return 0
        holder = {"kind": "asset", "id": parent["id"]}
    held = await run.api.call(
        "PUT", f"{BASE}/{row['id']}/holder", json=holder, version=row["version"]
    )
    row.update(held)
    return 1


async def _lend(run: Run, spec: Seeded, row: dict[str, Any]) -> int:
    """Loanable (version CREATED -> CREATED + 1), then out on a loan, each step once."""
    api = run.api
    done = 0
    if row["version"] == CREATED and not row["loanable"]:
        await api.call(
            "POST", f"{BASE}/loanable", json={"asset_ids": [row["id"]], "loanable": True}
        )
        row.update(await api.call("GET", f"{BASE}/{row['id']}"))
        done += 1
    if row["version"] != CREATED + 1 or not row["loanable"]:
        return done  # not the seed's loanable mark alone: changed by hand
    on_loan = {a["id"] for loan in await api.call("GET", f"{BASE}/loans") for a in loan["assets"]}
    if row["id"] in on_loan:
        return done
    due = (datetime.now(UTC) + timedelta(days=LOAN_DAYS)).replace(microsecond=0)
    await api.call(
        "POST",
        f"{BASE}/loans",
        json={
            "borrower_id": run.borrower,
            "asset_ids": [row["id"]],
            "due_at": due.isoformat(),
            "comment": "Until their own laptop arrives.",
        },
        idempotency=run.key("asset", "loan", spec.tag),
    )
    return done + 1


async def _group(
    api: Api, rows: Mapping[str, dict[str, Any]], made_now: set[str], seed_key: Callable[..., str]
) -> int:
    """The static group and its members, once: in the run that made its members.

    So a group someone deleted or renamed is never made again, nor is a member they took out
    put back.
    """
    if not set(GROUP_MEMBERS) <= made_now:
        return 0
    if any(g["name"] == GROUP for g in await api.call("GET", f"{BASE}/groups")):
        return 0
    group = await api.call(
        "POST",
        f"{BASE}/groups",
        json={
            "name": GROUP,
            "kind": "static",
            "description": "What the IT service desk works with every day.",
        },
        idempotency=seed_key("asset", "group", GROUP),
    )
    answer = await api.call(
        "POST",
        f"{BASE}/groups/{group['id']}/members",
        json={"asset_ids": [rows[t]["id"] for t in GROUP_MEMBERS]},
    )
    return 1 + int(answer["added"])


async def ensure_assets(
    api: Api,
    seed_key: Callable[..., str],
    sites: Mapping[str, str],
    holder: uuid.UUID,
    borrower: uuid.UUID,
) -> int:
    """Products, assets, a holder, a component, a loan and a group. Returns things made now."""
    rows: dict[str, dict[str, Any]] = {
        r["tag"]: r for r in await api.all_pages(BASE) if r.get("tag")
    }
    trashed = {r["tag"] for r in await api.all_pages(f"{BASE}/trash") if r.get("tag")}
    missing = [s for s in ASSETS if s.tag not in rows and s.tag not in trashed]
    products, made = await _products(api, seed_key, {s.product for s in missing})
    departments = {
        d["name"]: d["id"] for d in await api.call("GET", "/api/v1/organization/departments")
    }
    made_now: set[str] = set()
    for spec in missing:
        if spec.product not in products:
            continue
        rows[spec.tag] = await api.call(
            "POST",
            BASE,
            json={
                "name": spec.name,
                "product_id": products[spec.product],
                "tag": spec.tag,
                "serial_number": spec.serial,
                "site_id": sites.get(spec.site),
                "location": spec.location,
                "acquired_on": spec.acquired_on,
                "warranty_expires_on": spec.warranty_expires_on,
                "purchase_price": spec.price,
                "currency": "USD",
                "description": spec.description,
            },
            idempotency=seed_key("asset", spec.tag),
        )
        made_now.add(spec.tag)
        made += 1
    # The holders after every asset exists (a monitor is fitted to its desktop).
    run = Run(api, seed_key, str(holder), str(borrower), departments, rows)
    for spec in ASSETS:
        if spec.tag in rows:
            made += await _follow_up(run, spec, rows[spec.tag])
    return made + await _group(api, rows, made_now, seed_key)
