"""A business service's subscribers over HTTP (WP-053, D-172 (3); migration 0185).

The coordinator's conditions: tenant first with RLS (a cross-tenant test), a version, the outbox
event and the audit entry on every change; each active person counted once however many refs
reach them; disabled people and an emptied group count nobody; a removed unit reads "removed",
counts nobody and never shows its ID as a name; names of people only with `users.view`.

Real PostgreSQL and Valkey on the incident world: every organisation is new (rule 5h).
"""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_relationships import _given, _made
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _match

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

TABLE = "cmdb_service_subscribers"


async def _unit(world: World, org: Org, plural: str, name: str) -> dict[str, Any]:
    made = await world.call("POST", f"/organization/{plural}", org, org.admin, json={"name": name})
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _get(world: World, org: Org, ci: dict[str, Any], user: uuid.UUID) -> httpx.Response:
    return await world.call("GET", f"/cmdb/cis/{ci['id']}/subscribers", org, user)


async def _put(
    world: World,
    org: Org,
    ci: dict[str, Any],
    refs: list[tuple[str, Any]],
    *,
    version: int | None = None,
) -> httpx.Response:
    if version is None:
        version = int((await _get(world, org, ci, org.admin)).headers["ETag"].strip('"'))
    return await world.call(
        "PUT",
        f"/cmdb/cis/{ci['id']}/subscribers",
        org,
        org.admin,
        json={"subscribers": [{"kind": k, "ref_id": str(i)} for k, i in refs]},
        headers=_match(version),
    )


async def test_the_subscribers_table_is_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    service = await _made(world, a, f"RLS service {uuid.uuid4().hex[:6]}", "business_service")
    made = await _put(world, a, service, [("group", a.ga)])
    assert made.status_code == 200, made.text
    # Tenant B's admin cannot read tenant A's CI, nor its subscribers.
    assert problem(await _get(world, b, service, b.admin)) == (404, "cmdb_ci_not_found")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await session.execute(text(f"SELECT count(*) FROM {TABLE}"))).scalar_one() > 0  # noqa: S608 - a fixed table name
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text(f"SELECT count(*) FROM {TABLE} WHERE tenant_id = :a"),  # noqa: S608 - a fixed table name
            {"a": a.tenant},
        )
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text(f"UPDATE {TABLE} SET tenant_id = tenant_id WHERE tenant_id = :a"),  # noqa: S608 - a fixed table name
            {"a": a.tenant},
        )
        assert changed.rowcount == 0


