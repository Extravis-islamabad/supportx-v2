"""Automatic approval of a request's stages over HTTP (WP-047a S2b; REQ-SR-033).

Real PostgreSQL with RLS. Someone who approved an earlier stage is not asked again when the item
(or else the tenant) says so, and the record names the stage (AC1); a stage's rule that holds
approves it at once, naming the rule and the answer keys it read, never the answers (the
coordinator's condition 2); an approval by someone who has since lost eligibility never carries
over (condition 1); the settings are Professional, and switching them off stays allowed.
"""

import json
import uuid
from typing import Any

from conftest import assign_system_role, create_tenant
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import approvals, decide, fresh, manager_of
from tests.db.test_catalog_api import add as add_item
from tests.db.test_incidents_api import CONSOLE, Org, World, problem
from tests.db.test_service_requests_api import an_item, raise_request
from tests.db.test_users_api import seed_users

pytestmark = MODULE_LOOP
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

SR = "/service-requests"


def _staged(stages: list[dict[str, Any]]) -> dict[str, Any]:
    return {"approvers": stages[0]["approvers"], "stages": stages}


def _person(user: uuid.UUID, **stage: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"approvers": [{"kind": "person", "person_id": str(user)}], **stage}


async def _raised(
    world: World, org: Org, stages: list[dict[str, Any]], *, model: str = "air"
) -> dict[str, Any]:
    item = await an_item(world, org, approval=_staged(stages))
    made = await raise_request(
        world, org, org.requester, catalog_item_id=item["id"], answers={"model": model}
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


def _of(entries: list[dict[str, Any]], stage: int) -> list[dict[str, Any]]:
    return [e for e in entries if e["stage"] == stage]


async def _tenant_earlier(world: World, org: Org, on: bool) -> Any:  # noqa: ANN401 - the switch
    current = await world.call("GET", f"{SR}/settings", org, org.admin)
    assert current.status_code == 200, current.text
    return await world.call(
        "PATCH",
        f"{SR}/settings",
        org,
        org.admin,
        json={"auto_approve_earlier": on},
        headers={"If-Match": f'"{current.json()["version"]}"', **CONSOLE},
    )


async def _events(world: World, approval_id: str) -> list[str]:
    """The approval's outbox events, as their `change` (opened, decided, closed)."""
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = 'work_items.approval.changed'"
        " ORDER BY id"
    )
    found = []
    for row in rows:
        payload = json.loads(row["envelope"])["payload"]
        if payload["approval_id"] == approval_id:
            found.append(payload["change"])
    return found


async def test_ac1_an_approver_of_stage_1_is_not_asked_again_at_stage_3(world: World) -> None:
    """REQ-SR-033 AC1: stage 3 shows "approved automatically", naming stage 1; nobody mailed."""
    a = world.a
    record = await _raised(
        world,
        a,
        [_person(a.tech_a), _person(a.tech_b), _person(a.tech_a, auto_earlier=True)],
    )
    [first] = _of(await approvals(world, a, a.admin, record), 1)
    assert (await decide(world, a, a.tech_a, record, first, "approve")).status_code == 200
    [second] = _of(await approvals(world, a, a.admin, record), 2)
    assert (await decide(world, a, a.tech_b, record, second, "approve")).status_code == 200
    [third] = _of(await approvals(world, a, a.admin, record), 3)
    assert (third["state"], third["channel"], third["auto_reason"], third["auto_ref"]) == (
        "approved",
        "automatic",
        "approved_earlier",
        1,
    )
    assert third["approver_id"] == str(a.tech_a)
    assert third["decided_by"] is None  # nobody decided it now
    assert (await fresh(world, a, record))["approval_status"] == "approved"
    assert await _events(world, third["id"]) == ["decided"]  # never "opened": no mail asks
    audit = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2 AND object_id = $3",
        a.tenant,
        "service_request.approved_automatically",
        record["id"],
    )
    assert [json.loads(r["details"])["reason"] for r in audit] == ["approved_earlier"]


async def test_without_the_switch_they_are_asked_again(world: World) -> None:
    a = world.a
    record = await _raised(world, a, [_person(a.tech_a), _person(a.tech_a)])
    [first] = _of(await approvals(world, a, a.admin, record), 1)
    assert (await decide(world, a, a.tech_a, record, first, "approve")).status_code == 200
    [second] = _of(await approvals(world, a, a.admin, record), 2)
    assert (second["state"], second["auto_reason"]) == ("pending", None)


async def test_the_tenant_switch_applies_unless_the_item_says_otherwise(world: World) -> None:
    """The coordinator's Q1: off by default; the item's own setting overrides the tenant's."""
    a = world.a
    assert (await world.call("GET", f"{SR}/settings", a, a.admin)).json()[
        "auto_approve_earlier"
    ] is False
    switched = await _tenant_earlier(world, a, on=True)
    assert switched.status_code == 200, switched.text
    try:
        follows = await _raised(world, a, [_person(a.tech_a), _person(a.tech_a)])
        overrides = await _raised(
            world, a, [_person(a.tech_a), _person(a.tech_a, auto_earlier=False)]
        )
        for record, expected in ((follows, "approved"), (overrides, "pending")):
            [first] = _of(await approvals(world, a, a.admin, record), 1)
            assert (await decide(world, a, a.tech_a, record, first, "approve")).status_code == 200
            [second] = _of(await approvals(world, a, a.admin, record), 2)
            assert second["state"] == expected, record["display_id"]
    finally:
        assert (await _tenant_earlier(world, a, on=False)).status_code == 200


