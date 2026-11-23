"""Lane B's showcase CMDB: CIs, relationships, business views and subscribers (WP-053).

Called from tooling/showcase_seed.py's `fill` after the assets, through the public API as the
showcase admin (P2), like tooling/showcase_assets.py. So the CMDB screens, the relationship map
and the impact tab show a real estate instead of nothing:

- **About 50 CIs** of the built-in types (business services, applications, databases, servers,
  network devices) and two tenant types under `server`, `virtual_host` and `virtual_machine`:
  two VM hosts and the VMs they carry. One service is named in Arabic and one application in
  Urdu, for right-to-left records. One CI is made from a showcase asset (the finance laptop)
  through `POST /cmdb/cis/from-assets`.
- **Relationships of all five impact-carrying built-in types** (depends_on, runs_on,
  virtualised_by, part_of, connected_to). A failure of the core switch reaches the VM hosts,
  their VMs, the applications and databases on them and the business services over them: depth
  five and more on the impact tab.
- **Two business views**: the payroll service (hierarchical) and the headquarters network
  (radial).
- **Subscribers** on two business services: departments, a site and a group the seed already
  makes (affected users on the impact tab).
- **Restricted CIs**: the showcase has no narrowed persona, so a fine-grained access rule
  (ADR-053) on the built-in `technician` role keeps CIs of `critical` criticality out of its
  reach (`criticality_max: high`). The payroll and ERP databases are critical, so the technician
  (Omar) and the lead (Nadia) see them as restricted placeholders on maps and impact paths. The
  admin (Sana) also holds `tenant_admin`, which is not narrowed, so she sees everything (ADR-053:
  the union across roles).
- TODO (lane A's WP-053 S5, `work_item_cis`): a CI linked to an incident, once incidents can name
  CIs. Not on main yet.

The seed rules (as showcase_assets):

- **A stable key per thing.** Every create sends `seed_key("cmdb", ...)`, the seed's uuid5.
- **Idempotent.** What exists is found first (types by api_name, CIs by type and name, in the
  list and in the trash, views by name, the rule by its role) and left alone; the count returned
  is what this run made.
- **Never someone else's work.** Relationships, views and subscribers are made only in the run
  that made the CIs they join (both ends made now, a view's base made now, a service made now):
  so a relationship, view or subscriber list someone removed or changed is never put back, and
  a CI someone made by hand with the same name is never linked to. The access rule is added only
  while the technician role has no CI rule at all.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from tooling.showcase_lane_a import Api

BASE = "/api/v1/cmdb"
RULES = "/api/v1/resource-access/rules"
NARROWED_ROLE = "technician"
CEILING = "high"  # the technician role sees CIs up to `high`; `critical` ones are restricted
FROM_ASSET_TAG = "SX-LAP-001"  # the finance laptop (showcase_assets)
FROM_ASSET_TYPE = "workstation"
FROM_ASSET_LINK = "Distribution switch floor 2"  # the laptop's switch port


@dataclass(frozen=True)
class OwnType:
    """A tenant CI type the seed makes, under a built-in one."""

    api_name: str
    parent: str
    names: Mapping[str, str]
    icon: str


OWN_TYPES = (
    OwnType(
        "virtual_host",
        "server",
        {"en": "Virtualisation host", "ar": "مضيف المحاكاة الافتراضية", "ur": "ورچوئلائزیشن ہوسٹ"},
        "server",
    ),
    OwnType(
        "virtual_machine",
        "server",
        {"en": "Virtual machine", "ar": "جهاز افتراضي", "ur": "ورچوئل مشین"},
        "server",
    ),
)


@dataclass(frozen=True)
class Item:
    """One CI: its type's api_name, name, site and the rest of what a CI shows."""

    type: str
    name: str
    site: str | None = None
    criticality: str | None = None
    business_impact: str | None = None
    group: str | None = None  # the managing group
    description: str | None = None


HQ, DUBAI = "Islamabad headquarters", "Dubai office"
NET, APPS, DESK = "Network and access", "Business applications", "Service desk"

