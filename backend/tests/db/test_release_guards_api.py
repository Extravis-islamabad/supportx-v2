"""Required fields to leave a stage and stage access by role (WP-058a s3; REQ-REL-018, -019).

Real PostgreSQL with RLS and the real policy layer (architecture.md §11.2: stage access is a rule
the one policy evaluator applies, so the API, the offered moves and the record's operations all
agree). Refused users still see the record and its list row (stage access narrows edit and moves
only). A group change takes effect with no new sign-in: both after the change in this process
and, for other processes, through the authz invalidation consumer.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from app.modules.identity_access.service.authz_consumer import handler as authz_handler
from app.shared.events import Actor, EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World, role
from tests.db.test_release_templates_api import field_codes, patch_template, templates
from tests.db.test_releases_api import REL, a_release, move, panel

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

RELEASE_WORK = [("releases.view", "all"), ("releases.edit", "all"), ("releases.create", "all")]


async def release_workers(world: World, org: Org) -> None:
    """Tech A and Tech B work on releases (technicians only see them by default)."""
    worker = await role(world, org, "Release worker", RELEASE_WORK)
    for tech in (org.tech_a, org.tech_b):
        assigned = await world.call("PUT", f"/users/{tech}/roles/{worker}", org, org.admin)
        assert assigned.status_code == 204, assigned.text


async def set_access(world: World, org: Org, stage: str, **access: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    settings = (await world.call("GET", f"{REL}/settings", org, org.admin)).json()
    return await world.call(
        "PUT",
        f"{REL}/settings/stages/{stage}/access",
        org,
        org.admin,
        json=access,
        headers={"If-Match": f'"{settings["version"]}"', **CONSOLE},
    )


async def as_user(world: World, org: Org, user: uuid.UUID, item: dict[str, Any]) -> dict[str, Any]:
    response = await world.call("GET", f"{REL}/{item['id']}/stages", org, user)
    assert response.status_code == 200, response.text
    return dict(response.json())


def offered(shown: dict[str, Any], to: str) -> dict[str, Any]:
    return next(m for m in shown["moves"] if m["to_status"] == to)


async def test_req_rel_018_required_to_leave_is_asked_for_in_the_move(world: World) -> None:
    a = world.a
    standard = (await templates(world, a))["standard"]
    saved = await patch_template(
        world, a, standard, stage_rules={"submission": {"release_version": {"required": True}}}
    )
    assert saved.status_code == 200, saved.text
    item = await a_release(world, a)
    shown = await panel(world, a, item)
    leave = offered(shown, "submission_accepted")
    assert leave["allowed"] is True  # the dialog asks; the move is not disabled
    assert leave["missing"] == [{"field": "release_version", "code": "required_to_leave_stage"}]
    assert offered(shown, "submission_rejected")["missing"] == []  # stays in the stage
    refused = await move(world, a, item, "submission_accepted")
    assert field_codes(refused) == {("release_version", "required_to_leave_stage")}
    filled = await world.call(
        "POST",
        f"{REL}/{item['id']}/moves",
        a,
        a.admin,
        json={"to_status": "submission_accepted", "fields": {"release_version": "2.0.0"}},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert filled.status_code == 200, filled.text  # REQ-REL-018 AC1: filled in the move itself
    assert filled.json()["stage"] == "planning"
    got = (await world.call("GET", f"{REL}/{item['id']}/details", a, a.admin)).json()
    assert got["release_version"] == "2.0.0"


async def test_req_rel_019_stage_access_through_the_one_policy_layer(world: World) -> None:
    a = world.a
    await release_workers(world, a)
    typo = await set_access(world, a, "submission", move_out={"permissions": ["releases.mvoe"]})
    assert field_codes(typo) == {("access.move_out.permissions", "invalid_choice")}  # no lock-out
    saved = await set_access(world, a, "submission", move_out={"group_ids": [str(a.gb)]})
    assert saved.status_code == 200, saved.text
    item = await a_release(world, a)
    # Tech A (group GA) may not move it out of submission; Tech B (GB) may.
    shown_a = await as_user(world, a, a.tech_a, item)
    assert (
        offered(shown_a, "submission_accepted")["allowed"],
        offered(shown_a, "submission_accepted")["reason"],
    ) == (False, "stage_access")
    assert offered(shown_a, "submission_rejected")["allowed"] is True  # no edit rule: in-stage ok
    refused = await move(world, a, item, "submission_accepted", user=a.tech_a)
    assert refused.status_code == 403, refused.text
    assert refused.json()["params"]["reason"] == "stage_access"
    # Narrows moves only: Tech A still sees the record and its list row (D-052).
    seen = await world.call("GET", f"{REL}/{item['id']}", a, a.tech_a)
    assert seen.status_code == 200, seen.text
    listed = await world.call("GET", f"{REL}?limit=50", a, a.tech_a)
    assert item["id"] in {r["id"] for r in listed.json()["items"]}
    shown_b = await as_user(world, a, a.tech_b, item)
    assert offered(shown_b, "submission_accepted")["allowed"] is True
    # Editing is unrestricted until an edit rule is set; then the operation says why.
    await set_access(world, a, "submission", edit={"group_ids": [str(a.gb)]})
    record_a = (await world.call("GET", f"{REL}/{item['id']}", a, a.tech_a)).json()
    edit = next(o for o in record_a["operations"] if o["action"] == "edit")
    assert (edit["allowed"], edit["reason"]) == (False, "stage_access")
    edited = await world.call(
        "PATCH",
        f"{REL}/{item['id']}",
        a,
        a.tech_a,
        json={"subject": "Renamed"},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert edited.status_code == 403, edited.text
    moved = await move(world, a, item, "submission_accepted", user=a.tech_b)
    assert moved.status_code == 200, moved.text


async def test_a_group_change_takes_effect_without_signing_in_again(world: World) -> None:
    a = world.a
    await release_workers(world, a)
    await set_access(world, a, "submission", move_out={"group_ids": [str(a.gb)]})
    item = await a_release(world, a)
    assert (
        offered(await as_user(world, a, a.tech_a, item), "submission_accepted")["allowed"] is False
    )
    # In this process: the membership API bumps the tenant's authorization generation.
    added = await world.call("PUT", f"/organization/groups/{a.gb}/members/{a.tech_a}", a, a.admin)
    assert added.status_code in {200, 204}, added.text
    assert (
        offered(await as_user(world, a, a.tech_a, item), "submission_accepted")["allowed"] is True
    )
    # Another process's change: the row changes with no local bump, and the invalidation
    # consumer (identity_access__invalidate_authz) is what makes every API process see it.
    removed = await world.call(
        "DELETE", f"/organization/groups/{a.gb}/members/{a.tech_a}", a, a.admin
    )
    assert removed.status_code in {200, 204}, removed.text
    assert (
        offered(await as_user(world, a, a.tech_a, item), "submission_accepted")["allowed"] is False
    )
    await world.sql(
        "INSERT INTO group_members (tenant_id, group_id, user_id) VALUES ($1, $2, $3)",
        a.tenant,
        a.gb,
        a.tech_a,
    )
    settings = world.app.state.settings
    await authz_handler(lambda: settings)(
        EventEnvelope(
            event_id=uuid.uuid4(),
            event_type="organization.membership.changed",
            schema_version=1,
            tenant_id=a.tenant,
            actor=Actor.system("tests"),
            occurred_at=datetime.now(UTC),
            aggregate_type="support_group",
            aggregate_id=str(a.gb),
            payload={},
        ),
        None,
    )
    assert (
        offered(await as_user(world, a, a.tech_a, item), "submission_accepted")["allowed"] is True
    )


async def test_a_groups_only_rule_never_strands_a_release(world: World) -> None:
    """Those who configure the service desk always pass a non-empty rule (lane B's review)."""
    a = world.a
    await set_access(world, a, "submission", move_out={"group_ids": [str(a.gb)]})
    item = await a_release(world, a)
    assert offered(await as_user(world, a, a.admin, item), "submission_accepted")["allowed"] is True
    assert (await move(world, a, item, "submission_accepted")).status_code == 200


async def test_a_cleared_rule_restricts_nobody(world: World) -> None:
    """A stored rule with empty lists is no rule (lane B): nobody is locked out."""
    a = world.a
    await release_workers(world, a)
    item = await a_release(world, a)
    await world.sql(
        "UPDATE work_item_stages SET access = $2::jsonb"
        " WHERE tenant_id = $1 AND code = 'submission'",
        a.tenant,
        '{"move_out": {"group_ids": [], "permissions": []}, "edit": {"group_ids": []}}',
    )
    shown = await as_user(world, a, a.tech_a, item)
    assert offered(shown, "submission_accepted")["allowed"] is True
    assert (await move(world, a, item, "submission_accepted", user=a.tech_a)).status_code == 200
