"""Releases on the stage engine over HTTP (WP-058a s1; ADR-041; REQ-REL-001, -002, -014..017).

Real PostgreSQL with RLS. A release starts in its path's first stage and status; only listed
moves are offered and accepted; reaching a stage's completing status moves on to the next stage
in the same save; approval outcomes are set by the system entry point only; cancel needs a
reason and its own permission; the rail keeps every round; each move writes history and emits
the status event and `stage_changed` through the outbox. The five stage tables are isolated per
tenant.
"""

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.work_items.domain.types import RELEASE
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import work_items as service
from app.shared.events import EventEnvelope
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, role, world

__all__ = ["world"]  # the fixture, re-used

REL = "/releases"


async def new_release(world: World, org: Org, user: uuid.UUID, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "POST",
        REL,
        org,
        user,
        json={"subject": "Payroll 4.2", "requester_id": str(org.requester), **body},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def a_release(world: World, org: Org) -> dict[str, Any]:
    made = await new_release(world, org, org.admin)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def move(
    world: World,
    org: Org,
    item: dict[str, Any],
    to: str,
    *,
    user: uuid.UUID | None = None,
    reason_text: str | None = None,
) -> httpx.Response:
    return await world.call(
        "POST",
        f"{REL}/{item['id']}/moves",
        org,
        user or org.admin,
        json={"to_status": to, **({"reason_text": reason_text} if reason_text else {})},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )


async def moved(
    world: World, org: Org, item: dict[str, Any], to: str, reason_text: str | None = None
) -> dict[str, Any]:
    response = await move(world, org, item, to, reason_text=reason_text)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def panel(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    response = await world.call("GET", f"{REL}/{item['id']}/stages", org, org.admin)
    assert response.status_code == 200, response.text
    return dict(response.json())


def rail(shown: dict[str, Any]) -> dict[str, tuple[str, int]]:
    return {s["stage"]: (s["state"], len(s["entries"])) for s in shown["rail"]}


async def events(world: World, item_id: str, kind: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE aggregate_id = $1 ORDER BY id", item_id
    )
    found = [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]
    return [dict(e.payload) for e in found if e.event_type == kind]


async def test_req_rel_002_ac1_a_release_with_a_title_starts_in_the_first_stage(
    world: World,
) -> None:
    a = world.a
    item = await a_release(world, a)
    assert item["display_id"] == "REL-1"  # its own counter
    assert (item["stage"], item["stage_path"], item["status"]) == (
        "submission",
        "default",
        "submission_requested",
    )
    shown = await panel(world, a, item)
    assert rail(shown)["submission"] == ("current", 1)
    assert rail(shown)["closure"] == ("future", 0)
    offered = {m["to_status"]: m for m in shown["moves"]}
    assert set(offered) == {"submission_accepted", "submission_rejected", "closure_canceled"}
    assert offered["submission_rejected"]["reason_mode"] == "required"
    # Incidents keep their own life cycle and counter, and no stage.
    incident = await world.create(a, a.admin)
    assert (incident["display_id"], incident["stage"]) == ("INC-1", None)


async def test_req_rel_016_completing_status_moves_on_and_only_listed_moves_pass(
    world: World,
) -> None:
    a = world.a
    item = await a_release(world, a)
    skip = await move(world, a, item, "build_in_progress")
    assert problem(skip) == (409, "stage_move_not_allowed")
    accepted = await moved(world, a, item, "submission_accepted")
    # Accepted completes submission: the release is in planning, in its first status.
    assert (accepted["stage"], accepted["status"]) == ("planning", "planning_in_planning")
    assert rail(await panel(world, a, accepted))["submission"] == ("done", 1)
    history = await world.call("GET", f"{REL}/{item['id']}/history", a, a.admin)
    changes = {c["field"]: (c["old"], c["new"]) for c in history.json()["items"][0]["changes"]}
    assert changes["stage"] == ("submission", "planning")
    assert changes["status"] == ("submission_requested", "planning_in_planning")
    staged = await events(world, item["id"], "work_items.work_item.stage_changed")
    assert [(e["from_stage"], e["to_stage"]) for e in staged] == [("submission", "planning")]
    assert staged[0]["entry_id"]
    status_events = await events(world, item["id"], "work_items.work_item.status_changed")
    assert status_events[-1]["action"] == "stage_move"


async def test_approval_outcomes_only_through_the_system_entry_point(world: World) -> None:
    a = world.a
    item = await moved(world, a, await a_release(world, a), "submission_accepted")
    waiting = await moved(world, a, item, "planning_waiting_approval")
    assert waiting["status_category"] == "paused"
    by_hand = await move(world, a, waiting, "planning_plan_approved")
    assert problem(by_hand) == (409, "stage_status_system_only")
    offered = {m["to_status"] for m in (await panel(world, a, waiting))["moves"]}
    assert "planning_plan_approved" not in offered  # never offered to a person
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        record = await session.get(WorkItem, uuid.UUID(item["id"]))
        assert record is not None
        done = await service.system_stage_move(
            session, RELEASE, record, target="planning_plan_approved", source="api"
        )
        assert (done.stage, done.status) == ("build", "build_in_progress")


async def _approve(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    """Planning approved by the system entry point (as the approvals code will)."""
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        record = await session.get(WorkItem, uuid.UUID(item["id"]))
        assert record is not None
        await service.system_stage_move(
            session, RELEASE, record, target="planning_plan_approved", source="api"
        )
    response = await world.call("GET", f"{REL}/{item['id']}", org, org.admin)
    return dict(response.json())


async def test_req_rel_017_going_back_adds_a_round_and_the_rail_keeps_both(world: World) -> None:
    a = world.a
    item = await moved(world, a, await a_release(world, a), "submission_accepted")
    item = await _approve(world, a, await moved(world, a, item, "planning_waiting_approval"))
    assert item["stage"] == "build"
    item = await moved(world, a, item, "build_completed")
    assert item["status"] == "testing_in_progress"
    no_reason = await move(world, a, item, "testing_failed")
    assert no_reason.status_code == 422, no_reason.text
    item = await moved(world, a, item, "testing_failed", reason_text="Login fails on Safari")
    item = await moved(world, a, item, "build_in_progress")  # back to build
    shown = rail(await panel(world, a, item))
    assert shown["build"] == ("current", 2)  # a second round, the first kept
    assert shown["testing"] == ("done", 1)
    assert shown["planning"] == ("done", 1)
    assert shown["acceptance_testing"] == ("future", 0)


async def test_cancel_needs_a_reason_and_the_cancel_permission(world: World) -> None:
    a = world.a
    item = await a_release(world, a)
    editor = await role(
        world, a, "Release editor", [("releases.view", "all"), ("releases.edit", "all")]
    )
    assigned = await world.call("PUT", f"/users/{a.tech_c}/roles/{editor}", a, a.admin)
    assert assigned.status_code in {200, 204}, assigned.text
    offered = {m["to_status"]: m for m in (await panel(world, a, item))["moves"]}
    assert offered["closure_canceled"]["reason_mode"] == "required"
    refused = await move(
        world, a, item, "closure_canceled", user=a.tech_c, reason_text="Not needed"
    )
    assert refused.status_code == 403, refused.text
    no_reason = await move(world, a, item, "closure_canceled")
    assert no_reason.status_code == 422, no_reason.text
    canceled = await moved(world, a, item, "closure_canceled", reason_text="Not needed")
    assert (canceled["stage"], canceled["status_category"]) == ("closure", "canceled")


STAGE_TABLES = (
    "work_item_stages",
    "work_item_stage_paths",
    "work_item_path_stages",
    "work_item_status_transitions",
    "work_item_stage_entries",
)


@pytest.mark.parametrize("table", STAGE_TABLES)
async def test_stage_tables_are_isolated_by_rls(world: World, table: str) -> None:
    a, b = world.a, world.b
    await a_release(world, a)  # seeds A's model and an entry
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        mine = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608 - fixed table names
        assert mine > 0
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = (
            await session.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
                {"a": a.tenant},
            )
        ).scalar_one()
        assert seen == 0
        changed = await session.execute(
            text(f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert changed.rowcount == 0
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO work_item_stages (tenant_id, type, code, sort_order)"
                    " VALUES (:a, 'release', 'smuggled', 99)"
                ),
                {"a": a.tenant},
            )


async def _place(world: World, item: dict[str, Any], stage: str, status: str) -> dict[str, Any]:
    """Put this test's own release in a stage directly (its own fresh data)."""
    await world.sql(
        "UPDATE work_items SET stage = $2, status = $3, version = version + 1 WHERE id = $1",
        uuid.UUID(item["id"]),
        stage,
        status,
    )
    response = await world.call("GET", f"{REL}/{item['id']}", world.a, world.a.admin)
    return dict(response.json())


async def test_lane_a_review_closing_rules_required_fields_and_disabled_paths(
    world: World,
) -> None:
    a = world.a
    item = await _place(world, await a_release(world, a), "deployment", "deployment_rolled_back")
    # Entering a closed status runs the closing rules: the closure code is asked for.
    no_code = await move(world, a, item, "closure_closed")
    assert no_code.status_code == 422, no_code.text
    assert {e["field"] for e in no_code.json()["errors"]} == {"body.closure_code"}
    # A transition's required fields must have a value (ADR-041 §4).
    await world.sql(
        "UPDATE work_item_status_transitions SET required_fields = '[\"impact\"]'::jsonb"
        " WHERE tenant_id = $1 AND from_status = 'deployment_rolled_back'"
        " AND to_status = 'build_in_progress'",
        a.tenant,
    )
    no_impact = await move(world, a, item, "build_in_progress")
    assert no_impact.status_code == 422, no_impact.text
    assert {e["field"] for e in no_impact.json()["errors"]} == {"body.impact"}
    # A disabled path keeps working for the records already on it.
    await world.sql(
        "UPDATE work_item_stage_paths SET disabled_at = now() WHERE tenant_id = $1", a.tenant
    )
    closed = await world.call(
        "POST",
        f"{REL}/{item['id']}/moves",
        a,
        a.admin,
        json={"to_status": "closure_closed", "closure_code": "fixed"},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert closed.status_code == 200, closed.text
    assert (closed.json()["status_category"], closed.json()["closure_code"]) == ("closed", "fixed")
    assert rail(await panel(world, a, closed.json()))["closure"][0] == "current"


# --- a release's own fields (REQ-REL-002..005) ----------------------------------------------------


async def details(
    world: World,
    org: Org,
    item: dict[str, Any],
    version: int | None = None,
    **body: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "PATCH",
        f"{REL}/{item['id']}/details",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{version or item["version"]}"', **CONSOLE},
    )


async def test_req_rel_002_to_005_a_release_keeps_its_own_fields_with_history_and_search(
    world: World,
) -> None:
    a = world.a
    item = await a_release(world, a)
    empty = await world.call("GET", f"{REL}/{item['id']}/details", a, a.admin)
    assert empty.status_code == 200, empty.text
    assert empty.json()["release_type"] is None
    saved = await details(
        world,
        a,
        item,
        release_type="major",
        release_version="4.2.0",
        build_ref="build-1887",
        release_reason="security",
        release_notes="<p>Fixes <script>x</script>login</p>",
        scheduled_start="2026-11-10T08:00:00Z",
        scheduled_end="2026-11-10T10:00:00Z",
        release_manager_id=str(a.lead),
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["version"] == item["version"] + 1  # one If-Match for the whole record
    assert "<script>" not in body["release_notes"]  # sanitised (REQ-REL-005 AC3)
    history = await world.call("GET", f"{REL}/{item['id']}/history", a, a.admin)
    fields = {c["field"] for c in history.json()["items"][0]["changes"]}
    assert {"release_type", "release_version", "release_manager_id"} <= fields  # REQ-REL-002 AC3
    found = await world.call("GET", f"{REL}/search?q=4.2.0", a, a.admin)
    assert found.status_code == 200, found.text
    assert item["id"] in {r["id"] for r in found.json()["items"]}  # REQ-REL-005 AC1
    # The same unchanged input saves nothing.
    again = await details(world, a, item, body["version"], release_type="major")
    assert again.json()["version"] == body["version"]
    stale = await details(world, a, item, item["version"], build_ref="build-1888")
    assert stale.status_code == 409, stale.text


async def test_req_rel_002_ac2_end_before_start_and_rel_004_risk_needs_a_reason(
    world: World,
) -> None:
    a = world.a
    item = await a_release(world, a)
    backwards = await details(
        world,
        a,
        item,
        scheduled_start="2026-11-10T10:00:00Z",
        scheduled_end="2026-11-10T08:00:00Z",
    )
    assert backwards.status_code == 422, backwards.text
    assert {(e["field"], e["code"]) for e in backwards.json()["errors"]} == {
        ("body.scheduled_end", "end_before_start")
    } or {e["code"] for e in backwards.json()["errors"]} == {"end_before_start"}
    no_reason = await details(world, a, item, risk="high")
    assert no_reason.status_code == 422, no_reason.text
    assert {e["code"] for e in no_reason.json()["errors"]} == {"reason_required"}
    risky = await details(world, a, item, risk="high", risk_reason="Touches payroll")
    assert risky.status_code == 200, risky.text
    history = await world.call("GET", f"{REL}/{item['id']}/history", a, a.admin)
    assert history.json()["items"][0]["reason"] == "Touches payroll"  # REQ-REL-004 AC3


async def test_req_rel_003_a_retired_type_is_never_newly_chosen_but_kept(world: World) -> None:
    a = world.a
    item = await a_release(world, a)
    kept = (await details(world, a, item, release_type="minor")).json()
    await world.sql(
        "UPDATE work_item_reasons SET disabled_at = now() WHERE tenant_id = $1"
        " AND type = 'release' AND list = 'release_type' AND code = 'minor'",
        a.tenant,
    )
    other = await a_release(world, a)
    refused = await details(world, a, other, release_type="minor")
    assert refused.status_code == 422, refused.text
    assert {e["code"] for e in refused.json()["errors"]} == {"invalid_choice"}
    still = await details(world, a, item, kept["version"], release_type="minor", build_ref="b2")
    assert still.status_code == 200, still.text
    assert still.json()["release_type"] == "minor"  # the release that had it keeps it
    # Incidents have no release fields.
    incident = await world.create(a, a.admin)
    none = await world.call("GET", f"/incidents/{incident['id']}/details", a, a.admin)
    assert none.status_code in {404, 405}


async def test_release_details_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    item = await a_release(world, a)
    assert (await details(world, a, item, release_version="9.9.9")).status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM work_item_release_details WHERE tenant_id = :a"),
                {"a": a.tenant},
            )
        ).scalar_one()
        assert seen == 0
        changed = await session.execute(
            text("UPDATE work_item_release_details SET build_ref = 'x' WHERE tenant_id = :a"),
            {"a": a.tenant},
        )
        assert changed.rowcount == 0
    hidden = await world.call("GET", f"{REL}/{item['id']}/details", b, b.admin)
    assert hidden.status_code == 404
