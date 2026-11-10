"""Parent and sub-releases, and the review result (WP-058a s5; REQ-REL-030, -037) over HTTP.

Real PostgreSQL with RLS:
- a release has at most one parent and loops are refused (AC1);
- a parent cannot enter deployment while a sub-release has not passed testing, and the refusal
  names it (AC2);
- the parent lists its sub-releases with their stage;
- both records keep the link in history;
- the review stage records its overall result.
"""

import uuid
from typing import Any

import httpx

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World
from tests.db.test_release_templates_api import field_codes, release_from, templates
from tests.db.test_releases_api import REL, a_release, move

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def set_parent(
    world: World, org: Org, child: dict[str, Any], parent: uuid.UUID | None
) -> httpx.Response:
    return await world.call(
        "PUT",
        f"{REL}/{child['id']}/parent",
        org,
        org.admin,
        json={"parent_id": str(parent) if parent else None},
        headers=CONSOLE,
    )


async def place(
    world: World, org: Org, item: dict[str, Any], stage: str, status: str
) -> dict[str, Any]:
    """Put this test's own release in a stage directly (its own fresh data)."""
    await world.sql(
        "UPDATE work_items SET stage = $2, status = $3, version = version + 1 WHERE id = $1",
        uuid.UUID(item["id"]),
        stage,
        status,
    )
    return dict((await world.call("GET", f"{REL}/{item['id']}", org, org.admin)).json())


async def test_req_rel_037_ac1_one_parent_and_no_loops(world: World) -> None:
    a = world.a
    parent, child = await a_release(world, a), await a_release(world, a)
    made = await set_parent(world, a, child, uuid.UUID(parent["id"]))
    assert made.status_code == 200, made.text
    loop = await set_parent(world, a, parent, uuid.UUID(child["id"]))
    assert field_codes(loop) == {("parent_id", "would_loop")}
    itself = await set_parent(world, a, child, uuid.UUID(child["id"]))
    assert field_codes(itself) == {("parent_id", "would_loop")}
    listed = (await world.call("GET", f"{REL}/{parent['id']}/sub-releases", a, a.admin)).json()
    assert [(s["id"], s["stage"]) for s in listed] == [(child["id"], "submission")]
    for record in (parent, child):  # both histories keep the link
        history = await world.call("GET", f"{REL}/{record['id']}/history", a, a.admin)
        assert history.json()["items"][0]["changes"][0]["field"] == "link"
    other = await a_release(world, a)  # moving it to another parent replaces the link
    assert (await set_parent(world, a, child, uuid.UUID(other["id"]))).status_code == 200
    assert (await world.call("GET", f"{REL}/{parent['id']}/sub-releases", a, a.admin)).json() == []


async def test_req_rel_037_ac2_no_deployment_before_sub_releases_pass_testing(
    world: World,
) -> None:
    a = world.a
    emergency = (await templates(world, a))["emergency"]  # testing leads straight to deployment
    parent = await place(
        world, a, await release_from(world, a, emergency), "testing", "testing_in_progress"
    )
    child = await a_release(world, a)
    await set_parent(world, a, child, uuid.UUID(parent["id"]))
    refused = await move(world, a, parent, "testing_passed")
    assert refused.status_code == 409, refused.text
    params = refused.json()["params"]
    assert params["reason"] == "sub_releases_not_tested"
    assert params["reasons"] == "sub_releases_not_tested"
    await place(world, a, child, "deployment", "deployment_scheduled")  # past testing now
    allowed = await move(
        world, a, await place(world, a, parent, "testing", "testing_in_progress"), "testing_passed"
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["stage"] == "deployment"


async def test_req_rel_030_the_review_records_its_result(world: World) -> None:
    a = world.a
    item = await place(world, a, await a_release(world, a), "review", "review_in_progress")
    schedule = {
        s["stage"]: s
        for s in (await world.call("GET", f"{REL}/{item['id']}/schedule", a, a.admin)).json()
    }

    async def patch(**body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
        return await world.call(
            "PATCH",
            f"{REL}/{item['id']}/schedule/review",
            a,
            a.admin,
            json=body,
            headers={"If-Match": f'"{schedule["review"]["version"]}"', **CONSOLE},
        )

    wrong = await patch(outcome="passed")  # the review takes its own results
    assert field_codes(wrong) == {("outcome", "invalid_choice")}
    saved = await patch(outcome="successful_with_issues", outcome_notes="Two late tickets")
    assert saved.status_code == 200, saved.text
    assert saved.json()["outcome"] == "successful_with_issues"
    sections = [
        s["section"]
        for s in (await world.call("GET", f"{REL}/{item['id']}/plan", a, a.admin)).json()
    ]
    assert {"review_findings", "review_went_well", "review_went_badly"} <= set(sections)
