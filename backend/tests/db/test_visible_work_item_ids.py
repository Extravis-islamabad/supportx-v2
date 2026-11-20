"""Work items' `visible_work_item_ids` for the assets port (lane A's conditions, 2026-11-20).

Each type goes through its own staff view filter; trashed, other tenants', unknown and hidden IDs
are all simply absent; more than the cap is a programming error. Staff views only.
Real PostgreSQL and Valkey on the incident world; every record is new (rule 5h).
"""

import uuid

import pytest

from app.core.tenancy import TenantContext
from app.modules.assets import VISIBLE_IDS_MAX
from app.modules.work_items.service.asset_link_port import PORT
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_relationships import _given
from tests.db.test_incidents_api import World
from tests.db.test_problems_api import new_problem

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def _visible(world: World, user: uuid.UUID, ids: list[uuid.UUID]) -> frozenset[uuid.UUID]:
    a = world.a
    subject = await world.app.state.policy.subject(a.tenant, user)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        return await PORT.visible_work_item_ids(session, subject, ids)


async def test_each_id_is_judged_by_its_own_types_view(world: World) -> None:
    a, b = world.a, world.b
    tag = uuid.uuid4().hex[:6]
    # tech_a: a built-in technician, member of group GA only (the incident world).
    mine = await world.create(a, a.admin, group_id=str(a.ga), subject=f"Seen {tag}")
    theirs = await world.create(a, a.admin, group_id=str(a.gb), subject=f"Other group {tag}")
    trashed = await world.create(a, a.admin, group_id=str(a.ga), subject=f"Trashed {tag}")
    await world.sql(
        "UPDATE work_items SET deleted_at = now() WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(trashed["id"]),
    )
    elsewhere = await world.create(b, b.admin, subject=f"Tenant B {tag}")
    unknown = uuid.uuid4()
    ids = [uuid.UUID(x["id"]) for x in (mine, theirs, trashed, elsewhere)] + [unknown]
    assert await _visible(world, a.tech_a, ids) == {uuid.UUID(mine["id"])}


async def test_one_types_view_never_stands_for_anothers(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    incident = await world.create(a, a.admin, group_id=str(a.ga), subject=f"Incident {tag}")
    # A real problem, made through its own API: a viewer with incidents.view only must not see it.
    made = await new_problem(world, a, a.admin, group_id=str(a.ga), subject=f"Problem {tag}")
    assert made.status_code == 201, made.text
    problem = made.json()
    await _given(world, a, a.requester2, f"Incident viewer {tag}", [("incidents.view", "all")])
    seen = await _visible(
        world, a.requester2, [uuid.UUID(incident["id"]), uuid.UUID(problem["id"])]
    )
    assert uuid.UUID(incident["id"]) in seen
    assert uuid.UUID(problem["id"]) not in seen


async def test_more_than_the_cap_is_a_programming_error(world: World) -> None:
    a = world.a
    with pytest.raises(ValueError, match="at most"):
        await _visible(world, a.admin, [uuid.uuid4() for _ in range(VISIBLE_IDS_MAX + 1)])
    assert await _visible(world, a.admin, []) == frozenset()
