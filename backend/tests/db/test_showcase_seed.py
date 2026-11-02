"""The showcase seed (D-124 (5)): only `showcase`, through the API, once, nobody else's data."""

import asyncio
import json
import uuid
from collections import Counter
from collections.abc import Callable
from typing import Any

import asyncpg
import httpx
import pytest

from app.core.config import Settings
from conftest import create_tenant, make_settings
from tooling import db_testing
from tooling import showcase_seed as seed

pytestmark = pytest.mark.db


class FakeKeycloak:
    """Just the admin API calls the seed makes, with state, so a second run finds everything."""

    def __init__(self) -> None:
        self.orgs: list[dict[str, Any]] = []
        self.users: dict[str, dict[str, Any]] = {}
        self.roles: dict[str, set[str]] = {}
        self.members: dict[str, set[str]] = {}
        self.passwords: dict[str, str] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:  # noqa: C901, PLR0911 - one branch per call
        path = request.url.path.removeprefix("/admin/realms/supportx")
        method = request.method
        if request.url.path == "/realms/master/protocol/openid-connect/token":
            return httpx.Response(200, json={"access_token": "t"})
        if path == "/organizations" and method == "GET":
            return httpx.Response(200, json=self.orgs)
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


async def _states(url: str) -> Counter[str]:
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(seed.TENANT_ID))
            rows = await conn.fetch("SELECT status, technician_id FROM work_items")
    finally:
        await conn.close()
    return Counter(f"{r['status']}{'' if r['technician_id'] else ' unassigned'}" for r in rows)


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
    return report


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


def test_fills_showcase_through_the_api_once_and_leaves_other_tenants_alone(
    db_config: db_testing.DbTestConfig,
) -> None:
    database = db_testing.create(db_config)
    try:
        bystander = asyncio.run(create_tenant(database.migrator_url, "Bystander"))
        before = asyncio.run(_counts(database.migrator_url, bystander))
        keycloak = FakeKeycloak()
        # The technician came from the dev realm file without a password: the seed gives one.
        imported = "imported-tech"
        keycloak.users[imported] = {"id": imported, "email": seed.TECHNICIAN.email}
        keycloak.roles[imported] = set()

        first = asyncio.run(_run(database, keycloak))
        assert first.tenant == ["tenant", "subscription"]
        assert first.incidents == len(seed.STATES) == 60
        assert first.dashboard
        # The password is the environment's, set only on the users made here.
        assert keycloak.passwords == dict.fromkeys(keycloak.users, "Showcase-Pass-2026!")
        assert any(f"password {seed.TECHNICIAN.email}" == m for m in first.keycloak)
        keycloak.passwords[imported] = "Changed-By-Hand-1!"  # never overwritten
        assert {u["email"] for u in keycloak.users.values()} == {s.email for s in seed.SIGN_INS}
        counts = asyncio.run(_counts(database.migrator_url, seed.TENANT_ID))
        assert counts["users"] == len(seed.PEOPLE) + len(seed.SIGN_INS)
        assert counts["work_items"] == 60
        assert asyncio.run(_states(database.migrator_url)) == {
            "new unassigned": 10,
            "assigned": 14,
            "in_progress": 12,
            "awaiting_requester": 6,
            "resolved": 10,
            "closed": 8,
        }

        second = asyncio.run(_run(database, keycloak))
        assert (second.tenant, second.keycloak, second.incidents, second.dashboard) == (
            [],
            [],
            0,
            False,
        )
        assert asyncio.run(_counts(database.migrator_url, seed.TENANT_ID)) == counts
        assert asyncio.run(_counts(database.migrator_url, bystander)) == before
        assert keycloak.passwords[imported] == "Changed-By-Hand-1!"
    finally:
        db_testing.destroy(db_config, database)
