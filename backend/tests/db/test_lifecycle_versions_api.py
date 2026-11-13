"""Life cycle versions over HTTP (ADR-049 §2, §6; WP-046a S4, REQ-INC-049 AC1-AC3).

An administrator starts a draft (a copy of the latest published version), changes its moves,
sees each problem by name, publishes it, and new incidents start on it while older ones keep
theirs. Published versions never change; one draft at a time; the last published version cannot
be retired; a technician may do none of it.
"""

import uuid
from typing import Any

from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import World, problem, states

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

BASE = "/incidents/settings/lifecycles/standard"


async def _etag(world: World) -> str:
    listed = await world.call("GET", f"{BASE}/versions", world.a, world.a.admin)
    assert listed.status_code == 200, listed.text
    return listed.headers["ETag"]


async def _start(world: World) -> tuple[int, list[dict[str, Any]]]:
    """A draft: its number and its moves (as copied)."""
    started = await world.call(
        "POST", f"{BASE}/versions", world.a, world.a.admin, headers={"If-Match": await _etag(world)}
    )
    assert started.status_code == 201, started.text
    number = started.json()["number"]
    moves = await world.call("GET", f"{BASE}/versions/{number}/moves", world.a, world.a.admin)
    assert moves.status_code == 200, moves.text
    return number, moves.json()


async def _save(world: World, moves: list[dict[str, Any]]) -> dict[str, Any]:
    saved = await world.call(
        "PUT",
        f"{BASE}/draft/moves",
        world.a,
        world.a.admin,
        json={"moves": moves},
        headers={"If-Match": await _etag(world)},
    )
    assert saved.status_code == 200, saved.text
    return dict(saved.json())


async def _publish(world: World) -> Any:  # noqa: ANN401 - the response
    return await world.call(
        "POST",
        f"{BASE}/draft/publish",
        world.a,
        world.a.admin,
        headers={"If-Match": await _etag(world)},
    )


async def _discard(world: World) -> None:
    gone = await world.call(
        "DELETE", f"{BASE}/draft", world.a, world.a.admin, headers={"If-Match": await _etag(world)}
    )
    assert gone.status_code == 204, gone.text


async def test_ac1_a_draft_names_the_status_it_strands_and_does_not_publish(world: World) -> None:
    await world.create(world.a, world.a.admin)  # the type is seeded
    number, moves = await _start(world)
    assert number >= 2  # version 1 is the shipped one
    stranded = [m for m in moves if m["from_status"] != "awaiting_requester"]
    saved = await _save(world, stranded)
    assert {"code": "status_no_way_out", "params": {"status": "awaiting_requester"}} in saved[
        "problems"
    ]
    refused = await _publish(world)
    assert problem(refused) == (422, "lifecycle_version_has_problems")
    # One draft at a time.
    again = await world.call(
        "POST", f"{BASE}/versions", world.a, world.a.admin, headers={"If-Match": await _etag(world)}
    )
    assert problem(again) == (409, "lifecycle_draft_exists")
    await _discard(world)


async def test_ac2_ac3_publishing_changes_new_records_only(world: World) -> None:
    a = world.a
    before = await world.create(a, a.admin, subject=f"Before {uuid.uuid4().hex[:6]}")
    _number, moves = await _start(world)
    # The new version: "start work" from new needs the close right too, and a category.
    changed = [
        {**m, "permission": "incidents.close", "required_fields": ["category_id"]}
        if (m["from_status"], m["action"]) == ("new", "start_work")
        else m
        for m in moves
    ]
    saved = await _save(world, changed)
    assert saved["problems"] == []
    published = await _publish(world)
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["latest_published"] == saved["number"]
    states_of = {v["number"]: v["state"] for v in body["items"]}
    assert states_of[saved["number"]] == "published"
    # Its moves never change again: there is no draft to save into.
    no_draft = await world.call(
        "PUT",
        f"{BASE}/draft/moves",
        a,
        a.admin,
        json={"moves": changed},
        headers={"If-Match": await _etag(world)},
    )
    assert problem(no_draft) == (404, "lifecycle_draft_not_found")
    after = await world.create(a, a.admin, subject=f"After {uuid.uuid4().hex[:6]}")
    assert states(await world.fresh(a, before))["start_work"] is None  # its version: unchanged
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        on = await session.execute(
            text("SELECT id::text, lifecycle_version FROM work_items WHERE id IN (:x, :y)"),
            {"x": uuid.UUID(before["id"]), "y": uuid.UUID(after["id"])},
        )
        versions = dict(on.tuples().all())
    assert versions[after["id"]] == saved["number"]
    assert versions[before["id"]] < saved["number"]


async def test_a_right_beyond_the_type_or_an_unknown_field_is_a_problem(world: World) -> None:
    await world.create(world.a, world.a.admin)
    _number, moves = await _start(world)
    bad = [
        {**m, "permission": "roles.manage", "required_fields": ["shoe_size"]}
        if (m["from_status"], m["action"]) == ("new", "start_work")
        else m
        for m in moves
    ]
    saved = await _save(world, bad)
    assert {"code": "permission_not_allowed", "params": {"permission": "roles.manage"}} in saved[
        "problems"
    ]
    assert {"code": "required_field_unknown", "params": {"field": "shoe_size"}} in saved["problems"]
    await _discard(world)


async def test_the_last_published_version_cannot_be_retired(world: World) -> None:
    await world.create(world.a, world.a.admin)
    listed = await world.call("GET", f"{BASE}/versions", world.a, world.a.admin)
    latest = listed.json()["latest_published"]
    refused = await world.call(
        "POST",
        f"{BASE}/versions/{latest}/retire",
        world.a,
        world.a.admin,
        headers={"If-Match": listed.headers["ETag"]},
    )
    assert problem(refused) == (409, "lifecycle_version_last_published")


async def test_a_stale_if_match_is_a_conflict_and_a_technician_may_not(world: World) -> None:
    a = world.a
    await world.create(a, a.admin)
    stale = await world.call("POST", f"{BASE}/versions", a, a.admin, headers={"If-Match": '"0"'})
    assert stale.status_code == 409, stale.text
    for method, path in (
        ("GET", f"{BASE}/versions"),
        ("POST", f"{BASE}/versions"),
        ("POST", f"{BASE}/draft/publish"),
    ):
        refused = await world.call(
            method, path, a, a.tech_a, headers={"If-Match": await _etag(world)}
        )
        assert refused.status_code == 403, (method, path, refused.text)


async def test_tenant_b_never_sees_tenant_a_s_draft(world: World) -> None:
    a, b = world.a, world.b
    await world.create(a, a.admin)
    await world.create(b, b.admin)
    number, _moves = await _start(world)
    theirs = await world.call("GET", f"{BASE}/versions/{number}/moves", b, b.admin)
    assert problem(theirs) == (404, "lifecycle_version_not_found")
    await _discard(world)
