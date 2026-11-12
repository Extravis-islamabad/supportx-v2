"""A release's closure rule "review completed" (WP-058b S4; REQ-REL-051 AC1).

- Only a release's close rule may list it: never its resolve rule, never another type's.
- Listed, closing a release whose review is not completed is refused, and the problem names
  the review; completing the review in the move that closes the release passes.
- An emergency release always needs its review, whatever the rules list.
"""

import uuid
from typing import Any

import asyncpg

from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import closing
from tests.db.test_incidents_api import CONSOLE, Org, World, world
from tests.db.test_release_parts_api import settings_version
from tests.db.test_releases_api import REL, a_release

__all__ = ["world"]  # the fixture, re-used

INC = "/incidents"


async def _rules(world: World, org: Org, base: str, **body: Any) -> Any:  # noqa: ANN401 - JSON
    version = int((await world.call("GET", f"{base}/settings", org, org.admin)).json()["version"])
    return await world.call(
        "PATCH",
        f"{base}/settings/closure",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{version}"', **CONSOLE},
    )


async def _at(world: World, item: dict[str, Any], status: str, stage: str) -> dict[str, Any]:
    """The release put at `status` directly (the walk there is test_release_flow's)."""
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute(
            "UPDATE work_items SET status = $3::text, stage = $4::text,"
            " status_category = CASE WHEN $3::text LIKE 'review%' THEN 'resolved' ELSE 'open' END,"
            " version = version + 1 WHERE tenant_id = $1 AND id = $2",
            world.a.tenant,
            uuid.UUID(str(item["id"])),
            status,
            stage,
        )
    finally:
        await conn.close()
    got = await world.call("GET", f"{REL}/{item['id']}", world.a, world.a.admin)
    assert got.status_code == 200, got.text
    return dict(got.json())


async def _move(world: World, item: dict[str, Any], to: str) -> Any:  # noqa: ANN401 - response
    return await world.call(
        "POST",
        f"{REL}/{item['id']}/moves",
        world.a,
        world.a.admin,
        json={"to_status": to, "resolution": "Done.", "closure_code": "completed"},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )


async def test_only_a_release_close_rule_may_list_the_review(world: World) -> None:
    a = world.a
    ok = await _rules(world, a, REL, close_requires=["closure_code", "review_completed"])
    assert ok.status_code == 200, ok.text
    assert ok.json()["closure"]["close_requires"] == ["closure_code", "review_completed"]
    resolve = await _rules(world, a, REL, resolve_requires=["review_completed"])
    assert resolve.status_code == 422, resolve.text
    incident = await _rules(world, a, INC, close_requires=["review_completed"])
    assert incident.status_code == 422, incident.text
    assert await settings_version(world, a) == ok.json()["version"]


async def test_req_rel_051_ac1_closing_before_the_review_is_refused_and_says_so(
    world: World,
) -> None:
    a = world.a
    listed = await _rules(world, a, REL, close_requires=["closure_code", "review_completed"])
    assert listed.status_code == 200, listed.text
    # A rolled-back release on the default path may close straight away, but not without review.
    item = await _at(world, await a_release(world, a), "deployment_rolled_back", "deployment")
    refused = await _move(world, item, "closure_closed")
    assert refused.status_code == 422, refused.text
    errors = refused.json()["errors"]
    assert [(e["field"], e["code"]) for e in errors] == [
        ("body.review_completed", "review_required_to_close")
    ]
    assert errors[0]["message_key"] == "errors.field.review_required_to_close"

    # Completing the review closes the release in the same move: that passes.
    reviewing = await _at(world, await a_release(world, a), "review_in_progress", "review")
    closed = await _move(world, reviewing, "review_completed")
    assert closed.status_code == 200, closed.text
    assert closed.json()["status_category"] == "closed"

    # Without the rule, the rolled-back release closes.
    off = await _rules(world, a, REL, close_requires=["closure_code"])
    assert off.status_code == 200, off.text
    item = (await world.call("GET", f"{REL}/{item['id']}", a, a.admin)).json()
    assert (await _move(world, item, "closure_closed")).status_code == 200


def test_an_emergency_release_always_needs_its_review() -> None:
    def release(status: str, path: str) -> WorkItem:
        return WorkItem(type="release", status=status, stage_path=path)

    none = closing.MoveInput()
    assert closing.review_open(release("training_completed", "emergency"), none, [])
    assert not closing.review_open(release("training_completed", "default"), none, [])
    listed = ["review_completed"]
    assert closing.review_open(release("training_completed", "default"), none, listed)
    through = closing.MoveInput(passes_through="review_completed")
    assert not closing.review_open(release("review_in_progress", "emergency"), through, [])
    # Another type never has it.
    assert not closing.review_open(
        WorkItem(type="change", status="x", stage_path="emergency"), none, listed
    )
