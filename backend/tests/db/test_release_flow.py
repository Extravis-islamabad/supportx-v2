"""A Standard release from request to Closed, as an administrator does it (QA10-P4-29, FLOW-5).

Chrome QA found every Standard release stuck at Planning > Waiting for approval on a tenant whose
release settings were first made before roles and stage approvals existed: no approval was
raised, the Roles tab was empty, and only Cancel was left. The walk runs twice: on a fresh tenant,
and on one whose release settings look like that older seed (no role definitions, no stage
approvals), which the catalogue now tops up once.
"""

from typing import Any

import asyncpg
import pytest

from tests.db.test_incidents_api import CONSOLE, Org, World, world
from tests.db.test_release_approvals_api import approvals, current, decide
from tests.db.test_release_parts_api import put_role
from tests.db.test_releases_api import REL, a_release, moved

pytestmark = pytest.mark.db

__all__ = ["world"]  # the fixture, re-used


async def _moved_with(
    world: World,
    org: Org,
    item: dict[str, Any],
    to: str,
    **fields: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    """A move with what it asks for (a resolution, a closure code)."""
    response = await world.call(
        "POST",
        f"{REL}/{item['id']}/moves",
        org,
        org.admin,
        json={"to_status": to, **fields},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _approve_stage(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    """The stage's open approval, decided by the administrator (named, or routed to them)."""
    rows = [r for r in await approvals(world, org, item) if r["state"] == "pending"]
    assert rows, "an approval is raised"
    for row in rows:
        decided = await decide(world, org, item, row, org.admin)
        assert decided.status_code == 200, decided.text
    return await current(world, org, item)


async def _walk(world: World, org: Org) -> None:
    item = await a_release(world, org)
    roles = await world.call("GET", f"{REL}/{item['id']}/roles", org, org.admin)
    assert roles.status_code == 200, roles.text
    codes = {r["code"] for r in roles.json()["roles"]}
    assert {"release_manager", "uat_owner"} <= codes  # the Roles tab has its roles
    held = await put_role(world, org, item, "release_manager", users=[org.admin])
    assert held.status_code == 200, held.text
    held = await put_role(world, org, {**item, "version": held.json()["version"]}, "uat_owner",
                          users=[org.admin])  # fmt: skip
    assert held.status_code == 200, held.text
    item = await current(world, org, item)

    item = await moved(world, org, item, "submission_accepted")
    assert item["status"] == "planning_in_planning"
    item = await moved(world, org, item, "planning_waiting_approval")
    item = await _approve_stage(world, org, item)
    assert item["status"] == "build_in_progress"
    item = await moved(world, org, item, "build_completed")
    assert item["status"] == "testing_in_progress"
    item = await moved(world, org, item, "testing_passed")
    assert item["status"] == "acceptance_in_progress"
    item = await _approve_stage(world, org, item)
    assert item["status"] == "deployment_scheduled"
    item = await moved(world, org, item, "deployment_in_progress")
    item = await _moved_with(
        world, org, item, "deployment_deployed", resolution="Deployed to production."
    )
    assert item["status"] == "training_in_progress"
    item = await _moved_with(world, org, item, "training_completed", resolution="Trained.")
    assert item["status"] == "review_in_progress"
    # Completing the review closes the release: it asks for the closure code too.
    item = await _moved_with(
        world, org, item, "review_completed", resolution="Reviewed.", closure_code="fixed"
    )
    if item["status"] != "closure_closed":
        item = await _moved_with(world, org, item, "closure_closed", closure_code="fixed")
    assert (item["status"], item["status_category"]) == ("closure_closed", "closed")


async def test_a_standard_release_walks_from_request_to_closed(world: World) -> None:
    await _walk(world, world.a)


async def test_an_older_release_seed_is_topped_up_and_walks_too(world: World) -> None:
    a = world.a
    await a_release(world, a)  # seeds the release settings
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        # What a tenant seeded before roles and stage approvals looks like.
        await conn.execute(
            "DELETE FROM work_item_role_defs WHERE tenant_id = $1 AND type = 'release'", a.tenant
        )
        await conn.execute(
            "UPDATE work_item_stages SET approvals = NULL"
            " WHERE tenant_id = $1 AND type = 'release'",
            a.tenant,
        )
        await conn.execute(
            "UPDATE work_item_type_settings SET seed_version = 3"
            " WHERE tenant_id = $1 AND type = 'release'",
            a.tenant,
        )
    finally:
        await conn.close()
    await _walk(world, a)
