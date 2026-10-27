"""WP-021 QA findings (~/Desktop/qa-wp021/QA-REPORT.md), one test per ID (WP-021-FIX; D-096)."""

import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from tests.db.test_people_api import World, _run_imports, people_world
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    async with people_world(migrated_db) as built:
        yield built


async def test_bug_01_an_empty_name_is_required_not_a_validator_code(world: World) -> None:
    """An empty name came back as Pydantic's `string_type`, shown as "String Type"."""
    for body in ({"name": None}, {}):
        response = await world.call("POST", "/organization/departments", world.a, json=body)
        assert response.status_code == 422, response.text
        (error,) = response.json()["errors"]
        assert (error["field"], error["code"], error["message_key"]) == (
            "body.name",
            "required",
            "errors.field.required",
        )


async def test_bug_02_too_long_says_the_limit(world: World) -> None:
    """D-091: the message names the limit; the service and request checks alike."""
    person = await world.person(world.a, email="long@a.test", job_title="j" * 201)
    (error,) = person.json()["errors"]
    assert (error["code"], error["message_key"], error["params"]) == (
        "value_too_long",
        "errors.field.value_too_long_max",
        {"max_length": 200},
    )
    site = await world.call("POST", "/organization/sites", world.a, json={"name": "s" * 201})
    (error,) = site.json()["errors"]
    assert (error["code"], error["message_key"], error["params"]) == (
        "value_too_long",
        "errors.field.value_too_long_max",
        {"max_length": 200},
    )
    department = await world.call(
        "POST",
        "/organization/departments",
        world.a,
        json={"name": "Dept", "description": "d" * 2001},
    )
    (error,) = department.json()["errors"]
    assert (error["field"], error["message_key"], error["params"]) == (
        "body.description",
        "errors.field.value_too_long_max",
        {"max_length": 2000},
    )


async def _role_keys(world: World, user_id: str) -> list[str]:
    access = (await world.call("GET", f"/users/{user_id}/access", world.a)).json()
    roles = {r["id"]: r["key"] for r in (await world.call("GET", "/roles", world.a)).json()}
    return sorted(roles[role_id] for role_id in access["role_ids"])


async def test_bug_06_a_type_change_swaps_the_system_role(world: World) -> None:
    """A requester made technician kept the Requester role next to Technician."""
    person = (await world.person(world.a, email="swap@a.test")).json()
    assert await _role_keys(world, person["id"]) == ["requester"]
    made = await world.call(
        "PUT",
        f"/users/{person['id']}/type",
        world.a,
        json={"user_type": "technician"},
        headers={"If-Match": f'"{person["version"]}"'},
    )
    assert made.status_code == 200, made.text
    assert await _role_keys(world, person["id"]) == ["technician"]
    back = await world.call(
        "PUT",
        f"/users/{person['id']}/type",
        world.a,
        json={"user_type": "requester"},
        headers={"If-Match": f'"{made.json()["version"]}"'},
    )
    assert back.status_code == 200, back.text
    assert await _role_keys(world, person["id"]) == ["requester"]


async def test_c4_import_suggests_the_departments_site_never_overwrites(world: World) -> None:
    """D-096: an empty site takes the department's site; a site already set stays."""
    org = world.a
    riyadh = (await world.call("POST", "/organization/sites", org, json={"name": "Riyadh"})).json()
    jeddah = (await world.call("POST", "/organization/sites", org, json={"name": "Jeddah"})).json()
    finance = await world.call(
        "POST",
        "/organization/departments",
        org,
        json={"name": "Finance", "code": "fin", "site_id": riyadh["id"]},
    )
    assert finance.status_code == 201, finance.text
    placed = (await world.person(org, email="placed@a.test", site_id=jeddah["id"])).json()
    csv = (
        f"First name,Email,Department\nNew,new@a.test,fin\nPlaced,{placed['email']},fin\n"
    ).encode()
    started = await world.call(
        "POST", "/people-imports", org, params={"name": "p.csv"}, content=csv
    )
    assert started.status_code == 201, started.text
    await _run_imports(world)
    job = (await world.call("GET", f"/people-imports/{started.json()['id']}", org)).json()
    assert (job["created_count"], job["updated_count"], job["failed_count"]) == (1, 1, 0)
    new = (await world.call("GET", "/users", org, params={"q": "new@a.test"})).json()["items"][0]
    assert new["site_id"] == riyadh["id"]
    kept = (await world.call("GET", f"/users/{placed['id']}", org)).json()
    assert (kept["site_id"], kept["department_id"]) == (jeddah["id"], finance.json()["id"])


async def test_c4_a_site_in_the_file_wins_over_the_suggestion(world: World) -> None:
    org = world.a
    riyadh = (await world.call("POST", "/organization/sites", org, json={"name": "Riyadh"})).json()
    await world.call("POST", "/organization/sites", org, json={"name": "Dammam"})
    await world.call(
        "POST",
        "/organization/departments",
        org,
        json={"name": "Finance", "code": "fin", "site_id": riyadh["id"]},
    )
    started = await world.call(
        "POST",
        "/people-imports",
        org,
        params={"name": "p.csv"},
        content=b"First name,Email,Department,Site\nSam,sam@a.test,fin,Dammam\n",
    )
    await _run_imports(world)
    assert started.status_code == 201
    sam = (await world.call("GET", "/users", org, params={"q": "sam@a.test"})).json()["items"][0]
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        name = await conn.fetchval(
            "SELECT name FROM sites WHERE id = $1", uuid.UUID(sam["site_id"])
        )
    finally:
        await conn.close()
    assert name == "Dammam"


async def test_bug_08_changing_a_persons_site_department_or_manager(world: World) -> None:
    """Found while fixing: the field history got raw UUIDs and the save failed with a 500."""
    org = world.a
    site = (await world.call("POST", "/organization/sites", org, json={"name": "North"})).json()
    department = (
        await world.call("POST", "/organization/departments", org, json={"name": "Ops"})
    ).json()
    boss = (await world.person(org, email="boss8@a.test")).json()
    person = (await world.person(org, email="p8@a.test")).json()
    saved = await world.patch(
        org,
        person["id"],
        person["version"],
        site_id=site["id"],
        department_id=department["id"],
        manager_id=boss["id"],
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["site_id"], body["department_id"], body["manager_id"]) == (
        site["id"],
        department["id"],
        boss["id"],
    )
