"""Problem notifications on the engine (WP-044c D15, Appendix A file 04)."""

import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World
from tests.db.test_notifications_api import run_engine
from tests.db.test_problems_api import PRB, new_problem

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def told(world: World, org: Org, record_id: str) -> set[tuple[str, uuid.UUID]]:
    rows = await world.sql(
        "SELECT event_code, user_id FROM notification_deliveries"
        " WHERE tenant_id = $1 AND record_id = $2",
        org.tenant,
        uuid.UUID(record_id),
    )
    return {(r["event_code"], r["user_id"]) for r in rows}


async def test_d15_the_owner_hears_of_the_assignment(world: World) -> None:
    a = world.a
    made = await new_problem(world, a, a.admin, group_id=str(a.ga))
    record: dict[str, Any] = made.json()
    assigned = await world.call(
        "POST",
        f"{PRB}/{record['id']}/assign",
        a,
        a.admin,
        json={"group_id": str(a.ga), "technician_id": str(a.tech_c)},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert assigned.status_code == 200, assigned.text
    await run_engine(world, a)
    assert ("problem.assigned", a.tech_c) in await told(world, a, record["id"])


async def test_d15_a_known_error_reaches_the_linked_incidents_technicians(world: World) -> None:
    a = world.a
    incident = await world.create(a, a.admin, group_id=str(a.gb), technician_id=str(a.tech_b))
    record = (
        await new_problem(world, a, a.admin, group_id=str(a.ga), workaround="<p>Restart it.</p>")
    ).json()
    linked = await world.call(
        "POST",
        f"{PRB}/{record['id']}/incidents",
        a,
        a.admin,
        json={"incident_id": incident["id"], "move": False},
        headers=CONSOLE,
    )
    assert linked.status_code in {200, 201}, linked.text
    fresh = (await world.call("GET", f"{PRB}/{record['id']}", a, a.admin)).json()
    marked = await world.call(
        "POST",
        f"{PRB}/{record['id']}/known-error",
        a,
        a.admin,
        json={},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert marked.status_code == 200, marked.text
    await run_engine(world, a)
    assert ("problem.known_error", a.tech_b) in await told(world, a, record["id"])
    # Problems are staff records: the incident's requester is never told of the problem.
    assert all(user != a.requester for _, user in await told(world, a, record["id"]))


async def test_d16_a_new_set_of_repeated_incidents_tells_their_group(world: World) -> None:
    from tests.db.test_repeat_rules import a_category, evaluate, incidents  # noqa: PLC0415 - helpers

    a = world.a
    category = await a_category(world, a)
    await incidents(world, a, 10, category_id=category, site_id=str(a.s1), group_id=str(a.ga))
    assert await evaluate(world, a) == 1
    await run_engine(world, a)
    rows = await world.sql(
        "SELECT user_id FROM notification_deliveries"
        " WHERE tenant_id = $1 AND event_code = 'problem_repeat.detected'",
        a.tenant,
    )
    told = {r["user_id"] for r in rows}
    assert {a.tech_a, a.tech_c} <= told  # GA's members
    assert a.requester not in told
