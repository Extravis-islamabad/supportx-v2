"""Who may run a move, hardened to ADR-049 §5 (Amendment 1; lane B blocks), one test per rule.

Who may run (WP-029's transition settings) and the life cycle version's extra right and
required fields, checked by one function for the offer and for the move:
1. a record out of scope is a 404 before any condition is looked at;
2. a stale If-Match is a 409 before any condition: the facts are read after it;
3. the version's extra right is a plain permission refusal, never a condition;
4. a condition naming nobody (the requester has no manager) refuses everyone: fail closed;
5. a role the tenant does not have, or another tenant's group, is refused when saved;
6. the refusal is a 403 `transition_condition_not_met` with only its kind, and the API refuses
   exactly what the offer hid;
7. a workflow's run-as identity is limited like a person;
8. the version's required fields are listed by the offer and refused by the move.
"""

import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.service import workflow_commands
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_automation_triggers_api import offered, save_transition
from tests.db.test_incidents_api import BASE, World, problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

VERSIONS = "/incidents/settings/lifecycles/standard"


async def _reset(world: World, action: str) -> None:
    """Back to "permission only" for `action` (each test sets its own rule)."""
    listed = await world.call(
        "GET", "/automation/transitions", world.a, world.a.admin, params={"record_type": "incident"}
    )
    for row in listed.json():
        if row["action"] == action:
            gone = await world.call(
                "DELETE",
                f"/automation/transitions/{action}",
                world.a,
                world.a.admin,
                params={"record_type": "incident"},
                headers={"If-Match": f'"{row["version"]}"'},
            )
            assert gone.status_code == 204, gone.text


async def _publish_with(world: World, change: dict[str, Any]) -> None:
    """Publish the next version: "start work" (from every status) gets `change`."""
    a = world.a
    etag = (await world.call("GET", f"{VERSIONS}/versions", a, a.admin)).headers["ETag"]
    started = await world.call(
        "POST", f"{VERSIONS}/versions", a, a.admin, headers={"If-Match": etag}
    )
    assert started.status_code == 201, started.text
    number = started.json()["number"]
    moves = (await world.call("GET", f"{VERSIONS}/versions/{number}/moves", a, a.admin)).json()
    changed = [{**m, **change} if m["action"] == "start_work" else m for m in moves]
    etag = (await world.call("GET", f"{VERSIONS}/versions", a, a.admin)).headers["ETag"]
    saved = await world.call(
        "PUT",
        f"{VERSIONS}/draft/moves",
        a,
        a.admin,
        json={"moves": changed},
        headers={"If-Match": etag},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["problems"] == []
    etag = saved.headers["ETag"]
    published = await world.call(
        "POST", f"{VERSIONS}/draft/publish", a, a.admin, headers={"If-Match": etag}
    )
    assert published.status_code == 200, published.text


async def test_rule_1_a_record_out_of_scope_is_a_404_before_any_condition(world: World) -> None:
    a = world.a
    await save_transition(world, a, "resolve", relatives=["requester_manager"])
    try:
        item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
        # tech_b is in neither GA nor S1: the record does not exist for them.
        refused = await world.act(a, a.tech_b, item, "resolve")
        assert refused.status_code == 404, refused.text
    finally:
        await _reset(world, "resolve")


async def test_rule_2_a_stale_version_is_a_conflict_before_any_condition(world: World) -> None:
    a = world.a
    await save_transition(world, a, "resolve", relatives=["requester_manager"])
    try:
        item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
        stale = {**item, "version": item["version"] - 1 if item["version"] > 1 else 0}
        refused = await world.act(a, a.tech_a, stale, "resolve")
        assert refused.status_code == 409, refused.text
    finally:
        await _reset(world, "resolve")


async def test_rule_4_a_condition_naming_nobody_refuses_everyone(world: World) -> None:
    """The requester has no manager: "the requester's manager" matches no one, never anyone."""
    a = world.a
    await save_transition(world, a, "resolve", relatives=["requester_manager"])
    try:
        item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
        for user in (a.admin, a.tech_a):
            seen = await world.call("GET", f"{BASE}/{item['id']}", a, user)
            assert offered(seen.json(), "resolve") == (False, "not_for_you")
    finally:
        await _reset(world, "resolve")


async def test_rule_5_unknown_roles_and_another_tenant_s_groups_are_refused_at_save(
    world: World,
) -> None:
    a = world.a
    for body, field in (
        ({"roles": ["no_such_role"]}, "body.roles.0"),
        ({"group_ids": [str(world.b.ga)]}, "body.group_ids.0"),
    ):
        refused = await world.call(
            "PUT",
            "/automation/transitions/resolve",
            a,
            a.admin,
            params={"record_type": "incident"},
            json=body,
            headers={"If-Match": '"0"'},
        )
        assert refused.status_code == 422, refused.text
        assert field in {e["field"] for e in refused.json()["errors"]}, refused.text


async def test_rule_6_the_refusal_names_only_its_kind_and_matches_the_offer(world: World) -> None:
    a = world.a
    await save_transition(world, a, "resolve", relatives=["assignee"])
    try:
        item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
        seen = await world.call("GET", f"{BASE}/{item['id']}", a, a.tech_c)
        assert offered(seen.json(), "resolve") == (False, "not_for_you")
        refused = await world.act(a, a.tech_c, seen.json(), "resolve")
        assert problem(refused) == (403, "transition_condition_not_met")
        assert refused.json()["params"] == {"kind": "not_for_you"}  # no names, no ids
    finally:
        await _reset(world, "resolve")


async def test_rule_7_a_workflow_s_run_as_identity_is_limited_like_a_person(world: World) -> None:
    a = world.a
    await save_transition(world, a, "resolve", relatives=["assignee"])
    try:
        item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
        run = workflow_commands.runner(INCIDENT)
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            # tech_c sees the record (GA) but is not its assignee: the condition refuses.
            subject = await subject_for(session, a.tenant, a.tech_c)
            result = await run(
                session,
                subject,
                uuid.UUID(item["id"]),
                "move",
                {"action": "resolve"},
                {"kind": "workflow", "workflow_id": str(uuid.uuid4())},
            )
        assert not result.ok
        assert result.error == "transition_condition_not_met"
    finally:
        await _reset(world, "resolve")


async def test_rule_3_and_8_a_version_s_extra_right_and_required_fields(world: World) -> None:
    """The next version: "start work" needs the delete right and a category (ADR-049 §4)."""
    a = world.a
    await _publish_with(
        world, {"permission": "incidents.delete", "required_fields": ["category_id"]}
    )
    item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    # Rule 3: a technician without the delete right is refused as a missing right.
    seen = await world.call("GET", f"{BASE}/{item['id']}", a, a.tech_a)
    assert offered(seen.json(), "start_work") == (False, "no_permission")
    refused = await world.act(a, a.tech_a, seen.json(), "start_work")
    assert refused.status_code == 403, refused.text
    assert refused.json()["params"] == {"permission": "incidents.delete", "reason": "no_permission"}
    # Rule 8: the administrator holds the right; the category is still missing.
    mine = await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)
    (state,) = [s for s in mine.json()["actions"] if s["action"] == "start_work"]
    assert state["allowed"]
    assert "category_id" in state["missing"]
    needs = await world.act(a, a.admin, mine.json(), "start_work")
    assert problem(needs) == (422, "closure_rules")
    assert {(e["field"], e["code"]) for e in needs.json()["errors"]} == {
        ("body.category_id", "required_for_move")
    }
