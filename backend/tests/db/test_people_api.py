"""People, sites, departments, groups, desks and imports over HTTP (WP-021; D-073, D-092).

Real PostgreSQL (throwaway database, RLS on); the session is faked by headers, as in the other
API tests. Each test names the requirement or rule it proves.
"""

import io
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
from openpyxl import Workbook
from sqlalchemy import text

from app.core.database import Database, create_engine
from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from app.modules.identity_access.service.people_import import run_people_imports
from conftest import make_settings
from tests.db.test_access_api import Org, fake_session, make_org, problem
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db


@dataclass
class FakeAuth:
    """Stands in for the AuthService: records whose sessions were ended."""

    ended: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)

    async def end_sessions(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.ended.append((tenant_id, user_id))


@dataclass
class World:
    client: AsyncClient
    db: ThrowawayDatabase
    a: Org
    b: Org
    app: FastAPI
    auth: FakeAuth

    async def call(
        self,
        method: str,
        path: str,
        org: Org,
        user: uuid.UUID | None = None,
        **kw: Any,  # noqa: ANN401 - httpx request options
    ) -> httpx.Response:
        headers = {
            "X-Test-Tenant": str(org.tenant),
            "X-Test-User": str(user or org.admin),
            **kw.pop("headers", {}),
        }
        return await self.client.request(method, f"/api/v1{path}", headers=headers, **kw)

    async def person(self, org: Org, **body: Any) -> httpx.Response:  # noqa: ANN401
        return await self.call("POST", "/users", org, json={"first_name": "Pat", **body})

    async def patch(
        self,
        org: Org,
        user_id: str,
        version: int,
        **body: Any,  # noqa: ANN401
    ) -> httpx.Response:
        return await self.call(
            "PATCH",
            f"/users/{user_id}/person",
            org,
            json=body,
            headers={"If-Match": f'"{version}"'},
        )


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    app: FastAPI = create_app(make_settings(database_url=migrated_db.app_url))
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, fake_session)
        auth = FakeAuth()
        app.state.auth = auth
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield World(
                client,
                migrated_db,
                await make_org(migrated_db, "Alpha"),
                await make_org(migrated_db, "Beta"),
                app,
                auth,
            )


# --- tenant isolation of the new tables (CLAUDE.md rule a) ----------------------------------------


@pytest.mark.parametrize(
    "table", ["desks", "departments", "group_sites", "access_settings", "people_imports"]
)
async def test_new_tables_are_tenant_isolated(world: World, table: str) -> None:
    # Each tenant gets rows in every new table through the API.
    for org in (world.a, world.b):
        site = (await world.call("POST", "/organization/sites", org, json={"name": "S"})).json()
        group = await world.call(
            "POST", "/organization/groups", org, json={"name": "G", "site_ids": [site["id"]]}
        )
        assert group.status_code == 201, group.text
        department = await world.call(
            "POST", "/organization/departments", org, json={"name": "D", "code": "d1"}
        )
        assert department.status_code == 201, department.text
        saved = await world.call(
            "PUT",
            "/access-settings",
            org,
            json={"technician_scope": "group"},
            headers={"If-Match": '"0"'},
        )
        assert saved.status_code == 200, saved.text
        started = await world.call(
            "POST",
            "/people-imports",
            org,
            params={"name": "p.csv"},
            content=b"First name,Email\nAmal,amal@x.test\n",
        )
        assert started.status_code == 201, started.text
    database = _database(world)
    try:
        async with database.tenant_session(TenantContext(world.a.tenant)) as session:
            tenants = set(await session.scalars(text(f"SELECT DISTINCT tenant_id FROM {table}")))  # noqa: S608 - fixed table names
            assert tenants == {world.a.tenant}
            # group_sites rows are only added and removed (no UPDATE grant): probe with DELETE.
            write = "DELETE FROM" if table == "group_sites" else "UPDATE"
            tail = "" if table == "group_sites" else " SET tenant_id = tenant_id"
            changed = await session.execute(
                text(f"{write} {table}{tail} WHERE tenant_id = :b"),
                {"b": world.b.tenant},
            )
            assert changed.rowcount == 0  # type: ignore[attr-defined]  # CursorResult at runtime
    finally:
        await database.dispose()


# --- people (REQ-ADM-002..005) --------------------------------------------------------------------


async def test_add_a_contact_and_a_person_who_signs_in(world: World) -> None:
    """REQ-ADM-004: a contact needs no email; signing in does."""
    contact = await world.person(world.a, last_name="Contact", can_sign_in=False)
    assert contact.status_code == 201, contact.text
    body = contact.json()
    assert (body["display_name"], body["email"], body["can_sign_in"]) == (
        "Pat Contact",
        None,
        False,
    )
    assert body["signed_in_before"] is False
    missing = await world.person(world.a, can_sign_in=True)
    assert problem(missing) == (422, "validation_failed")
    assert missing.json()["errors"][0]["code"] == "email_required_for_sign_in"


