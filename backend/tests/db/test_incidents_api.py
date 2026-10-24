"""Incidents over HTTP on the work item engine (WP-020). Test names cite parity file 01 criteria.

Real PostgreSQL and Valkey; the session is faked by headers like the access tests. Each test
builds its own tenants in the session's throwaway database, so nothing here touches dev data.

Who is who in org A (`Org`), two sites S1 / S2 and two support groups GA / GB:
    admin       tenant admin (everything, all scopes)
    lead        custom role "Lead": every incidents.* permission at `all`
    tech_a      built-in technician (group + own, D-052); member of GA and of site S1
    tech_b      built-in technician; member of GB and of site S2
    tech_c      built-in technician; member of GA and GB and of site S1 (take must ask)
    requester   built-in requester, member of S1
    requester2  built-in requester, member of S2
"""

import asyncio
import json
import statistics
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import Database
from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules.work_items.domain.types import WorkItemTypeCode
from app.modules.work_items.service.realtime import LISTS, ROUTES
from app.shared.events import EventEnvelope
from conftest import assign_system_role, create_tenant, make_settings
from tests.db.test_access_api import fake_session
from tests.db.test_rate_limit import valkey_url
from tests.db.test_users_api import seed_users
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]

BASE = "/incidents"
CONSOLE = {"X-SupportX-Client": "console"}