CIS = (
    # Business services.
    Item("business_service", "Payroll", HQ, "high", "critical", APPS,
         "Monthly salaries and payslips for every employee."),
    Item("business_service", "Customer portal", None, "high", "high", APPS,
         "Where customers see their orders and raise requests."),
    Item("business_service", "Finance and supply chain", HQ, "high", "high", APPS,
         "The ERP: ledgers, purchasing and stock."),
    Item("business_service", "Email and collaboration", None, "medium", "high", DESK,
         "Mail, calendars and shared files for every office."),
    Item("business_service", "خدمات الموارد البشرية", DUBAI, "medium", "medium", APPS,
         "Leave, onboarding and employee records."),
    # Applications.
    Item("application", "Payroll engine", HQ, "high", None, APPS),
    Item("application", "Customer portal web", None, "high", None, APPS),
    Item("application", "Customer portal API", None, "high", None, APPS),
    Item("application", "ERP suite", HQ, "high", None, APPS),
    Item("application", "ERP finance module", HQ, "high", None, APPS),
    Item("application", "ERP supply chain module", HQ, "medium", None, APPS),
    Item("application", "Mail service", None, "medium", None, DESK),
    Item("application", "Identity provider", HQ, "high", None, NET),
    Item("application", "ملازمین کا پورٹل", DUBAI, "medium", None, APPS,
         "The employee self-service portal."),
    Item("application", "Reporting suite", HQ, "low", None, APPS),
    # Databases (the payroll and ERP ones are critical: restricted for the technician role).
    Item("database", "Payroll database", HQ, "critical", None, APPS),
    Item("database", "ERP database", HQ, "critical", None, APPS),
    Item("database", "Customer portal database", None, "high", None, APPS),
    Item("database", "HR database", DUBAI, "medium", None, APPS),
    Item("database", "Reporting warehouse", HQ, "low", None, APPS),
    Item("database", "Directory database", HQ, "high", None, NET),
    # Virtualisation hosts and their VMs.
    Item("virtual_host", "VM host HQ-01", HQ, "high", None, NET),
    Item("virtual_host", "VM host HQ-02", HQ, "high", None, NET),
    Item("virtual_machine", "vm-payroll-app", HQ, "high", None, APPS),
    Item("virtual_machine", "vm-payroll-db", HQ, "high", None, APPS),
    Item("virtual_machine", "vm-portal-web-01", HQ, "high", None, APPS),
    Item("virtual_machine", "vm-portal-web-02", HQ, "high", None, APPS),
    Item("virtual_machine", "vm-portal-api", HQ, "high", None, APPS),
    Item("virtual_machine", "vm-portal-db", HQ, "high", None, APPS),
    Item("virtual_machine", "vm-erp-app", HQ, "high", None, APPS),
    Item("virtual_machine", "vm-erp-db", HQ, "high", None, APPS),
    Item("virtual_machine", "vm-mail", HQ, "medium", None, DESK),
    Item("virtual_machine", "vm-idp", HQ, "high", None, NET),
    Item("virtual_machine", "vm-hr", HQ, "medium", None, APPS),
    Item("virtual_machine", "vm-reporting", HQ, "low", None, APPS),
    # Physical servers.
    Item("server", "Storage array SAN-01", HQ, "high", None, NET),
    Item("server", "Backup server", HQ, "medium", None, NET),
    Item("server", "Dubai file server", DUBAI, "medium", None, DESK),
    Item("server", "Dubai domain controller", DUBAI, "high", None, NET),
    # Network devices.
    Item("network_device", "Core switch HQ", HQ, "high", None, NET),
    Item("network_device", "Distribution switch floor 1", HQ, "medium", None, NET),
    Item("network_device", "Distribution switch floor 2", HQ, "medium", None, NET),
    Item("network_device", "Firewall HQ", HQ, "high", None, NET),
    Item("network_device", "Internet router HQ", HQ, "high", None, NET),
    Item("network_device", "Load balancer", HQ, "high", None, NET),
    Item("network_device", "VPN gateway", HQ, "medium", None, NET),
    Item("network_device", "Dubai router", DUBAI, "medium", None, NET),
    Item("network_device", "Dubai switch", DUBAI, "medium", None, NET),
)  # fmt: skip