async def test_values_are_refused_with_their_limit_never_cut(world: World) -> None:
    """D-091: a too-long value is refused at its field with the limit; nothing is shortened."""
    response = await world.person(world.a, email="x@y.test", job_title="j" * 201)
    assert response.status_code == 422
    (error,) = response.json()["errors"]
    assert (error["field"], error["code"], error["params"]) == (
        "body.job_title",
        "value_too_long",
        {"max_length": 200},
    )


async def test_email_and_employee_id_are_unique_ignoring_case(world: World) -> None:
    first = await world.person(world.a, email="Same@Tenant.test", employee_id="E-1")
    assert first.status_code == 201, first.text
    again = await world.person(world.a, email="same@tenant.test", employee_id="E-1")
    codes = {e["code"] for e in again.json()["errors"]}
    assert codes == {"email_taken", "employee_id_taken"}
    # Another tenant may use them: uniqueness is per tenant.
    other = await world.person(world.b, email="same@tenant.test", employee_id="E-1")
    assert other.status_code == 201, other.text


async def test_a_manager_loop_is_refused(world: World) -> None:
    """REQ-ADM-035 AC1: nobody manages their own manager, directly or through others."""
    boss = (await world.person(world.a, email="boss@a.test")).json()
    mid = (await world.person(world.a, email="mid@a.test", manager_id=boss["id"])).json()
    loop = await world.patch(world.a, boss["id"], boss["version"], manager_id=mid["id"])
    assert loop.status_code == 422
    assert loop.json()["errors"][0]["code"] == "manager_loop"


async def test_a_stale_edit_gets_an_explained_conflict(world: World) -> None:
    """QA WP-026 BUG-01 pattern: the editor's version is checked; the 409 says who and what."""
    person = (await world.person(world.a, email="v@a.test")).json()
    saved = await world.patch(world.a, person["id"], person["version"], job_title="Lead")
    assert saved.status_code == 200, saved.text
    stale = await world.patch(world.a, person["id"], person["version"], job_title="Other")
    assert problem(stale) == (409, "version_conflict")
    assert stale.json()["params"]["changed_fields"] == "job_title"
    assert stale.json()["params"]["changed_by"] == "Alpha Admin"


async def test_technicians_take_seats(world: World) -> None:
    """A technician added beyond the licence is refused (D-092; REQ-ADM-002)."""
    conn = await asyncpg.connect(world.db.migrator_url)
    try:
        await conn.execute(
            "UPDATE tenant_subscriptions SET limits = '{\"technicians\": 3}'::jsonb"
            " WHERE tenant_id = $1",
            world.a.tenant,
        )
    finally:
        await conn.close()
    # Alpha already has three technicians (admin, manager, tech).
    refused = await world.person(world.a, email="t@a.test", user_type="technician")
    assert problem(refused) == (403, "technician_limit_reached")
    requester = (await world.person(world.a, email="r@a.test")).json()
    promoted = await world.call(
        "PUT",
        f"/users/{requester['id']}/type",
        world.a,
        json={"user_type": "technician"},
        headers={"If-Match": f'"{requester["version"]}"'},
    )
    assert problem(promoted) == (403, "technician_limit_reached")


async def test_deactivate_ends_sessions_and_keeps_roles_reactivate_keeps_what_is_confirmed(
    world: World,
) -> None:
    """REQ-ADM-005: deactivation removes nothing; reactivation keeps only confirmed access."""
    org = world.a
    me = await world.call("GET", f"/users/{org.tech}", org)
    version = me.json()["version"]
    own = await world.call(
        "POST", f"/users/{org.admin}/deactivate", org, headers={"If-Match": '"1"'}
    )
    assert problem(own) == (403, "cannot_deactivate_self")
    gone = await world.call(
        "POST", f"/users/{org.tech}/deactivate", org, headers={"If-Match": f'"{version}"'}
    )
    assert gone.status_code == 200, gone.text
    assert gone.json()["status"] == "disabled"
    assert world.auth.ended == [(org.tenant, org.tech)]
    held = (await world.call("GET", f"/users/{org.tech}/reactivation", org)).json()
    assert len(held["role_ids"]) == 1  # the technician role, kept while deactivated
    back = await world.call(
        "POST",
        f"/users/{org.tech}/reactivate",
        org,
        json={"keep_role_ids": [], "keep_group_ids": []},
        headers={"If-Match": f'"{gone.json()["version"]}"'},
    )
    assert back.status_code == 200, back.text
    access = (await world.call("GET", f"/users/{org.tech}/access", org)).json()
    # Unconfirmed roles went; the system role of their type is always given back.
    roles = (await world.call("GET", "/roles", org)).json()
    technician = next(r["id"] for r in roles if r["key"] == "technician")
    assert access["role_ids"] == [technician]


