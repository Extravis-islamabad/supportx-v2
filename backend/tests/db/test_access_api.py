"""Access administration over HTTP: roles, assignments, protections and attacks (WP-016).

Real PostgreSQL and Valkey (the compiled-permission cache). The session is faked by headers
(X-Test-Tenant / X-Test-User); users and their system roles are seeded directly.
"""

import statistics
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules.identity_access import authorize
from conftest import assign_system_role, create_tenant, make_settings
from tests.db.test_rate_limit import valkey_url
from tests.db.test_users_api import seed_users
from tooling import timing
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]


async def fake_session(request: Request) -> TenantContext | None:
    tenant = request.headers.get("x-test-tenant")
    user = request.headers.get("x-test-user")
    if tenant is None:
        return None
    return TenantContext(uuid.UUID(tenant), uuid.UUID(user) if user else None)


@dataclass
class Org:
    """One tenant with an admin, a manager (custom role), a technician and a requester."""

    tenant: uuid.UUID
    admin: uuid.UUID
    manager: uuid.UUID
    tech: uuid.UUID
    requester: uuid.UUID


@dataclass
class World:
    client: AsyncClient
    db: ThrowawayDatabase
    a: Org
    b: Org
    app: FastAPI

    async def call(
        self,
        method: str,
        path: str,
        org: Org,
        user: uuid.UUID,
        **kw: Any,  # noqa: ANN401 - httpx request options
    ) -> httpx.Response:
        headers = {
            "X-Test-Tenant": str(org.tenant),
            "X-Test-User": str(user),
            **kw.pop("headers", {}),
        }
        return await self.client.request(method, f"/api/v1{path}", headers=headers, **kw)

    async def role_id(self, org: Org, key: str) -> uuid.UUID:
        roles = (await self.call("GET", "/roles", org, org.admin)).json()
        return uuid.UUID(next(r["id"] for r in roles if r["key"] == key))

    async def create_role(
        self, org: Org, user: uuid.UUID, name: str, grants: list[dict[str, Any]]
    ) -> httpx.Response:
        return await self.call(
            "POST", "/roles", org, user, json={"name": name, "permissions": grants}
        )


async def make_org(db: ThrowawayDatabase, name: str) -> Org:
    tenant = await create_tenant(db.migrator_url, name)
    admin, manager, tech, requester = await seed_users(
        db,
        tenant,
        [
            {"user_type": "technician", "display_name": f"{name} Admin"},
            {"user_type": "technician", "display_name": f"{name} Manager"},
            {"user_type": "technician", "display_name": f"{name} Tech"},
            {"user_type": "requester", "display_name": f"{name} Requester"},
        ],
    )
    await assign_system_role(db.admin_url, tenant, admin, "tenant_admin")
    await assign_system_role(db.admin_url, tenant, tech, "technician")
    await assign_system_role(db.admin_url, tenant, requester, "requester")
    await assign_system_role(db.admin_url, tenant, manager, "requester")
    return Org(tenant, admin, manager, tech, requester)


MANAGER_GRANTS = [
    {"permission": "roles.view", "scope": "all"},
    {"permission": "roles.manage", "scope": "all"},
    {"permission": "users.view", "scope": "all"},
    {"permission": "users.manage", "scope": "all"},
    {"permission": "requests.view", "scope": "site"},
]


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    app: FastAPI = create_app(make_settings(database_url=migrated_db.app_url, valkey_url=url))
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            w = World(
                client,
                migrated_db,
                await make_org(migrated_db, "Alpha"),
                await make_org(migrated_db, "Beta"),
                app,
            )
            for org in (w.a, w.b):
                created = await w.create_role(org, org.admin, "Access manager", MANAGER_GRANTS)
                assert created.status_code == 201, created.text
                assigned = await w.call(
                    "PUT", f"/users/{org.manager}/roles/{created.json()['id']}", org, org.admin
                )
                assert assigned.status_code == 204, assigned.text
            yield w
            keys = [
                k
                async for k in app.state.policy.cache.client.scan_iter(
                    match=f"{app.state.settings.valkey_key_prefix}*"
                )
            ]
            if keys:
                await app.state.policy.cache.client.delete(*keys)