async def test_people_count_once_and_disabled_or_removed_count_nobody(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    service = await _made(world, a, f"Payroll {tag}", "business_service")
    department = await _unit(world, a, "departments", f"Finance {tag}")
    group = await _unit(world, a, "groups", f"Payroll team {tag}")
    site = await _unit(world, a, "sites", f"Annex {tag}")
    await world.sql(
        "UPDATE users SET department_id = $1 WHERE id = ANY($2::uuid[])",
        uuid.UUID(department["id"]),
        [a.requester, a.requester2],
    )
    await world.sql("UPDATE users SET site_id = $1 WHERE id = $2", uuid.UUID(site["id"]), a.tech_b)
    for member in (a.requester2, a.tech_a):  # requester2 is in the department too
        added = await world.call(
            "PUT", f"/organization/groups/{group['id']}/members/{member}", a, a.admin
        )
        assert added.status_code in (200, 204), added.text
    made = await _put(
        world,
        a,
        service,
        [("department", department["id"]), ("group", group["id"]), ("site", site["id"])],
    )
    assert made.status_code == 200, made.text
    assert made.json()["people"] == 4  # requester, requester2 (once), tech_a, tech_b
    names = {s["kind"]: s["name"]["label"] for s in made.json()["items"]}
    assert names == {"department": f"Finance {tag}", "group": f"Payroll team {tag}",
                     "site": f"Annex {tag}"}  # fmt: skip
    # A disabled person counts nobody.
    await world.sql("UPDATE users SET status = 'disabled' WHERE id = $1", a.tech_b)
    try:
        assert (await _get(world, a, service, a.admin)).json()["people"] == 3
    finally:
        await world.sql("UPDATE users SET status = 'active' WHERE id = $1", a.tech_b)
    # An emptied group counts nobody (requester2 still comes through the department).
    for member in (a.requester2, a.tech_a):
        gone = await world.call(
            "DELETE", f"/organization/groups/{group['id']}/members/{member}", a, a.admin
        )
        assert gone.status_code in (200, 204), gone.text
    assert (await _get(world, a, service, a.admin)).json()["people"] == 3  # D: 2, site: 1
    # A removed department reads "removed", by name, and counts nobody (its people still name it).
    await world.sql(
        "UPDATE departments SET deleted_at = now() WHERE id = $1", uuid.UUID(department["id"])
    )
    after = (await _get(world, a, service, a.admin)).json()
    removed = next(s for s in after["items"] if s["kind"] == "department")
    assert removed["removed"] is True
    assert removed["name"]["label"] == f"Finance {tag}"
    assert department["id"] not in str(removed["name"])
    assert after["people"] == 1  # only the site's tech_b


async def test_only_a_business_service_takes_subscribers_and_each_unit_must_exist(
    world: World,
) -> None:
    a = world.a
    server = await _made(world, a, f"Not a service {uuid.uuid4().hex[:6]}", "server")
    refused = await _put(world, a, server, [("group", a.ga)])
    assert field_codes(refused) == {"subscribers": "cmdb_not_business_service"}
    service = await _made(world, a, f"Service {uuid.uuid4().hex[:6]}", "business_service")
    unknown = await _put(world, a, service, [("group", uuid.uuid4())])
    assert field_codes(unknown) == {"subscribers": "not_found"}
    too_many = await _put(world, a, service, [("group", uuid.uuid4()) for _ in range(101)])
    assert too_many.status_code == 422, too_many.text


async def test_a_change_needs_the_version_and_leaves_an_event_history_and_audit(
    world: World,
) -> None:
    a = world.a
    service = await _made(world, a, f"Audited {uuid.uuid4().hex[:6]}", "business_service")
    version = int((await _get(world, a, service, a.admin)).headers["ETag"].strip('"'))
    stale = await _put(world, a, service, [("group", a.ga)], version=version + 7)
    assert stale.status_code == 409, stale.text
    made = await _put(world, a, service, [("group", a.ga)], version=version)
    assert made.status_code == 200, made.text
    assert int(made.headers["ETag"].strip('"')) == version + 1
    events = await world.sql(
        "SELECT envelope->'payload' AS payload FROM outbox_events WHERE tenant_id = $1"
        " AND envelope->>'event_type' = 'cmdb.ci.updated'"
        " AND envelope->'payload'->>'ci_id' = $2",
        a.tenant,
        service["id"],
    )
    assert any("subscribers" in str(e["payload"]) for e in events)
    history = await world.call("GET", f"/cmdb/cis/{service['id']}/history", a, a.admin)
    assert "subscribers" in history.text
    assert str(a.ga) not in history.text  # a count, never the refs' IDs (rule d)
    audited = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'cmdb.subscribers_changed' AND object_id = $2 AND outcome = 'done'",
        a.tenant,
        service["id"],
    )
    assert audited[0]["n"] == 1


async def test_names_of_people_need_users_view(world: World) -> None:
    a = world.a
    service = await _made(world, a, f"Named {uuid.uuid4().hex[:6]}", "business_service")
    assert (await _put(world, a, service, [("group", a.ga)])).status_code == 200
    everyone = await world.call("GET", f"/cmdb/cis/{service['id']}/subscribers/people", a, a.admin)
    assert everyone.status_code == 200, everyone.text
    assert everyone.json(), "the admin sees who the group reaches"
    await _given(
        world, a, a.requester2, f"CMDB reader {uuid.uuid4().hex[:6]}", [("cmdb.view", "all")]
    )
    count_only = await _get(world, a, service, a.requester2)
    assert count_only.status_code == 200, count_only.text
    assert count_only.json()["people"] >= 1  # the count, for any reader of the CI
    names = await world.call(
        "GET", f"/cmdb/cis/{service['id']}/subscribers/people", a, a.requester2
    )
    assert names.status_code == 403, names.text
