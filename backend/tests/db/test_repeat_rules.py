"""Repeat incident rules without AI (WP-044c S3, D16; REQ-PRB-068; migration 0110)."""

import asyncio
import uuid
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules import licensing
from app.modules.work_items.service import repeat_rules
from conftest import assign_system_role, create_tenant
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, field_codes, problem
from tests.db.test_users_api import seed_users

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

API = "/problem-repeats"


async def evaluate(world: World, org: Org) -> int:
    database = Database(create_engine(world.db.app_url, application_name="test"))
    try:
        async with database.tenant_session(TenantContext(org.tenant)) as session:
            return await repeat_rules.evaluate(session)
    finally:
        await database.dispose()


async def a_category(world: World, org: Org) -> str:
    tree = (await world.call("GET", f"{BASE}/categories", org, org.admin)).json()
    return str(tree[0]["id"])


async def incidents(world: World, org: Org, n: int, **values: Any) -> list[str]:  # noqa: ANN401 - JSON
    return [(await world.create(org, org.admin, **values))["id"] for _ in range(n)]


async def hits(world: World, org: Org) -> list[Any]:
    return await world.sql(
        "SELECT id, incident_count, handled_at FROM problem_repeat_hits WHERE tenant_id = $1",
        org.tenant,
    )


async def test_req_prb_068_ten_in_one_category_and_site_open_one_hit(world: World) -> None:
    a = world.a
    category = await a_category(world, a)
    await incidents(world, a, 9, category_id=category, site_id=str(a.s1))
    assert await evaluate(world, a) == 0  # nine is not ten (the default rule)
    await incidents(world, a, 1, category_id=category, site_id=str(a.s1))
    assert await evaluate(world, a) == 1
    # AC2: fires once per set: an eleventh joins the open hit, nobody is told again.
    await incidents(world, a, 1, category_id=category, site_id=str(a.s1))
    assert await evaluate(world, a) == 0
    [hit] = await hits(world, a)
    assert hit["incident_count"] == 11
    detected = await world.sql(
        "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1"
        " AND envelope->>'event_type' = 'work_items.problem_repeat.detected'",
        a.tenant,
    )
    assert detected[0]["n"] == 1
    # Another tenant's evaluation never sees this tenant's incidents (RLS).
    assert await evaluate(world, world.b) == 0
    assert await hits(world, world.b) == []


async def test_req_prb_068_two_overlapping_runs_open_one_hit(world: World) -> None:
    a = world.a
    category = await a_category(world, a)
    await incidents(world, a, 10, category_id=category, site_id=str(a.s1))
    opened = await asyncio.gather(evaluate(world, a), evaluate(world, a))
    assert sum(opened) == 1  # ON CONFLICT on the open-hit index: only one run opens it
    assert len(await hits(world, a)) == 1  # the open-hit index: never two


async def test_req_prb_068_ac2_a_handled_set_opens_again_only_for_new_incidents(
    world: World,
) -> None:
    a = world.a
    category = await a_category(world, a)
    await incidents(world, a, 10, category_id=category, site_id=str(a.s2))
    assert await evaluate(world, a) == 1
    [hit] = await hits(world, a)
    await world.sql(
        "UPDATE problem_repeat_hits SET handled_at = now(), outcome = 'dismissed'"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        hit["id"],
    )
    # Handled: the same incidents never open it again (AC2) ...
    assert await evaluate(world, a) == 0
    # ... only enough new ones do.
    await incidents(world, a, 10, category_id=category, site_id=str(a.s2))
    assert await evaluate(world, a) == 1
    assert len(await hits(world, a)) == 2


async def test_d140_5_essentials_has_no_repeat_alerts(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-140 item 5: not in Essentials (no problem module): the schedule skips the tenant."""
    a = world.a
    category = await a_category(world, a)
    await incidents(world, a, 10, category_id=category, site_id=str(a.s1))

    async def no_problems(tenant_id: uuid.UUID, feature: object) -> bool:
        del tenant_id
        return str(feature) != repeat_rules.FEATURE

    monkeypatch.setattr(licensing, "has_feature", no_problems)
    assert await evaluate(world, a) == 0
    assert await hits(world, a) == []


async def test_req_prb_068_admins_manage_rules_the_default_is_only_switched_off(
    world: World,
) -> None:
    a = world.a
    rules = await world.call("GET", f"{API}/rules", a, a.admin)
    assert rules.status_code == 200, rules.text
    [default] = [r for r in rules.json() if r["is_default"]]
    assert (
        default["match"],
        default["threshold"],
        default["window_hours"],
        default["enabled"],
    ) == (
        "category_site",
        10,
        24,
        True,
    )
    made = await world.call(
        "POST",
        f"{API}/rules",
        a,
        a.admin,
        json={"name": "Printers", "match": "category", "threshold": 5, "window_hours": 168},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    removed = await world.call(
        "DELETE",
        f"{API}/rules/{default['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{default["version"]}"', **CONSOLE},
    )
    assert field_codes(removed) == {"id": "default_cannot_be_removed"}
    off = await world.call(
        "PATCH",
        f"{API}/rules/{default['id']}",
        a,
        a.admin,
        json={"enabled": False},
        headers={"If-Match": f'"{default["version"]}"', **CONSOLE},
    )
    assert off.status_code == 200, off.text
    # Technicians do not manage rules; another tenant never sees these.
    assert problem(await world.call("GET", f"{API}/rules", a, a.tech_a))[0] == 403
    other = (await world.call("GET", f"{API}/rules", world.b, world.b.admin)).json()
    assert made.json()["id"] not in {r["id"] for r in other}


async def test_d140_5_the_server_refuses_repeat_rules_without_the_problem_module(
    world: World,
) -> None:
    """Essentials has incidents but no problems: the API says so (the console shows a hint)."""
    essentials = await create_tenant(world.db.migrator_url, "Essentials", edition="essentials")
    (admin,) = await seed_users(world.db, essentials, [{"user_type": "technician"}])
    await assign_system_role(world.db.admin_url, essentials, admin, "tenant_admin")
    org = Org(essentials, admin, admin, admin, admin, admin, admin, admin)
    for path in (f"{API}/rules", f"{API}/hits"):
        assert problem(await world.call("GET", path, org, admin)) == (403, "entitlement_required")


async def test_req_prb_068_a_set_is_listed_and_dismissed_by_who_may_create_problems(
    world: World,
) -> None:
    a = world.a
    category = await a_category(world, a)
    await incidents(world, a, 10, category_id=category, site_id=str(a.s1))
    assert await evaluate(world, a) == 1
    [hit] = (await world.call("GET", f"{API}/hits", a, a.tech_a)).json()
    assert hit["incident_count"] == 10
    members = await world.call("GET", f"{API}/hits/{hit['id']}/incidents", a, a.tech_a)
    assert members.status_code == 200, members.text
    assert 0 < len(members.json()) <= 10  # only those tech_a may see (their own scope)
    dismissed = await world.call(
        "POST",
        f"{API}/hits/{hit['id']}/handle",
        a,
        a.tech_a,
        json={"outcome": "dismissed"},
        headers={"If-Match": f'"{hit["version"]}"', **CONSOLE},
    )
    assert dismissed.status_code == 200, dismissed.text
    assert (await world.call("GET", f"{API}/hits", a, a.tech_a)).json() == []
    # Requesters never reach them.
    assert problem(await world.call("GET", f"{API}/hits", a, a.requester))[0] == 403