def problem(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


# --- roles CRUD (admin) ---------------------------------------------------------------------------


async def test_roles_lifecycle_with_etags(world: World) -> None:
    a = world.a
    roles = (await world.call("GET", "/roles", a, a.admin)).json()
    assert [r["key"] for r in roles][:3] == sorted(
        ["requester", "technician", "tenant_admin"], key=lambda k: k
    )[:0] + [r["key"] for r in roles if r["is_system"]][:3]
    assert {r["key"] for r in roles if r["is_system"]} == {
        "tenant_admin",
        "technician",
        "requester",
        "auditor",
    }

    created = await world.create_role(
        a,
        a.admin,
        "HR desk",
        [
            {
                "permission": "requests.view",
                "scope": "all",
                "condition": {"field": "display_name", "op": "eq", "value": "x"},
            },
        ],
    )
    # requests has no resource type yet: attribute rules are refused with a field error.
    assert problem(created) == (422, "validation_failed")
    assert created.json()["errors"][0]["code"] == "condition_not_supported"

    created = await world.create_role(
        a,
        a.admin,
        "HR desk",
        [
            {
                "permission": "users.view",
                "scope": "all",
                "condition": {"field": "user_type", "op": "eq", "value": "requester"},
            },
            {"permission": "requests.view", "scope": "group"},
        ],
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert created.headers["ETag"] == '"1"'
    fetched = await world.call("GET", f"/roles/{role['id']}", a, a.admin)
    grants = {g["permission"]: g for g in fetched.json()["permissions"]}
    assert grants["users.view"]["condition"] == {
        "field": "user_type",
        "op": "eq",
        "value": "requester",
    }
    assert grants["requests.view"] == {
        "permission": "requests.view",
        "scope": "group",
        "condition": None,
    }

    patch = {
        "name": "HR service desk",
        "permissions": [{"permission": "requests.view", "scope": "all"}],
    }
    edited = await world.call(
        "PATCH", f"/roles/{role['id']}", a, a.admin, json=patch, headers={"If-Match": '"1"'}
    )
    assert (edited.status_code, edited.json()["version"]) == (200, 2)
    stale = await world.call(
        "PATCH", f"/roles/{role['id']}", a, a.admin, json=patch, headers={"If-Match": '"1"'}
    )
    assert problem(stale) == (409, "version_conflict")

    catalogue = (await world.call("GET", "/permissions", a, a.admin)).json()
    assert {p["key"] for p in catalogue} >= {"users.view", "changes.approve", "licence.manage"}
    assert next(p for p in catalogue if p["key"] == "users.view")["conditions_supported"] is True


async def test_role_in_use_needs_a_replacement(world: World) -> None:
    a = world.a
    role = (
        await world.create_role(
            a, a.admin, "Temp", [{"permission": "reports.view", "scope": "all"}]
        )
    ).json()
    await world.call("PUT", f"/users/{a.tech}/roles/{role['id']}", a, a.admin)
    refused = await world.call(
        "DELETE", f"/roles/{role['id']}", a, a.admin, headers={"If-Match": '"1"'}
    )
    assert problem(refused) == (409, "role_in_use")
    assert refused.json()["params"] == {"users": 1}
    technician = await world.role_id(a, "technician")
    deleted = await world.call(
        "DELETE",
        f"/roles/{role['id']}",
        a,
        a.admin,
        headers={"If-Match": '"1"'},
        params={"reassign_to": str(technician)},
    )
    assert deleted.status_code == 204, deleted.text
    access = (await world.call("GET", f"/users/{a.tech}/access", a, a.admin)).json()
    assert access["role_ids"] == [str(technician)]
    assert role["id"] not in {
        r["id"] for r in (await world.call("GET", "/roles", a, a.admin)).json()
    }


# --- attacks --------------------------------------------------------------------------------------


async def test_non_admin_cannot_make_themselves_admin(world: World) -> None:
    a = world.a
    admin_role = await world.role_id(a, "tenant_admin")
    attempt = await world.call("PUT", f"/users/{a.manager}/roles/{admin_role}", a, a.manager)
    assert problem(attempt) == (403, "privilege_escalation")
    assert (
        str(admin_role)
        not in (await world.call("GET", f"/users/{a.manager}/access", a, a.admin)).json()[
            "role_ids"
        ]
    )


async def test_non_admin_cannot_grant_more_than_they_hold(world: World) -> None:
    a = world.a
    for grants in (
        [{"permission": "settings.manage", "scope": "all"}],  # not held at all
        [{"permission": "requests.view", "scope": "all"}],  # held only at site scope
        [{"permission": "requests.view", "scope": "group"}],  # site does not include group records
    ):
        attempt = await world.create_role(a, a.manager, "Sneaky", grants)
        assert problem(attempt) == (403, "privilege_escalation"), grants
    within = await world.create_role(
        a, a.manager, "Site viewer", [{"permission": "requests.view", "scope": "site"}]
    )
    assert within.status_code == 201
    # ...and cannot hand out an existing role that holds more (the technician role).
    technician = await world.role_id(a, "technician")
    attempt = await world.call("PUT", f"/users/{a.requester}/roles/{technician}", a, a.manager)
    assert problem(attempt) == (403, "privilege_escalation")


async def test_non_admin_cannot_edit_a_role_above_their_own_power(world: World) -> None:
    a = world.a
    strong = (
        await world.create_role(
            a, a.admin, "Strong", [{"permission": "settings.manage", "scope": "all"}]
        )
    ).json()
    attempt = await world.call(
        "PATCH",
        f"/roles/{strong['id']}",
        a,
        a.manager,
        json={"name": "Mine now"},
        headers={"If-Match": '"1"'},
    )
    assert problem(attempt) == (403, "privilege_escalation")


async def test_system_roles_cannot_be_changed_or_deleted(world: World) -> None:
    a = world.a
    technician = await world.role_id(a, "technician")
    for method, kw in (("PATCH", {"json": {"name": "Hacked"}}), ("DELETE", {})):
        attempt = await world.call(
            method, f"/roles/{technician}", a, a.admin, headers={"If-Match": '"1"'}, **kw
        )
        assert problem(attempt) == (403, "system_role_immutable")


async def test_the_last_tenant_admin_keeps_the_role(world: World) -> None:
    a = world.a
    admin_role = await world.role_id(a, "tenant_admin")
    attempt = await world.call("DELETE", f"/users/{a.admin}/roles/{admin_role}", a, a.admin)
    assert problem(attempt) == (409, "last_tenant_admin")
    # A second admin first: then one of them may step down.
    assert (
        await world.call("PUT", f"/users/{a.tech}/roles/{admin_role}", a, a.admin)
    ).status_code == 204
    assert (
        await world.call("DELETE", f"/users/{a.admin}/roles/{admin_role}", a, a.admin)
    ).status_code == 204
    # A non-admin can never take the admin role from anyone.
    attempt = await world.call("DELETE", f"/users/{a.tech}/roles/{admin_role}", a, a.manager)
    assert problem(attempt) == (403, "privilege_escalation")


async def test_other_tenants_roles_and_users_are_invisible(world: World) -> None:
    a, b = world.a, world.b
    b_role = await world.role_id(b, "technician")
    assert problem(await world.call("GET", f"/roles/{b_role}", a, a.admin)) == (404, "not_found")
    assert (
        await world.call("PUT", f"/users/{a.tech}/roles/{b_role}", a, a.admin)
    ).status_code == 404
    a_role = await world.role_id(a, "technician")
    assert problem(await world.call("PUT", f"/users/{b.tech}/roles/{a_role}", a, a.admin)) == (
        404,
        "user_not_found",
    )
    assert {r["id"] for r in (await world.call("GET", "/roles", a, a.admin)).json()}.isdisjoint(
        {r["id"] for r in (await world.call("GET", "/roles", b, b.admin)).json()}
    )


async def test_requesters_have_no_admin_api(world: World) -> None:
    a = world.a
    for method, path in (
        ("GET", "/roles"),
        ("GET", "/permissions"),
        ("POST", "/roles"),
        ("GET", "/users"),
    ):
        response = await world.call(method, path, a, a.requester, json={"name": "x"})
        assert problem(response) == (403, "permission_denied"), path


# --- cache: a change takes effect on the next request ---------------------------------------------


async def test_removing_a_role_takes_effect_on_the_next_request(world: World) -> None:
    a = world.a
    assert (await world.call("GET", "/users", a, a.tech)).status_code == 200  # compiled + cached
    technician = await world.role_id(a, "technician")
    removed = await world.call("DELETE", f"/users/{a.tech}/roles/{technician}", a, a.admin)
    assert removed.status_code == 204
    start = time.perf_counter()
    after = await world.call("GET", "/users", a, a.tech)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert problem(after) == (403, "permission_denied")
    print(f"first request after the role change: {elapsed_ms:.1f} ms (recompiled)")  # noqa: T201

    # Re-granting works the same way.
    assert (
        await world.call("PUT", f"/users/{a.tech}/roles/{technician}", a, a.admin)
    ).status_code == 204
    assert (await world.call("GET", "/users", a, a.tech)).status_code == 200


async def test_custom_role_permissions_and_conditions_apply_to_lists(world: World) -> None:
    a = world.a
    role = (
        await world.create_role(
            a,
            a.admin,
            "Requester directory",
            [
                {
                    "permission": "users.view",
                    "scope": "all",
                    "condition": {"field": "user_type", "op": "eq", "value": "requester"},
                },
            ],
        )
    ).json()
    await world.call("PUT", f"/users/{a.requester}/roles/{role['id']}", a, a.admin)
    listed = (await world.call("GET", "/users", a, a.requester)).json()["items"]
    assert {u["user_type"] for u in listed} == {"requester"}
    # last_login_at is hidden without users.manage (field-level visibility).
    assert all(u["last_login_at"] is None for u in listed)


async def test_site_membership_widens_a_site_scope(world: World) -> None:
    a = world.a
    site = await world.call(
        "POST", "/organization/sites", a, a.admin, json={"name": "Dubai office"}
    )
    assert site.status_code == 201, site.text
    site_id = site.json()["id"]
    role = (
        await world.create_role(
            a, a.admin, "Site directory", [{"permission": "users.view", "scope": "site"}]
        )
    ).json()
    await world.call("PUT", f"/users/{a.requester}/roles/{role['id']}", a, a.admin)
    assert (await world.call("GET", "/users", a, a.requester)).json()["items"] == []
    for user in (a.requester, a.tech):
        added = await world.call("PUT", f"/organization/sites/{site_id}/members/{user}", a, a.admin)
        assert added.status_code == 204
    names = {
        u["display_name"]
        for u in (await world.call("GET", "/users", a, a.requester)).json()["items"]
    }
    assert names == {"Alpha Requester", "Alpha Tech"}
    assert problem(
        await world.call("PUT", f"/organization/sites/{site_id}/members/{a.admin}", a, a.tech)
    ) == (
        403,
        "permission_denied",
    )


@pytest.mark.timing
async def test_cached_permission_check_timing(world: World) -> None:
    """How long a check costs: compile once, then Valkey hits, then the in-memory decision."""
    a = world.a
    policy = world.app.state.policy
    await policy.invalidate(a.tenant)
    start = time.perf_counter()
    compiled = await policy.subject(a.tenant, a.tech)
    compile_ms = (time.perf_counter() - start) * 1000
    samples = []
    for _ in range(200):
        start = time.perf_counter()
        cached = await policy.subject(a.tenant, a.tech)
        samples.append((time.perf_counter() - start) * 1000)
    assert cached == compiled
    start = time.perf_counter()
    for _ in range(10_000):
        authorize(cached, "requests.view")
    decide_us = (time.perf_counter() - start) * 1_000_000 / 10_000
    hit_ms = statistics.median(samples)
    report = f"compile {compile_ms:.1f} ms; cached subject p50 {hit_ms:.2f} ms"
    print(f"{report}; decision {decide_us:.2f} us")  # noqa: T201
    timing.record("permission_check", {"compile_ms": compile_ms, "cached_p50_ms": hit_ms})
    assert hit_ms < timing.limit(20)
