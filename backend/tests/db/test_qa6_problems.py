"""QA6 (2026-11-06) problem fixes, each test named after its bug."""

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World
from tests.db.test_problems_api import new_problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def test_qa6_prb_03_whoever_opens_a_problem_owns_it(world: World) -> None:
    a = world.a
    made = await new_problem(world, a, a.tech_a, group_id=str(a.ga))
    assert made.status_code == 201, made.text
    assert made.json()["technician_id"] == str(a.tech_a)
    # Not in the problem's group: left for the group to take, never refused.
    outside = await new_problem(world, a, a.tech_a, group_id=str(a.gb))
    assert outside.status_code == 201, outside.text
    assert outside.json()["technician_id"] is None
    # A technician named on create is kept; "nobody" stays nobody.
    named = await new_problem(world, a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_c))
    assert named.json()["technician_id"] == str(a.tech_c)
    nobody = await new_problem(world, a, a.tech_a, group_id=str(a.ga), technician_id=None)
    assert nobody.json()["technician_id"] is None
