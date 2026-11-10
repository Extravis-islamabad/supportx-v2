"""Roles, plan sections, stage schedules and downtimes over HTTP (WP-058a s4; REQ-REL-023..028).

Real PostgreSQL with RLS and the real policy layer:
- a role holder reaches the record through the `own` scope (in person or through a group), in
  the list and on the record alike;
- eligibility refuses inactive or ineligible people and names the missing permission, and the
  picker offers only eligible people;
- stage access by role follows the current holder at once;
- plan sections conflict only on the same section;
- the engine stamps actual stage dates and corrections need a reason;
- a failed outcome needs its issues;
- downtimes keep their own versions;
- the five new tables are isolated per tenant;
- reports run with releases and their holders present: the reporting role reads the holders the
  own scope needs (0095).
"""

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.shared.events import EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World, role
from tests.db.test_release_guards_api import release_workers, set_access
from tests.db.test_release_templates_api import field_codes
from tests.db.test_releases_api import REL, a_release, move, moved
from tests.db.test_reports_api import ran

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def settings_version(world: World, org: Org) -> int:
    return int((await world.call("GET", f"{REL}/settings", org, org.admin)).json()["version"])


async def put_role(
    world: World,
    org: Org,
    item: dict[str, Any],
    code: str,
    *,
    users: list[uuid.UUID] | None = None,
    groups: list[uuid.UUID] | None = None,
    version: int | None = None,
) -> httpx.Response:
    return await world.call(
        "PUT",
        f"{REL}/{item['id']}/roles/{code}",
        org,
        org.admin,
        json={
            "user_ids": [str(u) for u in users or []],
            "group_ids": [str(g) for g in groups or []],
        },
        headers={"If-Match": f'"{version or item["version"]}"', **CONSOLE},
    )


async def patch_role_def(world: World, org: Org, code: str, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "PATCH",
        f"{REL}/settings/roles/{code}",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{await settings_version(world, org)}"', **CONSOLE},
    )


async def test_req_rel_023_roles_with_history_and_one_holder_each(world: World) -> None:
    a = world.a
    item = await a_release(world, a)
    shown = (await world.call("GET", f"{REL}/{item['id']}/roles", a, a.admin)).json()
    assert [r["code"] for r in shown["roles"]] == [
        "requester",
        "release_manager",
        "release_engineer",
        "development_lead",
        "qa_lead",
        "uat_owner",
        "reviewer",
    ]
    two = await put_role(world, a, item, "qa_lead", users=[a.tech_a, a.tech_b])
    assert field_codes(two) == {("user_ids", "too_many_items")}
    group = await put_role(world, a, item, "qa_lead", groups=[a.ga])
    assert field_codes(group) == {("group_ids", "not_allowed")}  # a single role: people only
    saved = await put_role(world, a, item, "qa_lead", users=[a.tech_a])
    assert saved.status_code == 200, saved.text
    qa = next(r for r in saved.json()["roles"] if r["code"] == "qa_lead")
    assert qa["user_ids"] == [str(a.tech_a)]
    assert saved.json()["version"] == item["version"] + 1
    history = await world.call("GET", f"{REL}/{item['id']}/history", a, a.admin)
    change = history.json()["items"][0]["changes"][0]
    assert change["field"] == "role.qa_lead"  # REQ-REL-023 AC3: old and new holder
    assert (change["old"]["users"], change["new"]["users"]) == ([], [str(a.tech_a)])
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE aggregate_id = $1 ORDER BY id", item["id"]
    )
    events = [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]
    roles_changed = [e.payload for e in events if e.event_type.endswith("roles_changed")]
    assert roles_changed[-1]["users_after"] == [str(a.tech_a)]


async def test_req_rel_024_only_eligible_active_people_and_the_picker_agrees(
    world: World,
) -> None:
    a = world.a
    await release_workers(world, a)
    ruled = await patch_role_def(
        world, a, "release_manager", eligibility={"permissions": ["releases.delete"]}
    )
    assert ruled.status_code == 200, ruled.text
    item = await a_release(world, a)
    refused = await put_role(world, a, item, "release_manager", users=[a.tech_a])
    assert field_codes(refused) == {("user_ids", "not_eligible")}  # AC1, naming the permission
    assert refused.json()["errors"][0]["params"]["permission"] == "releases.delete"
    candidates = await world.call("GET", f"{REL}/roles/release_manager/candidates", a, a.admin)
    offered = {c["id"] for c in candidates.json()}
    assert str(a.admin) in offered  # the tenant admin holds releases.delete
    assert str(a.tech_a) not in offered
    assert (await put_role(world, a, item, "release_manager", users=[a.admin])).status_code == 200
    # Deactivated people never hold a role.
    await world.sql("UPDATE users SET status = 'disabled' WHERE id = $1", a.tech_b)
    gone = await put_role(world, a, item, "qa_lead", users=[a.tech_b], version=item["version"] + 1)
    assert field_codes(gone) == {("user_ids", "user_not_found")}
    # Removed people neither, even if their status still says active (lane B).
    await world.sql(
        "UPDATE users SET deleted_at = now(), status = 'active' WHERE id = $1", a.requester2
    )
    removed = await put_role(
        world, a, item, "uat_owner", users=[a.requester2], version=item["version"] + 1
    )
    assert field_codes(removed) == {("user_ids", "user_not_found")}
    typo = await patch_role_def(world, a, "qa_lead", eligibility={"permissions": ["releases.nope"]})
    assert field_codes(typo) == {("eligibility.permissions", "invalid_choice")}


