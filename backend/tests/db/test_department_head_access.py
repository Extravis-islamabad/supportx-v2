"""A department's head sees its requests in the portal by default (D-152).

The right is computed from `departments.head_id` when permissions are compiled: a new head has it
at once, a replaced head loses it. Anyone else gets it through the built-in Department viewer
role, whose grant and removal are audited like any role.
"""

import uuid

import pytest

from tests.db.test_incidents_api import Org, World, world
from tests.db.test_portal_incidents_api import ids, mine

pytestmark = pytest.mark.db
__all__ = ["world"]  # the fixture, used by name


async def _department(world: World, org: Org, name: str) -> dict[str, object]:
    made = await world.call(
        "POST", "/organization/departments", org, org.admin, json={"name": name}
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _head(
    world: World, org: Org, department: dict[str, object], head: uuid.UUID | None
) -> dict[str, object]:
    changed = await world.call(
        "PATCH",
        f"/organization/departments/{department['id']}",
        org,
        org.admin,
        json={"head_id": None if head is None else str(head)},
        headers={"If-Match": f'"{department["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    return dict(changed.json())


async def test_the_head_sees_the_departments_requests_and_loses_them_when_replaced(
    world: World,
) -> None:
    a = world.a
    finance = await _department(world, a, f"Finance {uuid.uuid4().hex[:6]}")
    await world.sql(
        "UPDATE users SET department_id = $1 WHERE id = ANY($2::uuid[])",
        uuid.UUID(str(finance["id"])),
        [a.requester, a.requester2],
    )
    colleague = await world.create(
        a, a.admin, requester_id=str(a.requester2), department_id=str(finance["id"])
    )
    assert colleague["id"] not in ids(await mine(world, a, a.requester))  # not the head yet
    finance = await _head(world, a, finance, a.requester)
    assert colleague["id"] in ids(await mine(world, a, a.requester))  # at once
    finance = await _head(world, a, finance, a.requester2)
    assert colleague["id"] not in ids(await mine(world, a, a.requester))  # replaced: gone


async def test_an_admin_grants_the_department_viewer_role_and_it_is_audited(
    world: World,
) -> None:
    a = world.a
    sales = await _department(world, a, f"Sales {uuid.uuid4().hex[:6]}")
    await world.sql(
        "UPDATE users SET department_id = $1 WHERE id = ANY($2::uuid[])",
        uuid.UUID(str(sales["id"])),
        [a.requester, a.requester2],
    )
    colleague = await world.create(
        a, a.admin, requester_id=str(a.requester2), department_id=str(sales["id"])
    )
    roles = (await world.call("GET", "/roles", a, a.admin)).json()
    (viewer,) = [r["id"] for r in roles if r["key"] == "department_viewer"]
    granted = await world.call("PUT", f"/users/{a.requester}/roles/{viewer}", a, a.admin)
    assert granted.status_code in {200, 204}, granted.text
    assert colleague["id"] in ids(await mine(world, a, a.requester))
    removed = await world.call("DELETE", f"/users/{a.requester}/roles/{viewer}", a, a.admin)
    assert removed.status_code in {200, 204}, removed.text
    assert colleague["id"] not in ids(await mine(world, a, a.requester))
    audit = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1 AND action IN"
        " ('user.role_assigned', 'user.role_removed') AND object_id = $2",
        a.tenant,
        str(a.requester),
    )
    assert sorted(r["action"] for r in audit) == ["user.role_assigned", "user.role_removed"]