# (from, relationship type, to): "from <forward name> to". Impact flows by each type's direction
# (cmdb/domain/impact.py): depends_on, runs_on and virtualised_by carry a failure of `to` to
# `from`; part_of a failure of the part to the whole; connected_to both ways.
LINKS: tuple[tuple[str, str, str], ...] = (
    # Services on their applications.
    ("Payroll", "depends_on", "Payroll engine"),
    ("Payroll", "depends_on", "Identity provider"),
    ("Customer portal", "depends_on", "Customer portal web"),
    ("Customer portal", "depends_on", "Customer portal API"),
    ("Finance and supply chain", "depends_on", "ERP suite"),
    ("Email and collaboration", "depends_on", "Mail service"),
    ("Email and collaboration", "depends_on", "Identity provider"),
    ("خدمات الموارد البشرية", "depends_on", "ملازمین کا پورٹل"),
    ("خدمات الموارد البشرية", "depends_on", "Payroll engine"),
    # Applications on databases and on each other.
    ("Payroll engine", "depends_on", "Payroll database"),
    ("Customer portal web", "depends_on", "Customer portal API"),
    ("Customer portal API", "depends_on", "Customer portal database"),
    ("ERP finance module", "depends_on", "ERP database"),
    ("ERP supply chain module", "depends_on", "ERP database"),
    ("ملازمین کا پورٹل", "depends_on", "HR database"),
    ("Reporting suite", "depends_on", "Reporting warehouse"),
    ("Identity provider", "depends_on", "Directory database"),
    ("Reporting suite", "depends_on", "ERP database"),
    # Modules are part of the suite.
    ("ERP finance module", "part_of", "ERP suite"),
    ("ERP supply chain module", "part_of", "ERP suite"),
    ("Reporting suite", "part_of", "ERP suite"),
    # Applications and databases on their VMs.
    ("Payroll engine", "runs_on", "vm-payroll-app"),
    ("Payroll database", "runs_on", "vm-payroll-db"),
    ("Customer portal web", "runs_on", "vm-portal-web-01"),
    ("Customer portal web", "runs_on", "vm-portal-web-02"),
    ("Customer portal API", "runs_on", "vm-portal-api"),
    ("Customer portal database", "runs_on", "vm-portal-db"),
    ("ERP suite", "runs_on", "vm-erp-app"),
    ("ERP database", "runs_on", "vm-erp-db"),
    ("Mail service", "runs_on", "vm-mail"),
    ("Identity provider", "runs_on", "vm-idp"),
    ("Directory database", "runs_on", "vm-idp"),
    ("ملازمین کا پورٹل", "runs_on", "vm-hr"),
    ("HR database", "runs_on", "vm-hr"),
    ("Reporting warehouse", "runs_on", "vm-reporting"),
    # VMs on their hosts.
    ("vm-payroll-app", "virtualised_by", "VM host HQ-01"),
    ("vm-payroll-db", "virtualised_by", "VM host HQ-01"),
    ("vm-portal-web-01", "virtualised_by", "VM host HQ-01"),
    ("vm-portal-api", "virtualised_by", "VM host HQ-01"),
    ("vm-mail", "virtualised_by", "VM host HQ-01"),
    ("vm-idp", "virtualised_by", "VM host HQ-01"),
    ("vm-portal-web-02", "virtualised_by", "VM host HQ-02"),
    ("vm-portal-db", "virtualised_by", "VM host HQ-02"),
    ("vm-erp-app", "virtualised_by", "VM host HQ-02"),
    ("vm-erp-db", "virtualised_by", "VM host HQ-02"),
    ("vm-hr", "virtualised_by", "VM host HQ-02"),
    ("vm-reporting", "virtualised_by", "VM host HQ-02"),
    # Hosts on their storage, backups and the network.
    ("VM host HQ-01", "depends_on", "Storage array SAN-01"),
    ("VM host HQ-02", "depends_on", "Storage array SAN-01"),
    ("Storage array SAN-01", "connected_to", "Backup server"),
    ("VM host HQ-01", "connected_to", "Distribution switch floor 1"),
    ("VM host HQ-02", "connected_to", "Distribution switch floor 1"),
    ("Storage array SAN-01", "connected_to", "Distribution switch floor 1"),
    ("Distribution switch floor 1", "connected_to", "Core switch HQ"),
    ("Distribution switch floor 2", "connected_to", "Core switch HQ"),
    ("Load balancer", "connected_to", "Core switch HQ"),
    ("vm-portal-web-01", "connected_to", "Load balancer"),
    ("vm-portal-web-02", "connected_to", "Load balancer"),
    ("Core switch HQ", "connected_to", "Firewall HQ"),
    ("Firewall HQ", "connected_to", "Internet router HQ"),
    ("VPN gateway", "connected_to", "Firewall HQ"),
    # The Dubai office, through its own router and the VPN.
    ("Dubai router", "connected_to", "VPN gateway"),
    ("Dubai switch", "connected_to", "Dubai router"),
    ("Dubai file server", "connected_to", "Dubai switch"),
    ("Dubai domain controller", "connected_to", "Dubai switch"),
    ("Dubai domain controller", "depends_on", "Directory database"),
)


