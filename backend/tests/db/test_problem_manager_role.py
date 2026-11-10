"""The built-in problem manager role (WP-044c D14, Appendix A)."""

import uuid

import asyncpg

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, World, problem
from tests.db.test_problems_api import PRB, new_problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

ROOT_CAUSE = "<p>The relay's queue fills at nine.</p>"


async def test_the_problem_manager_works_every_problem_and_reads_incidents(world: World) -> None:
    a = world.a
    roles = (await world.call("GET", "/roles", a, a.admin)).json()
    rows = roles["items"] if isinstance(roles, dict) else roles
    manager = next(r for r in rows if r.get("key") == "problem_manager")
    assert manager["is_system"] is True
    granted = await world.call("PUT", f"/users/{a.requester2}/roles/{manager['id']}", a, a.admin)
    assert granted.status_code in {200, 204}, granted.text
    # Another group's problem, with a root cause: the manager reads and works it all.
    record = (
        await new_problem(world, a, a.admin, group_id=str(a.gb), root_cause=ROOT_CAUSE)
    ).json()
    seen = await world.call("GET", f"{PRB}/{record['id']}", a, a.requester2)
    assert seen.status_code == 200, seen.text
    assert seen.json()["root_cause"] == ROOT_CAUSE
    changed = await world.call(
        "PATCH",
        f"{PRB}/{record['id']}",
        a,
        a.requester2,
        json={"subject": "Mail relay drops messages every morning"},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    gone = await world.call(
        "DELETE",
        f"{PRB}/{record['id']}",
        a,
        a.requester2,
        headers={"If-Match": f'"{changed.json()["version"]}"', **CONSOLE},
    )
    assert gone.status_code in {200, 204}, gone.text
    # ... and the incidents problems are about.
    assert (await world.call("GET", "/incidents", a, a.requester2)).status_code == 200
    # Another tenant's admin never sees this tenant's role holders' work (RLS).
    assert (
        problem(await world.call("GET", f"{PRB}/{record['id']}", world.b, world.b.admin))[0] == 404
    )


async def _problem_manager_rows(url: str, tenant: uuid.UUID, *, drop: bool = False) -> int:
    """The tenant's problem_manager role rows; `drop` first removes them (a tenant from before)."""
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            if drop:
                await conn.execute("DELETE FROM roles WHERE key = 'problem_manager'")
            found: int = await conn.fetchval(
                "SELECT count(*) FROM roles WHERE key = 'problem_manager' AND deleted_at IS NULL"
            )
    finally:
        await conn.close()
    return found


async def test_an_existing_tenant_gets_the_role_exactly_once(world: World) -> None:
    """No data migration: ensure_system_roles adds it on the next listing, once (D14)."""
    a = world.a
    assert (await world.call("GET", "/roles", a, a.admin)).status_code == 200
    # A tenant whose system roles were made before problem_manager existed.
    assert await _problem_manager_rows(world.db.migrator_url, a.tenant, drop=True) == 0
    for _ in range(2):
        assert (await world.call("GET", "/roles", a, a.admin)).status_code == 200
    assert await _problem_manager_rows(world.db.migrator_url, a.tenant) == 1
