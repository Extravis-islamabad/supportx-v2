"""QA round 6 (2026-11-06), service requests: each test is named after its bug ID.

QA6-SR-01: a request nobody but its requester could approve sat waiting for ever. The approval
now says so (route reason `no_holder`) instead of waiting silently.
QA6-SR-03: your own request was offered in "Approvals waiting for you", then refused on click.
It is no longer offered.
"""

from typing import Any

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World
from tests.db.test_service_requests_api import SR, an_item, raise_request

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

NEEDS_MANAGER = {"approvers": [{"kind": "requested_for_manager"}]}


async def _approvals(world: World, org: Any, user: Any, record: dict[str, Any]) -> list[Any]:  # noqa: ANN401
    found = await world.call("GET", f"{SR}/{record['id']}/approvals", org, user)
    assert found.status_code == 200, found.text
    return list(found.json()["items"])


async def _inbox(world: World, org: Any, user: Any) -> set[str]:  # noqa: ANN401
    found = await world.call("GET", f"{SR}/my-approvals", org, user)
    assert found.status_code == 200, found.text
    return {p["record_id"] for p in found.json()["items"]}


async def test_qa6_sr_01_an_approval_nobody_else_can_decide_says_so(world: World) -> None:
    a = world.a
    item = await an_item(world, a, approval=NEEDS_MANAGER)
    # The admin (the tenant's only approval administrator) asks for themselves, with no manager.
    made = await raise_request(
        world, a, a.admin, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    record = made.json()
    rows = await _approvals(world, a, a.admin, record)
    assert [(r["origin"], r["route_reason"]) for r in rows] == [("administrators", "no_holder")]
    assert rows[0]["can_decide"] is False


async def test_qa6_sr_03_your_own_request_is_not_in_your_approvals(world: World) -> None:
    a = world.a
    item = await an_item(world, a, approval=NEEDS_MANAGER)
    own = (
        await raise_request(world, a, a.admin, catalog_item_id=item["id"], answers={"model": "air"})
    ).json()
    theirs = (
        await raise_request(
            world, a, a.requester, catalog_item_id=item["id"], answers={"model": "pro"}
        )
    ).json()
    inbox = await _inbox(world, a, a.admin)
    assert theirs["id"] in inbox  # the administrators' entry for someone else's request
    assert own["id"] not in inbox  # never offered to its own requester
    rows = await _approvals(world, a, a.admin, theirs)
    assert [(r["origin"], r["route_reason"]) for r in rows] == [("administrators", "no_manager")]