@dataclass(frozen=True)
class View:
    """A saved map of one base CI."""

    name: str
    base: str
    layout: str
    depth: int
    description: str


VIEWS = (
    View("Payroll service map", "Payroll", "hierarchical", 3,
         "Everything payroll runs on, down to the VMs."),
    View("Headquarters network", "Core switch HQ", "radial", 3,
         "The core switch and what hangs off it."),
)  # fmt: skip

# Business services and who they serve: (kind, name).
SUBSCRIBERS: Mapping[str, tuple[tuple[str, str], ...]] = {
    "Payroll": (("department", "Finance"), ("department", "Information technology")),
    "Email and collaboration": (("site", HQ), ("site", DUBAI), ("group", DESK)),
}


@dataclass
class Run:
    """One run: the API, the seed's keys, and what it found or made."""

    api: Api
    key: Callable[..., str]
    types: dict[str, str]  # api_name -> type ID
    rows: dict[str, dict[str, Any]]  # CI name -> the CI (found or made)
    made_now: set[str]  # CI names made in this run


def _names_by_type(
    found: Iterable[Mapping[str, Any]], types: Mapping[str, str]
) -> set[tuple[str, str]]:
    by_id = {v: k for k, v in types.items()}
    return {(by_id.get(str(r["type_id"]), ""), r["name"]) for r in found}


async def _types(api: Api, seed_key: Callable[..., str]) -> tuple[dict[str, str], int]:
    """Every CI type by api_name; the seed's own two are made when missing."""
    found = (await api.call("GET", f"{BASE}/ci-types"))["items"]
    types = {t["api_name"]: str(t["id"]) for t in found}
    made = 0
    for own in OWN_TYPES:
        if own.api_name in types or own.parent not in types:
            continue
        row = await api.call(
            "POST",
            f"{BASE}/ci-types",
            json={
                "api_name": own.api_name,
                "names": dict(own.names),
                "parent_id": types[own.parent],
                "icon": own.icon,
            },
            idempotency=seed_key("cmdb", "type", own.api_name),
        )
        types[own.api_name] = str(row["id"])
        made += 1
    return types, made


async def _cis(run: Run, sites: Mapping[str, str], groups: Mapping[str, str]) -> int:
    """The CIs: each made once, unless one of that type and name exists (or is in the trash)."""
    live = await run.api.all_pages(f"{BASE}/cis")
    trashed = _names_by_type(await run.api.all_pages(f"{BASE}/cis/trash"), run.types)
    by_id = {v: k for k, v in run.types.items()}
    for row in live:
        run.rows.setdefault(row["name"], row)
    present = {(by_id.get(str(r["type_id"]), ""), r["name"]) for r in live}
    made = 0
    for item in CIS:
        if item.type not in run.types or (item.type, item.name) in present | trashed:
            continue
        body: dict[str, Any] = {
            "type_id": run.types[item.type],
            "name": item.name,
            "site_id": sites.get(item.site) if item.site else None,
            "managed_by_group_id": groups.get(item.group) if item.group else None,
            "criticality": item.criticality,
            "business_impact": item.business_impact,
        }
        if item.description:
            body["description"] = item.description
        run.rows[item.name] = await run.api.call(
            "POST",
            f"{BASE}/cis",
            json=body,
            idempotency=run.key("cmdb", "ci", item.type, item.name),
        )
        run.made_now.add(item.name)
        made += 1
    return made


async def _links(run: Run, links: Iterable[tuple[str, str, str]] = LINKS) -> int:
    """Each relationship, only when both its CIs were made in this run."""
    relationship_types = {
        t["code"]: str(t["id"])
        for t in (await run.api.call("GET", f"{BASE}/relationship-types"))["items"]
    }
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for source, code, target in links:
        if {source, target} <= run.made_now and code in relationship_types:
            grouped[(source, code)].append(target)
    made = 0
    for (source, code), targets in grouped.items():
        answer = await run.api.call(
            "POST",
            f"{BASE}/cis/{run.rows[source]['id']}/relationships",
            json={
                "type_id": relationship_types[code],
                "direction": "forward",
                "targets": [str(run.rows[t]["id"]) for t in targets],
            },
            idempotency=run.key("cmdb", "links", source, code),
        )
        made += len(answer["items"])
    return made