@dataclass
class Org:
    """One tenant with the cast described in the module docstring."""

    tenant: uuid.UUID
    admin: uuid.UUID
    lead: uuid.UUID
    tech_a: uuid.UUID
    tech_b: uuid.UUID
    tech_c: uuid.UUID
    requester: uuid.UUID
    requester2: uuid.UUID
    s1: uuid.UUID = field(default_factory=uuid.uuid4)
    s2: uuid.UUID = field(default_factory=uuid.uuid4)
    ga: uuid.UUID = field(default_factory=uuid.uuid4)
    gb: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class World:
    client: AsyncClient
    db: ThrowawayDatabase
    app: FastAPI
    a: Org
    b: Org

    async def call(
        self,
        method: str,
        path: str,
        org: Org,
        user: uuid.UUID,
        **kw: Any,  # noqa: ANN401 - httpx request options
    ) -> httpx.Response:
        headers = {"X-Test-Tenant": str(org.tenant), "X-Test-User": str(user)}
        headers.update(kw.pop("headers", {}))
        return await self.client.request(method, f"/api/v1{path}", headers=headers, **kw)

    async def create(self, org: Org, user: uuid.UUID, **values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
        body = {"subject": "Mail is down", "requester_id": str(org.requester), **values}
        response = await self.call("POST", BASE, org, user, json=body, headers=CONSOLE)
        assert response.status_code == 201, response.text
        return dict(response.json())

    async def get(self, org: Org, user: uuid.UUID, item: dict[str, Any]) -> httpx.Response:
        return await self.call("GET", f"{BASE}/{item['id']}", org, user)

    async def fresh(self, org: Org, item: dict[str, Any]) -> dict[str, Any]:
        response = await self.get(org, org.admin, item)
        assert response.status_code == 200, response.text
        return dict(response.json())

    async def act(
        self,
        org: Org,
        user: uuid.UUID,
        item: dict[str, Any],
        action: str,
        reason_code: str | None = None,
        reason_text: str | None = None,
    ) -> httpx.Response:
        body: dict[str, Any] = {}
        if reason_code is not None:
            body["reason_code"] = reason_code
        if reason_text is not None:
            body["reason_text"] = reason_text
        return await self.call(
            "POST",
            f"{BASE}/{item['id']}/actions/{action}",
            org,
            user,
            headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
            json=body or None,
        )

    async def assign(
        self,
        org: Org,
        user: uuid.UUID,
        item: dict[str, Any],
        *,
        group: uuid.UUID | None = None,
        technician: uuid.UUID | None = None,
        **extra: Any,  # noqa: ANN401 - JSON
    ) -> httpx.Response:
        body = {
            "group_id": str(group) if group else None,
            "technician_id": str(technician) if technician else None,
            **extra,
        }
        return await self.call(
            "POST",
            f"{BASE}/{item['id']}/assign",
            org,
            user,
            headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
            json=body,
        )

    async def patch(
        self,
        org: Org,
        user: uuid.UUID,
        item: dict[str, Any],
        **values: Any,  # noqa: ANN401 - JSON
    ) -> httpx.Response:
        return await self.call(
            "PATCH",
            f"{BASE}/{item['id']}",
            org,
            user,
            headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
            json=values,
        )

    async def history(
        self, org: Org, item: dict[str, Any], query: str = ""
    ) -> list[dict[str, Any]]:
        response = await self.call("GET", f"{BASE}/{item['id']}/history{query}", org, org.admin)
        assert response.status_code == 200, response.text
        return list(response.json()["items"])

    async def sql(self, statement: str, *args: Any) -> list[asyncpg.Record]:  # noqa: ANN401 - asyncpg args
        conn = await asyncpg.connect(self.db.admin_url)
        try:
            return list(await conn.fetch(statement, *args))
        finally:
            await conn.close()


async def role(world: World, org: Org, name: str, grants: list[tuple[str, str]]) -> uuid.UUID:
    created = await world.call(
        "POST",
        "/roles",
        org,
        org.admin,
        json={"name": name, "permissions": [{"permission": p, "scope": s} for p, s in grants]},
    )
    assert created.status_code == 201, created.text
    return uuid.UUID(created.json()["id"])


async def unit(world: World, org: Org, kind: str, name: str, members: list[uuid.UUID]) -> uuid.UUID:
    created = await world.call("POST", f"/organization/{kind}", org, org.admin, json={"name": name})
    assert created.status_code == 201, created.text
    unit_id = uuid.UUID(created.json()["id"])
    for member in members:
        added = await world.call(
            "PUT", f"/organization/{kind}/{unit_id}/members/{member}", org, org.admin
        )
        assert added.status_code in {200, 204}, added.text
    return unit_id


INCIDENT_ACTIONS = (
    "view",
    "create",
    "edit",
    "assign",
    "assign_outside_group",
    "take",
    "change_priority",
    "resolve",
    "close",
    "reopen",
    "cancel",
    "delete",
)


async def make_org(world: World, name: str) -> Org:
    tenant = await create_tenant(world.db.migrator_url, name)
    users = await seed_users(
        world.db,
        tenant,
        [
            {"user_type": "technician", "display_name": f"{name} Admin"},
            {"user_type": "technician", "display_name": f"{name} Lead"},
            {"user_type": "technician", "display_name": f"{name} Tech A"},
            {"user_type": "technician", "display_name": f"{name} Tech B"},
            {"user_type": "technician", "display_name": f"{name} Tech C"},
            {"user_type": "requester", "display_name": f"{name} Requester"},
            {"user_type": "requester", "display_name": f"{name} Requester 2"},
        ],
    )
    admin, lead, tech_a, tech_b, tech_c, requester, requester2 = users
    await assign_system_role(world.db.admin_url, tenant, admin, "tenant_admin")
    for tech in (lead, tech_a, tech_b, tech_c):
        await assign_system_role(world.db.admin_url, tenant, tech, "technician")
    for person in (requester, requester2):
        await assign_system_role(world.db.admin_url, tenant, person, "requester")
    org = Org(tenant, admin, lead, tech_a, tech_b, tech_c, requester, requester2)
    lead_role = await role(
        world, org, "Lead", [(f"incidents.{action}", "all") for action in INCIDENT_ACTIONS]
    )
    assigned = await world.call("PUT", f"/users/{lead}/roles/{lead_role}", org, admin)
    assert assigned.status_code == 204, assigned.text
    org.s1 = await unit(world, org, "sites", f"{name} S1", [tech_a, tech_c, requester])
    org.s2 = await unit(world, org, "sites", f"{name} S2", [tech_b, requester2])
    org.ga = await unit(world, org, "groups", f"{name} GA", [tech_a, tech_c])
    org.gb = await unit(world, org, "groups", f"{name} GB", [tech_b, tech_c])
    return org


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    app: FastAPI = create_app(
        make_settings(
            database_url=migrated_db.app_url,
            valkey_url=url,
            centrifugo_token_secret="incidents-test-secret-" + "x" * 16,
        )
    )
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            w = World(client, migrated_db, app, a=None, b=None)  # type: ignore[arg-type]  # set below
            w.a = await make_org(w, "Alpha")
            w.b = await make_org(w, "Beta")
            yield w
            cache = app.state.policy.cache
            prefix = app.state.settings.valkey_key_prefix
            keys = [k async for k in cache.client.scan_iter(match=f"{prefix}*")]
            if keys:
                await cache.client.delete(*keys)


def problem(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


def field_codes(response: httpx.Response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    return {e["field"].removeprefix("body."): e["code"] for e in response.json()["errors"]}


def states(item: dict[str, Any], kind: str = "actions") -> dict[str, str | None]:
    """action -> None when allowed, else the reason code."""
    return {a["action"]: None if a["allowed"] else a["reason"] for a in item[kind]}


async def ids(world: World, org: Org, user: uuid.UUID, query: str = "") -> set[str]:
    response = await world.call("GET", f"{BASE}{query}", org, user)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


# --- create, IDs, priority ------------------------------------------------------------------------


async def test_req_inc_001_ac1_create_with_subject_and_requester_only(world: World) -> None:
    a = world.a
    response = await world.call(
        "POST",
        BASE,
        a,
        a.tech_a,
        json={"subject": "  Printer   jammed ", "requester_id": str(a.requester)},
        headers=CONSOLE,
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert response.headers["Location"] == f"/api/v1{BASE}/{item['id']}"
    assert response.headers["ETag"] == '"1"'
    assert item["subject"] == "Printer jammed"
    assert (item["status"], item["status_category"], item["type"]) == ("new", "open", "incident")
    assert item["site_id"] == str(a.s1)  # the requester's only site (REQ-INC-016 AC1)
    assert item["channel"] == "phone"  # console default (REQ-INC-005 AC2)
    assert item["people"][str(a.requester)]["display_name"] == "Alpha Requester"
    assert "@" in item["people"][str(a.requester)]["email"]
    missing = await world.call("POST", BASE, a, a.tech_a, json={"subject": " "}, headers=CONSOLE)
    assert missing.status_code == 422


async def test_req_wi_002_ids_per_type_and_tenant(world: World) -> None:
    a, b = world.a, world.b
    first = await world.create(a, a.admin)
    assert first["display_id"] == "INC-1"  # AC1
    assert (await world.create(b, b.admin))["display_id"] == "INC-1"  # AC2: per tenant
    # AC2: concurrent creates never collide.
    results = await asyncio.gather(*(world.create(a, a.admin, subject=f"c{i}") for i in range(12)))
    numbers = sorted(int(r["display_id"].split("-")[1]) for r in results)
    assert numbers == list(range(2, 14))


async def test_req_wi_002_ac3_ids_never_reused_after_delete(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    deleted = await world.call(
        "DELETE", f"{BASE}/{item['id']}", a, a.admin, headers={"If-Match": '"1"'}
    )
    assert deleted.status_code == 204
    again = await world.create(a, a.admin)
    assert again["display_id"] != item["display_id"]


async def test_req_wi_002_ac4_prefix_change_keeps_old_ids(world: World) -> None:
    a = world.a
    old = await world.create(a, a.admin)
    settings = await world.call("GET", f"{BASE}/settings", a, a.admin)
    assert settings.json()["prefix"] == "INC"
    changed = await world.call(
        "PATCH",
        f"{BASE}/settings",
        a,
        a.admin,
        headers={"If-Match": f'"{settings.json()["version"]}"'},
        json={"prefix": "TCK"},
    )
    assert changed.status_code == 200, changed.text
    new = await world.create(a, a.admin)
    assert new["display_id"] == "TCK-2"  # numbering continues (counter keyed by type)
    for value in (old["display_id"], old["display_id"].lower(), "1", "TCK-1"):
        found = await world.call("GET", f"{BASE}/lookup/{value}", a, a.admin)
        assert found.status_code == 200, value
        assert found.json()["id"] == old["id"]
    # AC5 / technicians may not change settings.
    refused = await world.call(
        "PATCH", f"{BASE}/settings", a, a.tech_a, headers={"If-Match": '"2"'}, json={"prefix": "X"}
    )
    assert refused.status_code == 403


async def test_req_wi_008_ac1_same_idempotency_key_one_incident(world: World) -> None:
    a = world.a
    key = {"Idempotency-Key": str(uuid.uuid4()), **CONSOLE}
    body = {"subject": "Once", "requester_id": str(a.requester)}
    first = await world.call("POST", BASE, a, a.admin, json=body, headers=key)
    again = await world.call("POST", BASE, a, a.admin, json=body, headers=key)
    assert (first.status_code, again.status_code) == (201, 201)
    assert first.json()["id"] == again.json()["id"]
    rows = await world.sql(
        "SELECT count(*) AS n FROM work_items WHERE tenant_id = $1 AND subject = 'Once'", a.tenant
    )
    assert rows[0]["n"] == 1


async def test_req_inc_009_priority_from_the_matrix(world: World) -> None:
    a = world.a
    settings = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    assert len(settings["matrix"]) == 16  # AC1: full in a new tenant
    p1 = await world.create(a, a.admin, impact="organisation", urgency="critical")
    assert (p1["priority"], p1["priority_source"]) == ("p1", "matrix")  # AC2
    item = await world.create(a, a.admin, impact="one_person", urgency="low")
    assert item["priority"] == "p4"
    changed = await world.patch(a, a.tech_a, item, urgency="critical", impact="department_or_site")
    assert changed.status_code == 200, changed.text
    assert (changed.json()["priority"], changed.json()["priority_source"]) == ("p1", "matrix")
    # AC3: the recompute is recorded as the matrix's doing, apart from the user's own change.
    entries = await world.history(a, item)
    automatic = [e for e in entries if e["automation"] == {"kind": "matrix"}]
    assert any(
        c["field"] == "priority" and c["new"] == "p1" for e in automatic for c in e["changes"]
    )
    people = await world.history(a, item, "?actors=people")
    assert all(e["automation"] is None for e in people)
    assert any(c["field"] == "urgency" for e in people for c in e["changes"])


async def test_req_inc_010_priority_override_needs_permission_and_reason(world: World) -> None:
    a = world.a
    tech_only = await role(
        world, a, "Viewer-editor", [("incidents.view", "all"), ("incidents.edit", "all")]
    )
    outsider_tech = uuid.uuid4()
    await seed_users(world.db, a.tenant, [{"id": outsider_tech, "user_type": "technician"}])
    assert (
        await world.call("PUT", f"/users/{outsider_tech}/roles/{tech_only}", a, a.admin)
    ).status_code == 204
    item = await world.create(a, a.admin, impact="team", urgency="low")
    # AC1: no permission → refused and the operation says why.
    view = (await world.get(a, outsider_tech, item)).json()
    assert states(view, "operations")["change_priority"] == "no_permission"
    refused = await world.patch(a, outsider_tech, item, priority="p1", priority_reason="VIP")
    assert refused.status_code == 403
    # AC2: a reason is required.
    assert field_codes(await world.patch(a, a.tech_a, item, priority="p1")) == {
        "priority_reason": "required"
    }
    set_ = await world.patch(a, a.tech_a, item, priority="p1", priority_reason="CEO affected")
    assert set_.status_code == 200, set_.text
    assert (set_.json()["priority"], set_.json()["priority_source"]) == ("p1", "manual")
    # AC3: manual stays manual on impact changes, until cleared back to the matrix.
    kept = await world.patch(a, a.tech_a, set_.json(), impact="organisation")
    assert (kept.json()["priority"], kept.json()["priority_source"]) == ("p1", "manual")
    cleared = await world.patch(a, a.tech_a, kept.json(), priority=None)
    assert (cleared.json()["priority"], cleared.json()["priority_source"]) == ("p3", "matrix")
    entries = await world.history(a, item)
    assert any(e["reason"] == "CEO affected" for e in entries)


async def test_req_inc_011_default_priority_and_no_sla_marker(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    assert (item["priority"], item["priority_source"]) == ("p3", "default")  # AC1
    assert item["sla_policy_id"] is None  # AC2: shown as "no SLA applies"
    assert item["id"] in await ids(world, a, a.admin, "?view=without_sla")  # AC3
    resolved = await world.act(a, a.admin, item, "resolve")
    assert item["id"] not in await ids(world, a, a.admin, "?view=without_sla")
    assert resolved.status_code == 200


# --- D-052 visibility (technician default scope: group) -------------------------------------------


async def test_d052_technician_sees_groups_assigned_and_site_queue_and_404_outside(
    world: World,
) -> None:
    a = world.a
    in_my_group = await world.create(a, a.admin, group_id=str(a.ga), requester_id=str(a.requester2))
    assigned_to_me = await world.create(
        a, a.admin, group_id=str(a.gb), technician_id=str(a.tech_a), requester_id=str(a.requester2)
    )
    my_site_queue = await world.create(a, a.admin)  # requester at S1, no group, no technician
    other_site_queue = await world.create(a, a.admin, requester_id=str(a.requester2))  # S2
    other_group = await world.create(a, a.admin, group_id=str(a.gb), requester_id=str(a.requester2))
    other_tenant = await world.create(world.b, world.b.admin)

    seen = await ids(world, a, a.tech_a, "?view=all")
    assert {in_my_group["id"], assigned_to_me["id"], my_site_queue["id"]} <= seen  # rule 1, 2, 3
    assert not {other_site_queue["id"], other_group["id"]} & seen
    for visible in (in_my_group, assigned_to_me, my_site_queue):
        assert (await world.get(a, a.tech_a, visible)).status_code == 200
    for hidden in (other_site_queue, other_group):
        assert problem(await world.get(a, a.tech_a, hidden)) == (404, "work_item_not_found")
        edit = await world.patch(a, a.tech_a, hidden, subject="x")
        assert problem(edit) == (404, "work_item_not_found")
    assert problem(await world.call("GET", f"{BASE}/{other_tenant['id']}", a, a.admin)) == (
        404,
        "work_item_not_found",
    )
    # The site queue is only the *unassigned* part: once GB has it, tech_a loses sight.
    moved = await world.assign(a, a.admin, my_site_queue, group=a.gb)
    assert moved.status_code == 200, moved.text
    assert problem(await world.get(a, a.tech_a, my_site_queue)) == (404, "work_item_not_found")
    # An admin may widen a technician to `all` (custom role): then everything is visible.
    wide = await role(world, a, "Wide", [("incidents.view", "all")])
    assert (
        await world.call("PUT", f"/users/{a.tech_b}/roles/{wide}", a, a.admin)
    ).status_code == 204
    assert {other_site_queue["id"], my_site_queue["id"]} <= await ids(
        world, a, a.tech_b, "?view=all"
    )


async def test_d053_handing_out_of_reach_needs_confirmation_and_is_recorded(world: World) -> None:
    a = world.a
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    warned = await world.assign(a, a.tech_a, item, group=a.gb, reason_code="wrong_group")
    assert problem(warned) == (409, "would_lose_access")
    assert warned.json()["params"]["display_id"] == item["display_id"]
    still = (await world.get(a, a.tech_a, item)).json()
    assert still["group_id"] == str(a.ga)  # nothing changed
    handed = await world.assign(
        a, a.tech_a, still, group=a.gb, reason_code="wrong_group", confirm_lose_access=True
    )
    assert handed.status_code == 200, handed.text
    assert handed.json()["visible"] is False
    assert problem(await world.get(a, a.tech_a, item)) == (404, "work_item_not_found")
    entries = await world.history(a, item)
    flags = [c for e in entries for c in e["changes"] if c["field"] == "handed_over_out_of_reach"]
    assert flags == [{"field": "handed_over_out_of_reach", "old": None, "new": True}]
    # Logging a call for a requester of another site: the same warning at create time.
    other_site = await world.call(
        "POST",
        BASE,
        a,
        a.tech_a,
        json={"subject": "S2 call", "requester_id": str(a.requester2)},
        headers=CONSOLE,
    )
    assert problem(other_site) == (409, "would_lose_access")


# --- statuses and transitions ---------------------------------------------------------------------


async def test_req_inc_046_ac1_api_refuses_disallowed_transition(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    assert problem(await world.act(a, a.admin, item, "close")) == (409, "invalid_transition")
    assert problem(await world.act(a, a.admin, item, "assign")) == (409, "invalid_transition")
    bogus = await world.act(a, a.admin, item, "teleport")
    assert bogus.status_code == 422
    # Status is not a field: PATCH refuses it.
    assert (await world.patch(a, a.admin, item, status="closed")).status_code == 422
    view = await world.fresh(a, item)
    assert states(view)["close"] == "not_from_status"
    assert [x["action"] for x in view["actions"]] == [
        "start_work",
        "wait_requester",
        "wait_third_party",
        "resume",
        "resolve",
        "close",
        "reopen",
        "cancel",
        "undo_cancel",
    ]


async def test_req_inc_047_reasons_on_status_changes(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga))
    assert item["status"] == "assigned"
    assert field_codes(await world.act(a, a.tech_a, item, "wait_requester")) == {
        "reason_code": "required"
    }
    other = await world.act(a, a.tech_a, item, "wait_requester", "other")
    assert field_codes(other) == {"reason_text": "required"}
    waiting = await world.act(
        a, a.tech_a, item, "wait_requester", "more_information", "Need the error text"
    )
    assert waiting.status_code == 200, waiting.text
    body = waiting.json()
    assert (body["status"], body["status_category"]) == ("awaiting_requester", "paused")
    assert (body["status_reason_code"], body["status_reason_text"]) == (
        "more_information",
        "Need the error text",
    )
    entry = (await world.history(a, item))[0]
    assert entry["kind"] == "status"
    assert entry["reason"] == "Need the error text"
    assert {"field": "status_reason_code", "old": None, "new": "more_information"} in entry[
        "changes"
    ]
    resumed = await world.act(a, a.tech_a, body, "resume")
    assert resumed.json()["status_reason_code"] is None
    assert resumed.json()["paused_seconds"] >= 0
    assert resumed.json()["paused_since"] is None


async def test_req_inc_050_assignment_moves_the_status(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    assigned = await world.assign(a, a.admin, item, group=a.ga, technician=a.tech_a)
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "assigned"  # AC1
    entries = await world.history(a, item)
    auto = entries[0]
    assert auto["kind"] == "status"
    assert auto["automation"]["kind"] == "auto_move"
    unassigned = await world.assign(a, a.admin, assigned.json(), group=a.ga)
    assert unassigned.json()["status"] == "new"
    # AC4: in progress stays in progress.
    started = await world.act(
        a,
        a.admin,
        (await world.assign(a, a.admin, unassigned.json(), group=a.ga, technician=a.tech_a)).json(),
        "start_work",
    )
    moved = await world.assign(a, a.admin, started.json(), group=a.ga, technician=a.tech_c)
    assert moved.json()["status"] == "in_progress"
    # AC3: with the setting off, assignment leaves the status alone.
    settings = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    off = await world.call(
        "PATCH",
        f"{BASE}/settings",
        a,
        a.admin,
        headers={"If-Match": f'"{settings["version"]}"'},
        json={"auto_status_on_assign": False},
    )
    assert off.status_code == 200, off.text
    other = await world.create(a, a.admin)
    kept = await world.assign(a, a.admin, other, group=a.ga, technician=a.tech_a)
    assert kept.json()["status"] == "new"


async def test_req_inc_053_assignees_and_group_rules(world: World) -> None:
    a = world.a
    listed = await world.call("GET", f"{BASE}/assignees?group_id={a.ga}", a, a.tech_a)
    assert listed.status_code == 200, listed.text
    people = {row["id"] for row in listed.json()}
    assert people == {str(a.tech_a), str(a.tech_c)}  # AC1: only GA members
    await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    loads = {row["id"]: row["open_count"] for row in listed.json()}
    relisted = await world.call("GET", f"{BASE}/assignees?group_id={a.ga}", a, a.tech_a)
    assert {row["id"]: row["open_count"] for row in relisted.json()}[str(a.tech_a)] == loads[
        str(a.tech_a)
    ] + 1  # AC2
    item = await world.create(a, a.tech_a, group_id=str(a.ga))
    outside = await world.assign(a, a.tech_a, item, group=a.ga, technician=a.tech_b)
    assert field_codes(outside) == {"technician_id": "technician_not_in_group"}  # AC3
    lead = await world.assign(a, a.lead, item, group=a.ga, technician=a.tech_b)
    assert lead.status_code == 200, lead.text  # the lead holds assign_outside_group
    requester_as_tech = await world.assign(
        a, a.lead, lead.json(), group=a.ga, technician=a.requester
    )
    assert field_codes(requester_as_tech) == {"technician_id": "technician_not_allowed"}
    entries = await world.history(a, item)
    assert any(c["field"] == "technician_id" for e in entries for c in e["changes"])  # AC4


async def test_req_inc_054_take_sets_the_group_and_conflicts_name_the_winner(world: World) -> None:
    a = world.a
    queue = await world.create(a, a.admin)
    taken = await world.call(
        "POST", f"{BASE}/{queue['id']}/take", a, a.tech_a, headers={"If-Match": '"1"'}
    )
    assert taken.status_code == 200, taken.text
    body = taken.json()
    assert (body["technician_id"], body["group_id"], body["status"]) == (
        str(a.tech_a),
        str(a.ga),
        "assigned",
    )  # AC1: tech_a's only group
    # AC2: tech_c is in two groups and must choose.
    second = await world.create(a, a.admin)
    ask = await world.call(
        "POST", f"{BASE}/{second['id']}/take", a, a.tech_c, headers={"If-Match": '"1"'}
    )
    assert field_codes(ask) == {"group_id": "group_required"}
    chose = await world.call(
        "POST",
        f"{BASE}/{second['id']}/take",
        a,
        a.tech_c,
        headers={"If-Match": '"1"'},
        json={"group_id": str(a.gb)},
    )
    assert chose.status_code == 200, chose.text
    assert chose.json()["group_id"] == str(a.gb)
    # AC3: a stale take after someone else took it names them.
    race = await world.create(a, a.admin)
    first = await world.call(
        "POST", f"{BASE}/{race['id']}/take", a, a.tech_a, headers={"If-Match": '"1"'}
    )
    assert first.status_code == 200
    late = await world.call(
        "POST",
        f"{BASE}/{race['id']}/take",
        a,
        a.tech_c,
        headers={"If-Match": '"1"'},
        json={"group_id": str(a.ga)},
    )
    assert problem(late) == (409, "version_conflict")
    assert late.json()["params"]["changed_by"] == "Alpha Tech A"
    current = (await world.get(a, a.tech_c, race)).json()
    assert states(current, "operations")["take"] == "assigned_to_other"
    again = await world.call(
        "POST",
        f"{BASE}/{race['id']}/take",
        a,
        a.tech_c,
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert problem(again) == (409, "already_taken")
    assert again.json()["params"]["taken_by"] == "Alpha Tech A"


async def test_req_inc_055_moving_groups_needs_a_reason_and_counts(world: World) -> None:
    a = world.a
    item = await world.create(a, a.lead, group_id=str(a.ga))
    assert field_codes(await world.assign(a, a.lead, item, group=a.gb)) == {
        "reason_code": "required"
    }
    moved = await world.assign(
        a, a.lead, item, group=a.gb, reason_code="needs_expertise", reason_text="Needs networking"
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["reassignment_count"] == 1
    entry = (await world.history(a, item))[0]
    assert entry["reason"] == "Needs networking"
    assert {"field": "assignment_reason", "old": None, "new": "needs_expertise"} in entry["changes"]


async def test_req_inc_097_and_100_reopen_and_cancel_keep_the_past(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga))
    resolved = (await world.act(a, a.tech_a, item, "resolve")).json()
    closed = (await world.act(a, a.tech_a, resolved, "close")).json()
    assert closed["closed_at"]
    assert closed["resolved_at"]
    # INC-097 AC1: reopen needs a reason.
    assert field_codes(await world.act(a, a.tech_a, closed, "reopen")) == {
        "reason_code": "required"
    }
    reopened = await world.act(a, a.tech_a, closed, "reopen", "came_back")
    assert reopened.status_code == 200, reopened.text
    body = reopened.json()
    assert (body["status"], body["reopen_count"], body["closed_at"]) == ("in_progress", 1, None)
    # AC2: the earlier times stay in history.
    entry = (await world.history(a, item))[0]
    stamps = {c["field"]: c for c in entry["changes"]}
    assert stamps["closed_at"]["old"] is not None
    assert stamps["closed_at"]["new"] is None
    assert stamps["resolved_at"]["old"] is not None
    assert stamps["reopen_count"] == {"field": "reopen_count", "old": 0, "new": 1}
    # AC3: reopen count is a filter.
    assert item["id"] in await ids(world, a, a.admin, "?reopen_count=1")
    # INC-100: cancel needs a reason, makes it read-only, undo returns to the previous status.
    assert field_codes(await world.act(a, a.tech_a, body, "cancel")) == {"reason_code": "required"}
    canceled = (await world.act(a, a.tech_a, body, "cancel", "duplicate")).json()
    assert canceled["status"] == "canceled"
    assert problem(await world.patch(a, a.tech_a, canceled, subject="x")) == (409, "record_closed")
    assert states(canceled, "operations")["edit"] == "record_closed"
    undone = await world.act(a, a.tech_a, canceled, "undo_cancel")
    assert undone.json()["status"] == "in_progress"


# --- concurrency, history, trash ------------------------------------------------------------------


async def test_req_wi_007_ac1_stale_version_409_names_user_and_fields(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    missing = await world.call("PATCH", f"{BASE}/{item['id']}", a, a.admin, json={"subject": "x"})
    assert problem(missing) == (428, "precondition_required")
    first = await world.patch(a, a.tech_a, item, subject="Mail down for everyone", urgency="high")
    assert first.status_code == 200
    stale = await world.patch(a, a.admin, item, subject="mine")
    assert problem(stale) == (409, "version_conflict")
    params = stale.json()["params"]
    assert params["changed_by"] == "Alpha Tech A"
    assert {"subject", "urgency"} <= set(params["changed_fields"].split(","))
    same = await world.patch(a, a.admin, first.json(), subject="Mail down for everyone")
    assert same.json()["version"] == first.json()["version"]  # no-op: no new version


async def test_req_wi_003_history_records_who_when_old_new_source(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, urgency="low")
    await world.patch(a, a.tech_a, item, subject="New subject")
    entries = await world.history(a, item)
    edit = entries[0]
    assert (edit["actor_id"], edit["actor_name"], edit["source"]) == (
        str(a.tech_a),
        "Alpha Tech A",
        "ui",
    )
    assert {"field": "subject", "old": "Mail is down", "new": "New subject"} in edit["changes"]
    assert entries[-1]["kind"] == "created"
    # AC2: true order inside one second (microsecond time + change id).
    times = [e["occurred_at"] for e in entries]
    assert times == sorted(times, reverse=True)
    # AC5: history has no write route.
    for method in ("POST", "PATCH", "DELETE", "PUT"):
        response = await world.call(method, f"{BASE}/{item['id']}/history", a, a.admin)
        assert response.status_code == 405, method
    page = await world.call("GET", f"{BASE}/{item['id']}/history?limit=1", a, a.admin)
    cursor = page.json()["next_cursor"]
    rest = await world.call(
        "GET", f"{BASE}/{item['id']}/history?limit=5&cursor={cursor}", a, a.admin
    )
    assert len(page.json()["items"]) + len(rest.json()["items"]) == len(entries)


async def test_req_wi_020_trash_and_restore(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin)
    refused = await world.call(
        "DELETE", f"{BASE}/{item['id']}", a, a.tech_a, headers={"If-Match": '"1"'}
    )
    assert refused.status_code == 403  # AC4: technicians cannot delete
    assert (await world.call("GET", f"{BASE}/trash", a, a.tech_a)).status_code == 403
    deleted = await world.call(
        "DELETE", f"{BASE}/{item['id']}", a, a.admin, headers={"If-Match": '"1"'}
    )
    assert deleted.status_code == 204
    assert item["id"] not in await ids(world, a, a.admin, "?view=all")  # AC1
    trash = await world.call("GET", f"{BASE}/trash", a, a.admin)
    assert item["id"] in {r["id"] for r in trash.json()["items"]}
    restored = await world.call(
        "POST", f"{BASE}/{item['id']}/restore", a, a.admin, headers={"If-Match": '"2"'}
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["display_id"] == item["display_id"]  # AC2
    kinds = [e["kind"] for e in await world.history(a, item)]
    assert kinds[:2] == ["restored", "deleted"]


# --- lists and views ------------------------------------------------------------------------------


async def test_req_inc_105_builtin_views_and_counts(world: World) -> None:
    a = world.a
    mine = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    queue = await world.create(a, a.admin)
    waiting = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    await world.act(a, a.tech_a, waiting, "wait_requester", "confirmation")
    resolved = await world.create(a, a.admin, group_id=str(a.ga))
    await world.act(a, a.admin, resolved, "resolve")
    expectations = {
        "open": {mine["id"], queue["id"], waiting["id"]},
        "my_open": {mine["id"], waiting["id"]},
        "unassigned": {queue["id"]},
        "my_groups_open": {mine["id"], waiting["id"]},
        "waiting": {waiting["id"]},
        "resolved": {resolved["id"]},
    }
    for view, expected in expectations.items():
        assert await ids(world, a, a.tech_a, f"?view={view}") == expected, view
    counts = {
        c["view"]: c["count"]
        for c in (await world.call("GET", f"{BASE}/views", a, a.tech_a)).json()
    }
    assert counts["my_open"] == 2
    assert list(counts)[:3] == ["open", "my_open", "unassigned"]  # fixed order
    assert (await world.call("GET", f"{BASE}?view=nope", a, a.admin)).status_code == 422


async def test_req_inc_104_ac2_and_110_sort_and_stable_paging(world: World) -> None:
    a = world.a
    made = [await world.create(a, a.admin, subject=f"Item {i:02d}") for i in range(7)]
    first = await world.call("GET", f"{BASE}?sort=subject&limit=3&include_total=true", a, a.admin)
    page = first.json()
    assert [r["subject"] for r in page["items"]] == ["Item 00", "Item 01", "Item 02"]
    assert page["estimated_total"] == 7
    await world.create(a, a.admin, subject="Item 00 new")  # arrives between pages
    second = await world.call(
        "GET", f"{BASE}?sort=subject&limit=3&cursor={page['next_cursor']}", a, a.admin
    )
    seen = [r["subject"] for r in page["items"]] + [r["subject"] for r in second.json()["items"]]
    assert len(seen) == len(set(seen))  # no row twice
    assert len(made) == 7


async def test_req_inc_001_filters_tags_and_fields(world: World) -> None:
    a = world.a
    tagged = await world.create(a, a.admin, tags=["vpn", "VPN", "wifi"], impact="team")
    assert tagged["tags"] == ["vpn", "wifi"]
    assert tagged["id"] in await ids(world, a, a.admin, "?tag=vpn")
    assert tagged["id"] in await ids(world, a, a.admin, "?impact=team&priority=p4")
    dsl = {"field": "subject", "op": "contains", "value": "Mail"}
    found = await ids(world, a, a.admin, "?" + str(httpx.QueryParams({"filter": json.dumps(dsl)})))
    assert tagged["id"] in found


async def test_req_inc_006_categories_and_references(world: World) -> None:
    a = world.a
    tree = (await world.call("GET", f"{BASE}/categories", a, a.tech_a)).json()
    codes = {n["code"] for n in tree}
    assert {"hardware", "printer", "network", "vpn"} <= codes
    printer = next(n for n in tree if n["code"] == "printer")
    item = await world.create(a, a.admin, category_id=printer["id"])
    assert item["category_id"] == printer["id"]
    bogus = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "category_id": str(uuid.uuid4())},
    )
    assert field_codes(bogus) == {"category_id": "category_not_found"}
    # An admin adds a node with its own labels and disables one; old records keep theirs.
    added = await world.call(
        "POST",
        f"{BASE}/categories",
        a,
        a.admin,
        json={"parent_id": printer["id"], "labels": {"en": "Toner", "ar": "حبر"}},
    )
    assert added.status_code == 201, added.text
    assert added.json()["level"] == 3
    too_deep = await world.call(
        "POST",
        f"{BASE}/categories",
        a,
        a.admin,
        json={"parent_id": added.json()["id"], "labels": {"en": "Deeper"}},
    )
    assert field_codes(too_deep) == {"parent_id": "too_deep"}
    disabled = await world.call(
        "PATCH",
        f"{BASE}/categories/{printer['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{printer["version"]}"'},
        json={"disabled": True},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["disabled"] is True
    refused = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "category_id": printer["id"]},
    )
    assert field_codes(refused) == {"category_id": "category_disabled"}
    assert (await world.fresh(a, item))["category_id"] == printer["id"]
    technician_add = await world.call(
        "POST", f"{BASE}/categories", a, a.tech_a, json={"labels": {"en": "Mine"}}
    )
    assert technician_add.status_code == 403


async def test_req_inc_005_ac3_reserved_channel_refused(world: World) -> None:
    a = world.a
    response = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "channel": "email"},
    )
    assert field_codes(response) == {"channel": "channel_reserved"}
    walk_up = await world.create(a, a.admin, channel="walk_up")
    assert walk_up["channel"] == "walk_up"
    api = await world.call(
        "POST", BASE, a, a.admin, json={"subject": "x", "requester_id": str(a.requester)}
    )
    assert api.json()["channel"] == "api"  # no console header: the API channel


async def test_req_inc_064_description_is_sanitised(world: World) -> None:
    a = world.a
    item = await world.create(
        a,
        a.admin,
        description=(
            '<p onclick="x()">Hello <script>alert(1)</script><a href="javascript:x">l</a></p>'
        ),
    )
    assert item["description"] == "<p>Hello l</p>"  # the refused link keeps its text (QA C4)
    blank = await world.create(a, a.admin, description="<p></p>")
    assert blank["description"] is None


# --- licence --------------------------------------------------------------------------------------


async def test_req_wi_017_ac1_licence_gates_incidents(world: World) -> None:
    no_plan = await create_tenant(world.db.migrator_url, "No plan", edition=None)
    (admin,) = await seed_users(world.db, no_plan, [{"user_type": "technician"}])
    await assign_system_role(world.db.admin_url, no_plan, admin, "tenant_admin")
    org = Org(no_plan, admin, admin, admin, admin, admin, admin, admin)
    for method, path in (("GET", BASE), ("GET", f"{BASE}/settings"), ("POST", BASE)):
        response = await world.call(method, path, org, admin, json={"subject": "x"})
        assert problem(response) == (403, "entitlement_required"), path


# --- realtime -------------------------------------------------------------------------------------


async def envelopes(world: World, item_id: str) -> list[EventEnvelope]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE aggregate_id = $1 ORDER BY id", item_id
    )
    return [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]


async def test_req_wi_005_ac2_group_move_publishes_old_and_new_audience(
    world: World, app_db: Database
) -> None:
    a = world.a
    item = await world.create(a, a.admin)  # unassigned at S1
    moved = await world.assign(a, a.admin, item, group=a.ga)
    regrouped = await world.assign(a, a.admin, moved.json(), group=a.gb, reason_code="wrong_group")
    assert regrouped.status_code == 200, regrouped.text
    found = await envelopes(world, item["id"])
    assert [e.event_type for e in found] == [
        "work_items.work_item.created",
        "work_items.work_item.assigned",
        "work_items.work_item.assigned",
    ]
    assert "Mail" not in json.dumps([e.payload for e in found])  # IDs and codes only

    async def route(envelope: EventEnvelope) -> set[str]:
        channels: set[str] = set()
        async with app_db.tenant_session(TenantContext(a.tenant)) as session:
            for spec in ROUTES:
                if envelope.event_type in spec.event_types:
                    effects = await spec.route(envelope, session)
                    channels |= {p.channel.name for p in effects.publications}
        return channels

    t = a.tenant
    first_move = await route(found[1])
    # Left the S1 unassigned queue, joined GA.
    assert {
        f"t:{t}:queue:incidents.unassigned.{a.s1}",
        f"t:{t}:queue:incidents.group.{a.ga}",
    } <= first_move
    assert f"t:{t}:wi:{item['id']}" in first_move
    second_move = await route(found[2])
    assert {
        f"t:{t}:queue:incidents.group.{a.ga}",
        f"t:{t}:queue:incidents.group.{a.gb}",
    } <= second_move


async def test_req_wi_005_ac5_channels_follow_d040_scopes(world: World, app_db: Database) -> None:
    a = world.a
    policy = world.app.state.policy
    async with app_db.tenant_session(TenantContext(a.tenant)) as session:
        tech = await policy.subject(a.tenant, a.tech_a, session)
        requester = await policy.subject(a.tenant, a.requester, session)
    live = LISTS[WorkItemTypeCode.INCIDENT]
    names = {c.name for c in live.channels_for(tech, a.tenant)}
    t = a.tenant
    assert names == {
        f"t:{t}:queue:incidents.group.{a.ga}",
        f"t:{t}:queue:incidents.unassigned.{a.s1}",
        f"t:{t}:user:{a.tech_a}",
    }
    assert live.channels_for(requester, a.tenant) == []  # no incident access yet (portal: WP-028)


# --- performance ----------------------------------------------------------------------------------

ROWS = 100_000
RUNS = 30
SEED = """
INSERT INTO work_items (id, tenant_id, type, display_id, display_number, subject, requester_id,
                        channel, site_id, group_id, technician_id, priority, priority_source,
                        status, status_category, created_by, updated_by, created_at, updated_at)
SELECT gen_random_uuid(), $1, 'incident', 'INC-' || (n + 1000), n + 1000,
       'Incident ' || lpad(n::text, 6, '0'), $2, 'phone',
       CASE WHEN n % 4 = 0 THEN $3::uuid ELSE NULL END,
       CASE WHEN n % 3 = 0 THEN $4::uuid WHEN n % 3 = 1 THEN $5::uuid ELSE NULL END,
       CASE WHEN n % 5 = 0 THEN $6::uuid ELSE NULL END,
       (ARRAY['p1', 'p2', 'p3', 'p4'])[1 + n % 4], 'matrix',
       (ARRAY['new', 'in_progress', 'resolved', 'closed'])[1 + (n / 7) % 4],
       (ARRAY['open', 'open', 'resolved', 'closed'])[1 + (n / 7) % 4],
       $2, $2, now() - (n || ' seconds')::interval, now() - (n || ' seconds')::interval
FROM generate_series(1, $7) AS n
"""


async def test_incidents_list_p95_on_100k_rows(world: World) -> None:
    """List p95 < 300 ms on 100,000 incidents (architecture §1.3 targets 10M in V1, k6)."""
    org = await make_org(world, "Perf")
    first = await world.create(org, org.admin)  # seeds the tenant's configuration
    assert first["display_id"] == "INC-1"
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute(
            SEED, org.tenant, org.requester, org.s1, org.ga, org.gb, org.tech_a, ROWS
        )
        await conn.execute("ANALYZE work_items")
    finally:
        await conn.close()
    queries = {
        "admin_open_by_updated": (org.admin, "?view=open&limit=50"),
        "admin_p1_open": (org.admin, "?view=open&priority=p1&limit=50"),
        "admin_sorted_by_subject": (org.admin, "?sort=subject&limit=50"),
        "admin_subject_contains": (
            org.admin,
            "?"
            + str(
                httpx.QueryParams(
                    {
                        "filter": json.dumps(
                            {"field": "subject", "op": "contains", "value": "004242"}
                        )
                    }
                )
            ),
        ),
        "tech_group_scope_open": (org.tech_a, "?view=open&limit=50"),
        "tech_my_open": (org.tech_a, "?view=my_open&limit=50"),
    }
    report: dict[str, dict[str, float]] = {}
    for name, (user, suffix) in queries.items():
        timings = []
        response = None
        for _ in range(RUNS):
            started = time.perf_counter()
            response = await world.call("GET", f"{BASE}{suffix}", org, user)
            timings.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200, response.text
        assert response is not None
        timings.sort()
        p95 = timings[int(len(timings) * 0.95) - 1]
        report[name] = {
            "p50_ms": round(statistics.median(timings), 1),
            "p95_ms": round(p95, 1),
            "max_ms": round(timings[-1], 1),
            "items": len(response.json()["items"]),
        }
        print(f"\n[perf] incidents_100k {name}: rows={ROWS}, {report[name]}")  # noqa: T201
    assert all(r["items"] > 0 for r in report.values()), report
    assert all(r["p95_ms"] < 300 for r in report.values()), report


# --- QA findings (WP-020-FIX, the QA report's bug IDs) ------------------------------------------


async def test_bug_03_history_names_the_people_in_changed_values(world: World) -> None:
    """QA BUG-03: history shows "Technician: (empty) → Tariq", so it returns their names."""
    a = world.a
    item = await world.create(a, a.admin)
    taken = await world.call(
        "POST", f"{BASE}/{item['id']}/take", a, a.tech_a, headers={"If-Match": '"1"'}
    )
    assert taken.status_code == 200, taken.text
    page = await world.call("GET", f"{BASE}/{item['id']}/history", a, a.admin)
    assert page.status_code == 200, page.text
    body = page.json()
    changed = [c for e in body["items"] for c in e["changes"] if c["field"] == "technician_id"]
    assert changed == [{"field": "technician_id", "old": None, "new": str(a.tech_a)}]
    assert body["people"][str(a.tech_a)]["display_name"] == "Alpha Tech A"
    # The requester of the created entry is named too (old and new values, every person field).
    assert body["people"][str(a.requester)]["display_name"] == "Alpha Requester"


async def test_bug_05_start_work_on_an_unassigned_incident_takes_it_first(world: World) -> None:
    """QA BUG-05: "Start work" on an unassigned incident assigns it to the user, then starts it.

    One action, every step in history. A user who may not take it sees the action disabled with
    the reason; a technician of several groups chooses the group as with Take.
    """
    a = world.a
    item = await world.create(a, a.admin)
    view = (await world.get(a, a.tech_a, item)).json()
    assert states(view)["start_work"] is None
    started = await world.act(a, a.tech_a, item, "start_work")
    assert started.status_code == 200, started.text
    body = started.json()
    assert (body["status"], body["technician_id"], body["group_id"]) == (
        "in_progress",
        str(a.tech_a),
        str(a.ga),
    )
    entries = await world.history(a, item)
    kinds = [(e["kind"], [c["field"] for c in e["changes"]]) for e in entries]
    assert ("updated", ["group_id", "technician_id"]) in kinds
    assert entries[0]["kind"] == "status"
    assert {"field": "status", "old": "assigned", "new": "in_progress"} in entries[0]["changes"]
    # Several groups: the group is asked for, then sent with the action.
    other = await world.create(a, a.admin)
    ask = await world.act(a, a.tech_c, other, "start_work")
    assert field_codes(ask) == {"group_id": "group_required"}
    chose = await world.call(
        "POST",
        f"{BASE}/{other['id']}/actions/start_work",
        a,
        a.tech_c,
        headers={"If-Match": f'"{other["version"]}"', **CONSOLE},
        json={"group_id": str(a.gb)},
    )
    assert chose.status_code == 200, chose.text
    assert (chose.json()["technician_id"], chose.json()["group_id"]) == (str(a.tech_c), str(a.gb))
    # May work on incidents but not take them: disabled with the reason, and refused by the API.
    worker = await role(world, a, "Worker", [("incidents.view", "all"), ("incidents.edit", "all")])
    third = await world.create(a, a.admin)
    solo = await make_worker(world, a, worker)
    seen = (await world.get(a, solo, third)).json()
    assert states(seen)["start_work"] == "cannot_take"
    refused = await world.act(a, solo, third, "start_work")
    assert problem(refused) == (403, "permission_denied")
    # Already someone's: start work keeps the current technician (no take).
    mine = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_c))
    kept = await world.act(a, a.lead, mine, "start_work")
    assert kept.status_code == 200, kept.text
    assert kept.json()["technician_id"] == str(a.tech_c)


async def make_worker(world: World, org: Org, role_id: uuid.UUID) -> uuid.UUID:
    """A technician user holding only the given role."""
    (user,) = await seed_users(
        world.db, org.tenant, [{"user_type": "technician", "display_name": "Alpha Worker"}]
    )
    added = await world.call("PUT", f"/users/{user}/roles/{role_id}", org, org.admin)
    assert added.status_code == 204, added.text
    return user


async def test_form_review_default_impact_and_urgency_are_tenant_settings(world: World) -> None:
    """Haider's form review: the create form starts from the tenant's default impact and urgency."""
    a = world.a
    settings = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    assert (settings["default_impact"], settings["default_urgency"]) == ("team", "medium")
    cell = next(c for c in settings["matrix"] if (c["impact"], c["urgency"]) == ("team", "medium"))
    assert cell["priority"] == settings["default_priority"]  # the defaults agree
    changed = await world.call(
        "PATCH",
        f"{BASE}/settings",
        a,
        a.admin,
        headers={"If-Match": f'"{settings["version"]}"'},
        json={"default_impact": "one_person", "default_urgency": None},
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["default_impact"], changed.json()["default_urgency"]) == (
        "one_person",
        None,
    )
    bad = await world.call(
        "PATCH",
        f"{BASE}/settings",
        a,
        a.admin,
        headers={"If-Match": f'"{changed.json()["version"]}"'},
        json={"default_impact": "galaxy"},
    )
    assert bad.status_code == 422, bad.text