async def test_an_approval_by_someone_no_longer_eligible_never_carries_over(
    world: World,
) -> None:
    """The coordinator's condition 1: eligibility is checked again when the later stage opens."""
    a = world.a
    [leaver] = await seed_users(world.db, a.tenant, [{"user_type": "technician"}])
    await assign_system_role(world.db.admin_url, a.tenant, leaver, "technician")
    record = await _raised(
        world,
        a,
        [_person(leaver), _person(a.tech_b), _person(leaver, auto_earlier=True)],
    )
    [first] = _of(await approvals(world, a, a.admin, record), 1)
    assert (await decide(world, a, leaver, record, first, "approve")).status_code == 200
    person = await world.call("GET", f"/users/{leaver}", a, a.admin)
    left = await world.call(
        "POST",
        f"/users/{leaver}/deactivate",
        a,
        a.admin,
        headers={"If-Match": person.headers["ETag"], **CONSOLE},
    )
    assert left.status_code == 200, left.text
    [second] = _of(await approvals(world, a, a.admin, record), 2)
    assert (await decide(world, a, a.tech_b, record, second, "approve")).status_code == 200
    [third] = _of(await approvals(world, a, a.admin, record), 3)
    assert (third["state"], third["auto_reason"]) == ("pending", None)
    assert (third["origin"], third["route_reason"]) == ("administrators", "approver_inactive")


async def test_a_rule_that_holds_approves_the_stage_naming_its_keys_not_the_answers(
    world: World,
) -> None:
    """The coordinator's condition 2: the record and the audit name the rule and the keys."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    rule = {
        "name": {"en": "Air laptops are pre-approved"},
        "condition": {"field": "model", "op": "eq", "value": "air"},
    }
    record = await _raised(
        world, a, [{"approvers": [{"kind": "requested_for_manager"}], "auto_rules": [rule]}]
    )
    assert (await fresh(world, a, record))["approval_status"] == "approved"  # at once
    [entry] = await approvals(world, a, a.admin, record)
    assert (entry["state"], entry["auto_reason"], entry["auto_ref"]) == (
        "approved",
        "rule_matched",
        1,
    )
    assert entry["auto_rule"] == {"en": "Air laptops are pre-approved"}
    assert entry["auto_keys"] == ["model"]  # staff see the keys it read
    [seen] = await approvals(world, a, a.requester, record)
    assert seen["auto_rule"] == {"en": "Air laptops are pre-approved"}
    assert seen["auto_keys"] is None  # the item's set-up stays staff-only
    history = await world.sql(
        "SELECT new_value FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = 'approval_automatic'",
        a.tenant,
        uuid.UUID(record["id"]),
    )
    [said] = [json.loads(r["new_value"]) for r in history]
    assert (said["reason"], said["keys"], said["rule"]) == (
        "rule_matched",
        ["model"],
        {"en": "Air laptops are pre-approved"},
    )
    audit = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2 AND object_id = $3",
        a.tenant,
        "service_request.approved_automatically",
        record["id"],
    )
    [details] = [json.loads(r["details"]) for r in audit]
    assert details["keys"] == ["model"]
    assert "air" not in json.dumps(details)
    assert "air" not in json.dumps(said)

    other = await _raised(
        world,
        a,
        [{"approvers": [{"kind": "requested_for_manager"}], "auto_rules": [rule]}],
        model="pro",
    )
    [waiting] = await approvals(world, a, a.admin, other)
    assert (waiting["state"], waiting["auto_reason"]) == ("pending", None)


async def test_automatic_approval_is_professional_and_switching_it_off_stays_open(
    world: World,
) -> None:
    """REQ-SR-033 is Professional (`catalog`): an Essentials tenant may not turn it on."""
    tenant = await create_tenant(world.db.migrator_url, "Essentials auto", edition="essentials")
    (admin, approver, requester) = await seed_users(
        world.db,
        tenant,
        [{"user_type": "technician"}, {"user_type": "technician"}, {"user_type": "requester"}],
    )
    await assign_system_role(world.db.admin_url, tenant, admin, "tenant_admin")
    org = Org(tenant, admin, admin, admin, approver, admin, requester, requester)
    refused = await _tenant_earlier(world, org, on=True)
    assert problem(refused) == (403, "entitlement_required")
    assert (await _tenant_earlier(world, org, on=False)).status_code == 200  # off: allowed
    group = await world.call("POST", "/organization/groups", org, admin, json={"name": "Desk"})
    named = {"approvers": [{"kind": "person", "person_id": str(approver)}]}
    for auto in (
        {"auto_earlier": True},
        {"auto_earlier": False},
        {
            "auto_rules": [
                {"name": {"en": "x"}, "condition": {"field": "quantity", "op": "eq", "value": 1}}
            ]
        },
    ):
        made = await add_item(
            world, org, admin, group_id=group.json()["id"], approval={**named, **auto}
        )
        assert problem(made) == (403, "entitlement_required"), auto