async def _views(run: Run, views: Iterable[View] = VIEWS) -> int:
    """Each business view, only in the run that made its base CI."""
    have = {v["name"] for v in await run.api.all_pages(f"{BASE}/business-views")}
    made = 0
    for view in views:
        if view.name in have or view.base not in run.made_now:
            continue
        await run.api.call(
            "POST",
            f"{BASE}/business-views",
            json={
                "base_ci_id": str(run.rows[view.base]["id"]),
                "name": view.name,
                "description": view.description,
                "layout": view.layout,
                "filters": {"depth": view.depth},
            },
            idempotency=run.key("cmdb", "view", view.name),
        )
        made += 1
    return made


async def _subscribers(run: Run, units: Mapping[str, Mapping[str, str]]) -> int:
    """Each service's subscribers, only in the run that made the service (a replace, If-Match)."""
    made = 0
    for service, wanted in SUBSCRIBERS.items():
        if service not in run.made_now:
            continue
        refs = [
            {"kind": kind, "ref_id": units[kind][name]}
            for kind, name in wanted
            if name in units.get(kind, {})
        ]
        if not refs:
            continue
        current = await run.api.call("GET", f"{BASE}/cis/{run.rows[service]['id']}")
        await run.api.call(
            "PUT",
            f"{BASE}/cis/{run.rows[service]['id']}/subscribers",
            json={"subscribers": refs},
            version=current["version"],
        )
        made += len(refs)
    return made


async def _from_asset(run: Run) -> int:
    """One CI from the finance laptop, linked to its switch: once, while the asset has no CI."""
    if FROM_ASSET_TYPE not in run.types:
        return 0
    found = [a for a in await run.api.all_pages("/api/v1/assets") if a.get("tag") == FROM_ASSET_TAG]
    if not found or any(str(r.get("asset_id")) == str(found[0]["id"]) for r in run.rows.values()):
        return 0  # no such asset, or it has its CI already (a replayed create counts nothing)
    answer = await run.api.call(
        "POST",
        f"{BASE}/cis/from-assets",
        json={"asset_ids": [found[0]["id"]], "type_id": run.types[FROM_ASSET_TYPE]},
        idempotency=run.key("cmdb", "from-asset", FROM_ASSET_TAG),
    )
    created = answer["created"]
    if not created:
        return 0  # the asset already has its CI (this run or an earlier one, or someone's)
    ci = created[0]
    made = 1
    if FROM_ASSET_LINK in run.made_now:
        run.rows[ci["name"]] = ci
        run.made_now.add(ci["name"])
        made += await _links(run, ((ci["name"], "connected_to", FROM_ASSET_LINK),))
    return made


async def _restricted(api: Api, seed_key: Callable[..., str]) -> int:
    """The technician role sees CIs up to `high`: once, while that role has no CI rule."""
    role = next(
        (r for r in await api.call("GET", "/api/v1/roles") if r["key"] == NARROWED_ROLE), None
    )
    if role is None:
        return 0
    rules = await api.call("GET", RULES, params={"role_id": role["id"], "resource": "ci"})
    if rules:
        return 0
    await api.call(
        "POST",
        RULES,
        json={"role_id": role["id"], "resource": "ci", "criteria": {"criticality_max": CEILING}},
        idempotency=seed_key("cmdb", "rule", NARROWED_ROLE),
    )
    return 1


async def ensure_cmdb(
    api: Api,
    seed_key: Callable[..., str],
    sites: Mapping[str, str],
    groups: Mapping[str, str],
) -> int:
    """Types, CIs, links, views, subscribers, a CI from an asset, a rule: things made now."""
    types, made = await _types(api, seed_key)
    run = Run(api, seed_key, types, {}, set())
    made += await _cis(run, sites, groups)
    made += await _links(run)
    made += await _views(run)
    departments = {
        d["name"]: str(d["id"]) for d in await api.call("GET", "/api/v1/organization/departments")
    }
    units = {"department": departments, "site": dict(sites), "group": dict(groups)}
    made += await _subscribers(run, units)
    made += await _from_asset(run)
    return made + await _restricted(api, seed_key)
