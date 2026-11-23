"""The showcase CMDB (tooling/showcase_cmdb.py): stable keys, a re-run makes nothing, nobody
else's work is touched, and the impact from the core switch reaches real depth."""

import asyncio
import uuid
from collections import deque
from collections.abc import Mapping
from typing import Any

from app.modules.cmdb.domain.impact import IMPACT_FLOW, Flow
from tooling import showcase_cmdb as cmdb

SITES = {cmdb.HQ: str(uuid.uuid4()), cmdb.DUBAI: str(uuid.uuid4())}
GROUPS = {name: str(uuid.uuid4()) for name in (cmdb.NET, cmdb.APPS, cmdb.DESK)}
BUILT_IN = ("business_service", "application", "database", "hardware", "server", "workstation",
            "network_device", "printer")  # fmt: skip
CODES = ("depends_on", "runs_on", "connected_to", "part_of", "virtualised_by", "backed_up_by")


def _key(*parts: str) -> str:
    return str(uuid.uuid5(uuid.UUID("5ca5e5ee-d000-4000-8000-000000000000"), "/".join(parts)))


class FakeApi:
    """The CMDB endpoints the seed calls, with the server's rules that matter here."""

    def __init__(self) -> None:
        self.types = {name: str(uuid.uuid4()) for name in BUILT_IN}
        self.relationship_types = {code: str(uuid.uuid4()) for code in CODES}
        self.cis: dict[str, dict[str, Any]] = {}
        self.trash: list[dict[str, Any]] = []
        self.links: set[tuple[str, str, str]] = set()  # (from id, type id, to id)
        self.views: list[dict[str, Any]] = []
        self.subscribers: dict[str, list[dict[str, Any]]] = {}
        self.rules: list[dict[str, Any]] = []
        self.keys: list[str] = []
        self.writes: list[tuple[str, str]] = []
        self.asset = {"id": str(uuid.uuid4()), "tag": cmdb.FROM_ASSET_TAG}
        self.role = {"id": str(uuid.uuid4()), "key": cmdb.NARROWED_ROLE}

    def _ci(self, type_id: str, name: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
        row = {"id": str(uuid.uuid4()), "type_id": type_id, "name": name, "version": 1, **extra}
        self.cis[row["id"]] = row
        return row

    async def call(  # noqa: C901, PLR0911, PLR0912 - one branch per endpoint
        self,
        method: str,
        path: str,
        *,
        json: Any = None,  # noqa: ANN401 - request bodies
        params: Mapping[str, Any] | None = None,
        idempotency: str | None = None,
        version: int | None = None,
    ) -> Any:  # noqa: ANN401 - the endpoint's JSON
        if idempotency is not None:
            self.keys.append(idempotency)
        if method != "GET":
            self.writes.append((method, path))
        base = cmdb.BASE
        if (method, path) == ("GET", f"{base}/ci-types"):
            return {"items": [{"id": v, "api_name": k} for k, v in self.types.items()]}
        if (method, path) == ("POST", f"{base}/ci-types"):
            assert json["api_name"] not in self.types, "cmdb_ci_type_exists (409)"
            self.types[json["api_name"]] = str(uuid.uuid4())
            return {"id": self.types[json["api_name"]]}
        if (method, path) == ("POST", f"{base}/cis"):
            return self._ci(json["type_id"], json["name"], asset_id=None)
        if (method, path) == ("GET", f"{base}/relationship-types"):
            return {"items": [{"id": v, "code": k} for k, v in self.relationship_types.items()]}
        if method == "POST" and path.endswith("/relationships"):
            source = path.split("/")[-2]
            made = []
            for target in json["targets"]:
                link = (source, json["type_id"], target)
                assert link not in self.links, "cmdb_relationship_exists (409)"
                self.links.add(link)
                made.append({"id": str(uuid.uuid4())})
            return {"items": made}
        if (method, path) == ("POST", f"{base}/business-views"):
            self.views.append({"name": json["name"], "base": json["base_ci_id"]})
            return {}
        if method == "PUT" and path.endswith("/subscribers"):
            ci = self.cis[path.split("/")[-2]]
            assert version == ci["version"], "stale If-Match (409)"
            self.subscribers[ci["id"]] = json["subscribers"]
            ci["version"] += 1
            return {}
        if method == "GET" and path.startswith(f"{base}/cis/"):
            return self.cis[path.rsplit("/", maxsplit=1)[-1]]
        if (method, path) == ("POST", f"{base}/cis/from-assets"):
            if any(c.get("asset_id") == self.asset["id"] for c in self.cis.values()):
                return {"created": [], "skipped": [{"asset_id": self.asset["id"]}]}
            return {"created": [self._ci(json["type_id"], "Finance laptop 01",
                                         asset_id=self.asset["id"])]}  # fmt: skip
        if (method, path) == ("GET", "/api/v1/organization/departments"):
            return [
                {"id": str(uuid.uuid4()), "name": n} for n in ("Finance", "Information technology")
            ]
        if (method, path) == ("GET", "/api/v1/roles"):
            return [self.role, {"id": str(uuid.uuid4()), "key": "requester"}]
        if (method, path) == ("GET", cmdb.RULES):
            assert params is not None
            return [r for r in self.rules if r["role_id"] == params["role_id"]]
        if (method, path) == ("POST", cmdb.RULES):
            self.rules.append(dict(json))
            return {}
        msg = f"unexpected {method} {path}"
        raise AssertionError(msg)

    async def all_pages(self, path: str, params: Mapping[str, Any] | None = None) -> list[Any]:
        del params
        if path == f"{cmdb.BASE}/cis":
            return list(self.cis.values())
        if path == f"{cmdb.BASE}/cis/trash":
            return self.trash
        if path == f"{cmdb.BASE}/business-views":
            return self.views
        if path == "/api/v1/assets":
            return [self.asset]
        msg = f"unexpected page {path}"
        raise AssertionError(msg)

    def as_user(self, user: uuid.UUID) -> "FakeApi":
        del user
        return self


def _run(api: FakeApi) -> int:
    return asyncio.run(cmdb.ensure_cmdb(api, _key, SITES, GROUPS))


def test_the_first_run_makes_the_estate_and_a_second_makes_nothing() -> None:
    api = FakeApi()
    made = _run(api)
    assert len(api.cis) == len(cmdb.CIS) + 1  # and the one from the finance laptop
    assert 45 <= len(api.cis) <= 60
    assert len(api.links) == len(cmdb.LINKS) + 1
    assert [v["name"] for v in api.views] == [v.name for v in cmdb.VIEWS]
    assert len(api.subscribers) == len(cmdb.SUBSCRIBERS)
    assert api.rules == [
        {"role_id": api.role["id"], "resource": "ci", "criteria": {"criticality_max": "high"}}
    ]
    assert made > len(cmdb.CIS)
    writes = len(api.writes)
    assert _run(api) == 0
    assert len(api.writes) == writes, api.writes[writes:]


def test_every_create_has_a_stable_key() -> None:
    first, second = FakeApi(), FakeApi()
    _run(first)
    _run(second)
    assert first.keys == second.keys
    assert len(set(first.keys)) == len(first.keys)


def test_a_hand_made_ci_of_the_same_name_is_left_alone_and_never_linked() -> None:
    api = FakeApi()
    mine = api._ci(api.types["application"], "Payroll engine", asset_id=None)  # noqa: SLF001 - the fake's own helper
    _run(api)
    assert [c for c in api.cis.values() if c["name"] == "Payroll engine"] == [mine]
    assert mine["version"] == 1
    assert not any(mine["id"] in (f, t) for f, _, t in api.links)


def test_a_ci_in_the_trash_is_never_made_again() -> None:
    api = FakeApi()
    api.trash.append({"id": str(uuid.uuid4()), "type_id": api.types["database"],
                      "name": "Payroll database"})  # fmt: skip
    _run(api)
    assert all(c["name"] != "Payroll database" for c in api.cis.values())


def test_an_existing_ci_rule_on_the_role_is_left_as_it_is() -> None:
    api = FakeApi()
    theirs = {"role_id": api.role["id"], "resource": "ci", "criteria": {"site_ids": ["x"]}}
    api.rules.append(theirs)
    _run(api)
    assert api.rules == [theirs]


def test_the_links_cover_every_impact_type_and_the_core_switch_reaches_depth_five() -> None:
    assert {code for _, code, _ in cmdb.LINKS} == set(IMPACT_FLOW)
    names = {item.name for item in cmdb.CIS}
    assert all(s in names and t in names for s, _, t in cmdb.LINKS)
    # A failure travels by each type's flow (cmdb/domain/impact.py).
    reaches: dict[str, set[str]] = {}
    for source, code, target in cmdb.LINKS:
        flow = IMPACT_FLOW[code]
        if flow in (Flow.TO_FROM, Flow.BOTH):
            reaches.setdefault(target, set()).add(source)
        if flow in (Flow.FROM_TO, Flow.BOTH):
            reaches.setdefault(source, set()).add(target)
    depth = {"Core switch HQ": 0}
    queue = deque(["Core switch HQ"])
    while queue:
        here = queue.popleft()
        for there in reaches.get(here, ()):
            if there not in depth:
                depth[there] = depth[here] + 1
                queue.append(there)
    assert depth["Payroll"] >= 5
    assert {"Payroll", "Customer portal", "Finance and supply chain"} <= depth.keys()


def test_the_restricted_cis_are_the_critical_ones() -> None:
    critical = {item.name for item in cmdb.CIS if item.criticality == "critical"}
    assert critical == {"Payroll database", "ERP database"}
    assert cmdb.CEILING == "high"