async def test_a_holder_reaches_the_record_through_the_own_scope(world: World) -> None:
    a = world.a
    own = await role(world, a, "Own releases", [("releases.view", "own")])
    assigned = await world.call("PUT", f"/users/{a.requester2}/roles/{own}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    item = await a_release(world, a)
    hidden = await world.call("GET", f"{REL}/{item['id']}", a, a.requester2)
    assert hidden.status_code == 404
    held = await put_role(world, a, item, "uat_owner", users=[a.requester2])
    assert held.status_code == 200, held.text
    seen = await world.call("GET", f"{REL}/{item['id']}", a, a.requester2)
    assert seen.status_code == 200, seen.text
    listed = await world.call("GET", f"{REL}?limit=50", a, a.requester2)
    assert item["id"] in {r["id"] for r in listed.json()["items"]}  # the list agrees


async def test_reports_run_with_release_holders_for_every_scope(world: World) -> None:
    """The own scope reads role holders (owner_extra), and so do reports: no 500 for anyone."""
    a = world.a
    await world.create(a, a.admin)  # one incident
    item = await a_release(world, a)
    held = await put_role(world, a, item, "uat_owner", users=[a.tech_b])
    assert held.status_code == 200, held.text
    own = await role(
        world, a, "Own work and reports", [("incidents.view", "own"), ("reports.view", "all")]
    )
    assigned = await world.call("PUT", f"/users/{a.tech_b}/roles/{own}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    assert (await ran(world, a, a.admin))["totals"] == [1]  # releases never count as incidents
    mine = await ran(world, a, a.tech_b)  # the own scope, with a held release in the tenant
    listed = await world.call("GET", "/incidents?limit=100", a, a.tech_b)
    assert mine["totals"] == [len(listed.json()["items"])]  # the report and the list agree


async def test_a_group_holds_a_role_of_several_and_its_members_reach_the_record(
    world: World,
) -> None:
    a = world.a
    added = await world.call(
        "POST",
        f"{REL}/settings/roles",
        a,
        a.admin,
        json={"labels": {"en": "Testers"}, "single": False},
        headers={"If-Match": f'"{await settings_version(world, a)}"', **CONSOLE},
    )
    assert added.status_code == 201, added.text
    code = added.headers["Location"].rsplit("/", 1)[-1]
    own = await role(world, a, "Own releases B", [("releases.view", "own")])
    await world.call("PUT", f"/users/{a.tech_b}/roles/{own}", a, a.admin)
    item = await a_release(world, a)
    saved = await put_role(world, a, item, code, groups=[a.gb], users=[a.tech_a])
    assert saved.status_code == 200, saved.text
    testers = next(r for r in saved.json()["roles"] if r["code"] == code)
    assert (testers["group_ids"], testers["user_ids"]) == ([str(a.gb)], [str(a.tech_a)])


async def test_req_rel_019_stage_access_by_role_follows_the_current_holder(world: World) -> None:
    a = world.a
    await release_workers(world, a)
    await set_access(world, a, "submission", move_out={"roles": ["release_manager"]})
    item = await a_release(world, a)
    refused = await move(world, a, item, "submission_accepted", user=a.tech_a)
    assert refused.status_code == 403, refused.text
    held = await put_role(world, a, item, "release_manager", users=[a.tech_a])
    assert held.status_code == 200, held.text
    moved_now = await move(
        world, a, {**item, "version": held.json()["version"]}, "submission_accepted", user=a.tech_a
    )
    assert moved_now.status_code == 200, moved_now.text  # REQ-REL-019 AC2: at once


async def test_req_rel_025_plan_sections_conflict_only_on_the_same_section(world: World) -> None:
    a = world.a
    item = await a_release(world, a)

    async def put(section: str, content: str, version: int) -> httpx.Response:
        return await world.call(
            "PUT",
            f"{REL}/{item['id']}/plan/{section}",
            a,
            a.admin,
            json={"content": content},
            headers={"If-Match": f'"{version}"', **CONSOLE},
        )

    first = await put("rollout", "<p>Roll out at 22:00<script>x</script></p>", 0)
    assert first.status_code == 200, first.text
    assert "<script>" not in first.json()["content"]
    other = await put("backout", "<p>Restore the snapshot</p>", 0)  # another section: no clash
    assert other.status_code == 200, other.text
    stale = await put("rollout", "<p>Someone else's plan</p>", 0)
    assert stale.status_code == 409, stale.text
    history = await world.call("GET", f"{REL}/{item['id']}/history", a, a.admin)
    assert history.json()["items"][0]["changes"][0]["field"] == "plan.backout"
    sections = (await world.call("GET", f"{REL}/{item['id']}/plan", a, a.admin)).json()
    assert [s["section"] for s in sections][:3] == ["impact", "rollout", "backout"]
    assert [s["version"] for s in sections][:3] == [0, 1, 1]


async def test_req_rel_026_028_actual_dates_and_outcomes(world: World) -> None:
    a = world.a
    item = await moved(world, a, await a_release(world, a), "submission_accepted")
    schedule = {
        s["stage"]: s
        for s in (await world.call("GET", f"{REL}/{item['id']}/schedule", a, a.admin)).json()
    }
    assert schedule["submission"]["actual_start"] is not None
    assert schedule["submission"]["actual_end"] is not None  # left on acceptance
    assert schedule["planning"]["actual_start"] is not None  # AC1: set on entering
    assert schedule["planning"]["actual_end"] is None

    async def patch(stage: str, version: int, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
        return await world.call(
            "PATCH",
            f"{REL}/{item['id']}/schedule/{stage}",
            a,
            a.admin,
            json=body,
            headers={"If-Match": f'"{version}"', **CONSOLE},
        )

    planning = schedule["planning"]
    no_reason = await patch("planning", planning["version"], actual_start="2026-11-01T08:00:00Z")
    assert field_codes(no_reason) == {("reason", "reason_required")}
    fixed = await patch(
        "planning",
        planning["version"],
        actual_start="2026-11-01T08:00:00Z",
        scheduled_end="2026-11-20T17:00:00Z",
        reason="Planning started at the kick-off",
    )
    assert fixed.status_code == 200, fixed.text
    not_here = await patch("planning", fixed.json()["version"], outcome="passed")
    assert field_codes(not_here) == {("outcome", "not_allowed")}  # planning has no outcome
    testing = schedule["testing"]
    failed = await patch("testing", testing["version"], outcome="failed")
    assert field_codes(failed) == {("issues", "required")}  # REQ-REL-028 AC1
    noted = await patch("testing", testing["version"], outcome="failed", issues="Login breaks")
    assert noted.status_code == 200, noted.text


async def test_req_rel_027_downtime_windows(world: World) -> None:
    a = world.a
    item = await a_release(world, a)
    key = str(uuid.uuid4())

    async def add(**body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
        return await world.call(
            "POST",
            f"{REL}/{item['id']}/downtimes",
            a,
            a.admin,
            json=body,
            headers={"Idempotency-Key": key, **CONSOLE},
        )

    window = {
        "kind": "maintenance_window",
        "starts_at": "2026-11-12T22:00:00Z",
        "ends_at": "2026-11-12T23:00:00Z",
        "service_ids": [str(uuid.uuid4())],
    }
    made = await add(**window)
    assert made.status_code == 201, made.text
    assert (await add(**window)).json()["id"] == made.json()["id"]  # one window for one key
    backwards = await world.call(
        "POST",
        f"{REL}/{item['id']}/downtimes",
        a,
        a.admin,
        json={**window, "ends_at": "2026-11-12T21:00:00Z"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert field_codes(backwards) == {("ends_at", "end_before_start")}
    down = made.json()
    changed = await world.call(
        "PATCH",
        f"{REL}/{item['id']}/downtimes/{down['id']}",
        a,
        a.admin,
        json={"phase": "actual", "description": "Took 50 minutes"},
        headers={"If-Match": f'"{down["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    removed = await world.call(
        "DELETE",
        f"{REL}/{item['id']}/downtimes/{down['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{changed.json()["version"]}"', **CONSOLE},
    )
    assert removed.status_code == 204, removed.text
    assert (await world.call("GET", f"{REL}/{item['id']}/downtimes", a, a.admin)).json() == []


PART_TABLES = (
    "work_item_role_defs",
    "work_item_role_holders",
    "work_item_plan_sections",
    "work_item_stage_schedules",
    "work_item_downtimes",
)


@pytest.mark.parametrize("table", PART_TABLES)
async def test_part_tables_are_isolated_by_rls(world: World, table: str) -> None:
    a, b = world.a, world.b
    item = await moved(world, a, await a_release(world, a), "submission_accepted")
    roles = await put_role(world, a, item, "qa_lead", users=[a.tech_a], version=item["version"])
    assert roles.status_code == 200, roles.text
    await world.call(
        "PUT",
        f"{REL}/{item['id']}/plan/rollout",
        a,
        a.admin,
        json={"content": "<p>x</p>"},
        headers={"If-Match": '"0"', **CONSOLE},
    )
    await world.call(
        "POST",
        f"{REL}/{item['id']}/downtimes",
        a,
        a.admin,
        json={"starts_at": "2026-11-12T22:00:00Z", "ends_at": "2026-11-12T23:00:00Z"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
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