async def test_stopping_sign_in_ends_sessions(world: World) -> None:
    person = (await world.person(world.a, email="s@a.test")).json()
    stopped = await world.call(
        "PUT",
        f"/users/{person['id']}/sign-in",
        world.a,
        json={"allowed": False},
        headers={"If-Match": f'"{person["version"]}"'},
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["can_sign_in"] is False
    assert world.auth.ended == [(world.a.tenant, uuid.UUID(person["id"]))]


# --- sites, departments, groups: removal (WP-021 scope) -------------------------------------------


async def test_a_site_or_department_people_sit_at_cannot_be_removed(world: World) -> None:
    org = world.a
    site = (await world.call("POST", "/organization/sites", org, json={"name": "Used"})).json()
    department = (
        await world.call("POST", "/organization/departments", org, json={"name": "Dep"})
    ).json()
    await world.person(org, email="p@a.test", site_id=site["id"], department_id=department["id"])
    blocked = await world.call(
        "DELETE",
        f"/organization/sites/{site['id']}",
        org,
        headers={"If-Match": f'"{site["version"]}"'},
    )
    assert problem(blocked) == (409, "site_in_use")
    assert blocked.json()["params"] == {"people": 1}
    blocked = await world.call(
        "DELETE",
        f"/organization/departments/{department['id']}",
        org,
        headers={"If-Match": f'"{department["version"]}"'},
    )
    assert problem(blocked) == (409, "department_in_use")
    unused = (await world.call("POST", "/organization/sites", org, json={"name": "Free"})).json()
    removed = await world.call(
        "DELETE",
        f"/organization/sites/{unused['id']}",
        org,
        headers={"If-Match": f'"{unused["version"]}"'},
    )
    assert removed.status_code == 204, removed.text


async def test_an_unused_group_can_be_removed(world: World) -> None:
    org = world.a
    group = (await world.call("POST", "/organization/groups", org, json={"name": "QA"})).json()
    removed = await world.call(
        "DELETE",
        f"/organization/groups/{group['id']}",
        org,
        headers={"If-Match": f'"{group["version"]}"'},
    )
    assert removed.status_code == 204, removed.text
    names = [g["name"] for g in (await world.call("GET", "/organization/groups", org)).json()]
    assert "QA" not in names


# --- technician visibility (D-073) ----------------------------------------------------------------


async def test_technician_visibility_is_asked_once_and_widens_the_technician_role(
    world: World,
) -> None:
    org = world.a
    asked = (await world.call("GET", "/access-settings", org)).json()
    assert asked == {"technician_scope": "group", "answered_at": None, "version": 0}
    roles = (await world.call("GET", "/roles", org)).json()
    technician = next(r["id"] for r in roles if r["key"] == "technician")

    async def incident_view_scope() -> str:
        detail = (await world.call("GET", f"/roles/{technician}", org)).json()
        return str(
            next(g["scope"] for g in detail["permissions"] if g["permission"] == "incidents.view")
        )

    assert await incident_view_scope() == "group"
    saved = await world.call(
        "PUT",
        "/access-settings",
        org,
        json={"technician_scope": "all"},
        headers={"If-Match": '"0"'},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["answered_at"] is not None
    assert await incident_view_scope() == "all"
    stale = await world.call(
        "PUT",
        "/access-settings",
        org,
        json={"technician_scope": "group"},
        headers={"If-Match": '"0"'},
    )
    assert problem(stale) == (409, "version_conflict")
    # Only admins (roles.manage) answer it.
    denied = await world.call("GET", "/access-settings", org, org.tech)
    assert denied.status_code == 403


# --- imports (REQ-ADM-003) ------------------------------------------------------------------------


def _database(world: World) -> Database:
    """As the application role (RLS applies), like the consumers worker that runs imports."""
    return Database(create_engine(world.db.app_url, application_name="test", use_null_pool=True))


async def _run_imports(world: World) -> None:
    database = _database(world)
    try:
        await run_people_imports(database, world.app.state.settings)
    finally:
        await database.dispose()


async def test_csv_import_creates_updates_and_reports_rows(world: World) -> None:
    org = world.a
    site = (await world.call("POST", "/organization/sites", org, json={"name": "Riyadh"})).json()
    existing = (await world.person(org, email="known@a.test", job_title="Old")).json()
    csv = (
        b"First name,Last name,Email,Job title,Site,Type\n"
        b"Amal,Saleh,amal@a.test,Analyst,riyadh,requester\n"
        b",,nofirst@a.test,,,\n"
        b"Known,,KNOWN@a.test,New title,,\n"
        b"Zed,,zed@a.test,,Nowhere,\n"
    )
    started = await world.call(
        "POST", "/people-imports", org, params={"name": "people.csv"}, content=csv
    )
    assert started.status_code == 201, started.text
    assert started.json()["status"] == "queued"
    await _run_imports(world)
    job = (await world.call("GET", f"/people-imports/{started.json()['id']}", org)).json()
    assert (job["status"], job["total"], job["processed"]) == ("done", 4, 4)
    assert (job["created_count"], job["updated_count"], job["failed_count"]) == (1, 1, 2)
    assert {(p["row"], p["field"], p["code"]) for p in job["problems"]} == {
        (3, "first_name", "required"),
        (5, "site_id", "site_not_found"),
    }
    known = (await world.call("GET", f"/users/{existing['id']}", org)).json()
    assert known["job_title"] == "New title"
    amal = await world.call("GET", "/users", org, params={"q": "amal@a.test"})
    (row,) = amal.json()["items"]
    assert (row["display_name"], row["site_id"]) == ("Amal Saleh", site["id"])
    # The file is not kept once read.
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        assert await conn.fetchval("SELECT content FROM people_imports") is None
    finally:
        await conn.close()


async def test_excel_import_and_rows_beyond_the_seats_are_refused(world: World) -> None:
    org = world.a
    conn = await asyncpg.connect(world.db.migrator_url)
    try:
        await conn.execute(
            "UPDATE tenant_subscriptions SET limits = '{\"technicians\": 4}'::jsonb"
            " WHERE tenant_id = $1",
            org.tenant,
        )
    finally:
        await conn.close()
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["First name", "Email", "Employee ID", "Type"])
    sheet.append(["One", "one@a.test", 1001, "technician"])  # Excel keeps 1001 as a number
    sheet.append(["Two", "two@a.test", 1002, "technician"])
    buffer = io.BytesIO()
    book.save(buffer)
    started = await world.call(
        "POST",
        "/people-imports",
        org,
        params={"name": "people.xlsx", "match_on": "employee_id"},
        content=buffer.getvalue(),
    )
    assert started.status_code == 201, started.text
    await _run_imports(world)
    job = (await world.call("GET", f"/people-imports/{started.json()['id']}", org)).json()
    assert (job["created_count"], job["failed_count"]) == (1, 1)
    assert job["problems"] == [
        {"row": 3, "field": "user_type", "code": "technician_limit_reached", "detail": None}
    ]
    one = (await world.call("GET", "/users", org, params={"q": "one@a.test"})).json()["items"]
    assert one[0]["employee_id"] == "1001"


async def test_a_file_that_is_not_csv_or_xlsx_is_refused_at_once(world: World) -> None:
    refused = await world.call(
        "POST", "/people-imports", world.a, params={"name": "people.pdf"}, content=b"%PDF-1.7"
    )
    assert problem(refused) == (422, "people_import_file_not_readable")


async def test_an_unknown_column_fails_the_whole_file_with_its_name(world: World) -> None:
    started = await world.call(
        "POST",
        "/people-imports",
        world.a,
        params={"name": "p.csv"},
        content=b"First name,Shoe size\nAmal,40\n",
    )
    await _run_imports(world)
    job = (await world.call("GET", f"/people-imports/{started.json()['id']}", world.a)).json()
    assert (job["status"], job["failure"]) == ("failed", "unknown_column")
    assert job["problems"][0]["detail"] == "Shoe size"


async def test_imports_are_only_for_people_admins(world: World) -> None:
    denied = await world.call(
        "POST",
        "/people-imports",
        world.a,
        world.a.tech,
        params={"name": "p.csv"},
        content=b"First name\nA\n",
    )
    assert denied.status_code == 403


async def test_a_new_incident_takes_the_requesters_department_and_its_site(world: World) -> None:
    """REQ-INC-016 AC1 with WP-021: site and department come from the requester's record."""
    org = world.a
    site = (await world.call("POST", "/organization/sites", org, json={"name": "Jeddah"})).json()
    department = (
        await world.call(
            "POST",
            "/organization/departments",
            org,
            json={"name": "Finance", "site_id": site["id"]},
        )
    ).json()
    person = (await world.person(org, email="fin@a.test", department_id=department["id"])).json()
    created = await world.call(
        "POST", "/incidents", org, json={"subject": "Printer", "requester_id": person["id"]}
    )
    assert created.status_code == 201, created.text
    record = created.json()
    assert (record["department_id"], record["site_id"]) == (department["id"], site["id"])
