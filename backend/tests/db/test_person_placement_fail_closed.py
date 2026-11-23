"""`person_placement` fails closed for an ID with no visible row (the #582 follow-up).

Lane B's #582 review found that an ID nobody holds in this tenant (a random ID, or another
tenant's user, which RLS hides) read as active and able to sign in. A caller that trusted it
could treat a stranger as a live person. It now reads as nobody: not active, no sign-in, no
site, department or manager. Real people read exactly as before.
"""

import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.identity_access import person_placement
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, World, problem
from tests.db.test_service_requests_api import SR, an_item, raise_request

pytestmark = MODULE_LOOP
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used


async def _scope(world: World, scope: str) -> None:
    a = world.a
    current = await world.call("GET", f"{SR}/settings", a, a.admin)
    assert current.status_code == 200, current.text
    changed = await world.call(
        "PATCH",
        f"{SR}/settings",
        a,
        a.admin,
        json={"on_behalf_scope": scope},
        headers={"If-Match": f'"{current.json()["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text


async def test_an_id_nobody_holds_here_is_nobody(world: World) -> None:
    a, b = world.a, world.b
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        for stranger in (uuid.uuid4(), b.tech_a, None):  # random, tenant B's real user, no one
            placed = await person_placement(session, stranger)
            assert (placed.active, placed.can_sign_in) == (False, False), stranger
            assert (placed.site_id, placed.department_id, placed.manager_id) == (None, None, None)
        real = await person_placement(session, a.tech_a)
        assert (real.active, real.can_sign_in) == (True, True)  # unchanged for real people


async def test_raising_for_someone_nobody_holds_here_is_refused_not_a_server_error(
    world: World,
) -> None:
    """With the widest on-behalf scope (anyone), a stranger read as "active" and passed the scope
    check, to be refused only by a later field check (422). Now the scope refuses it, as for a
    deactivated person (checked without the fix: this test then fails with that 422).
    """
    a, b = world.a, world.b
    await _scope(world, "all_users")  # through the API, so the cached settings follow
    try:
        item = await an_item(world, a)

        async def for_whom(person: uuid.UUID) -> Any:  # noqa: ANN401 - the response
            return await raise_request(
                world,
                a,
                a.requester,
                catalog_item_id=item["id"],
                answers={"model": "air"},
                on_behalf_of_id=str(person),
            )

        for stranger in (uuid.uuid4(), b.requester):
            refused = await for_whom(stranger)
            assert problem(refused) == (403, "on_behalf_out_of_scope"), refused.text
            assert str(stranger) not in refused.text
        allowed = await for_whom(a.requester2)  # a real colleague, as before
        assert allowed.status_code == 201, allowed.text
    finally:
        await _scope(world, "same_department")  # the default, for the module's other tests
