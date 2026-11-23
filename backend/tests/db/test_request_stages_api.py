"""A service request's approval stages over HTTP (WP-047a S2a; REQ-SR-029..032).

Real PostgreSQL with RLS. Stages run in order; neighbours sharing a parallel group open
together and one rejection ends them; a stage whose condition does not hold is skipped and
shown with it; the requester never approves their own request (audited); a stage naming nobody
goes to the approval administrators, recorded; an item with today's one stage is unchanged.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.work_items.service.person_data import REFERENCES
from conftest import assign_system_role, create_tenant
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import MANAGER, approvals, decide, fresh, manager_of
from tests.db.test_catalog_api import add as add_item
from tests.db.test_incidents_api import CONSOLE, Org, World, problem
from tests.db.test_service_requests_api import an_item, raise_request
from tests.db.test_users_api import seed_users

pytestmark = MODULE_LOOP
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used


def _staged(stages: list[dict[str, Any]]) -> dict[str, Any]:
    """An approval with stages: the top level repeats stage 1, as the API reads it back."""
    return {"approvers": stages[0]["approvers"], "stages": stages}


def _person(user: uuid.UUID, **stage: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"approvers": [{"kind": "person", "person_id": str(user)}], **stage}


async def _raised(
    world: World,
    org: Org,
    stages: list[dict[str, Any]],
    *,
    model: str = "air",
) -> dict[str, Any]:
    item = await an_item(world, org, approval=_staged(stages))
    made = await raise_request(
        world, org, org.requester, catalog_item_id=item["id"], answers={"model": model}
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


def _of(entries: list[dict[str, Any]], stage: int) -> list[dict[str, Any]]:
    return [e for e in entries if e["stage"] == stage]


async def _snapshot(world: World, record: dict[str, Any]) -> Any:  # noqa: ANN401 - JSON
    rows = await world.sql(
        "SELECT approval_stages FROM work_items WHERE id = $1", uuid.UUID(record["id"])
    )
    value = rows[0]["approval_stages"]
    return json.loads(value) if isinstance(value, str) else value


async def test_an_item_with_todays_one_stage_runs_unchanged(world: World) -> None:
    """The coordinator's condition 5: no snapshot, one row at stage 1, settled as before."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await an_item(world, a, **MANAGER)
    made = await raise_request(
        world, a, a.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    record = made.json()
    assert await _snapshot(world, record) is None
    [entry] = await approvals(world, a, a.tech_a, record)
    assert (entry["stage"], entry["rule"], entry["branch"], entry["skip_reason"]) == (
        1,
        None,
        None,
        None,
    )
    approved = await decide(world, a, a.tech_a, record, entry, "approve")
    assert approved.status_code == 200, approved.text
    assert (await fresh(world, a, record))["approval_status"] == "approved"


async def test_three_stages_run_in_order_and_the_last_approves(world: World) -> None:
    """REQ-SR-029 AC1: the manager, then one of a group, then a named person."""
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    members = [
        r["user_id"]
        for r in await world.sql(
            "SELECT user_id FROM group_members WHERE group_id = $1 AND user_id <> $2",
            a.ga,
            a.requester,
        )
    ]
    assert members, "the world's group A has members"
    record = await _raised(
        world,
        a,
        [
            {"approvers": [{"kind": "requested_for_manager"}]},
            {"approvers": [{"kind": "group", "group_id": str(a.ga)}], "rule": "any"},
            _person(a.tech_b),
        ],
    )
    assert (await _snapshot(world, record))["v"] == 1
    entries = await approvals(world, a, a.admin, record)
    assert {e["stage"] for e in entries} == {1}  # only the first stage is open
    [first] = _of(entries, 1)
    assert (await decide(world, a, a.tech_a, record, first, "approve")).status_code == 200
    second = _of(await approvals(world, a, a.admin, record), 2)
    assert {e["approver_id"] for e in second} == {str(m) for m in members}
    decider = next(e for e in second if e["approver_id"] == str(members[0]))
    assert (await decide(world, a, members[0], record, decider, "approve")).status_code == 200
    entries = await approvals(world, a, a.admin, record)
    assert all(e["state"] == "not_needed" for e in _of(entries, 2) if e["id"] != decider["id"])
    assert (await fresh(world, a, record))["approval_status"] == "pending"
    [third] = _of(entries, 3)
    assert (await decide(world, a, a.tech_b, record, third, "approve")).status_code == 200
    after = await fresh(world, a, record)
    assert after["approval_status"] == "approved"


async def test_a_parallel_pair_ends_on_one_rejection(world: World) -> None:
    """REQ-SR-030 AC1, AC2: both open together; one rejects, the other is not needed."""
    a = world.a
    record = await _raised(
        world,
        a,
        [_person(a.tech_a, parallel_group="pair"), _person(a.tech_b, parallel_group="pair")],
    )
    entries = await approvals(world, a, a.admin, record)
    assert sorted(e["stage"] for e in entries) == [1, 2]
    assert {e["branch"] for e in entries} == {"pair"}
    [mine] = _of(entries, 1)
    rejected = await decide(world, a, a.tech_a, record, mine, "reject", "Not this quarter")
    assert rejected.status_code == 200, rejected.text
    [other] = _of(await approvals(world, a, a.admin, record), 2)
    assert other["state"] == "not_needed"
    after = await fresh(world, a, record)
    assert (after["status"], after["approval_status"]) == ("rejected", "rejected")


async def test_a_stage_whose_condition_fails_is_skipped_and_shown_with_it(world: World) -> None:
    """REQ-SR-032 AC1, AC2: skipped with its condition; the next stage opens at once."""
    a = world.a
    condition = {"field": "model", "op": "eq", "value": "pro"}
    record = await _raised(
        world, a, [_person(a.tech_a, condition=condition), _person(a.tech_b)], model="air"
    )
    entries = await approvals(world, a, a.admin, record)
    [skipped] = _of(entries, 1)
    assert (skipped["state"], skipped["skip_reason"], skipped["condition"]) == (
        "skipped",
        "condition_not_met",
        condition,
    )
    assert skipped["can_decide"] is False
    [waiting] = _of(entries, 2)
    assert (waiting["approver_id"], waiting["state"]) == (str(a.tech_b), "pending")


async def test_every_stage_skipped_approves_the_request_at_once(world: World) -> None:
    a = world.a
    condition = {"field": "model", "op": "eq", "value": "pro"}
    record = await _raised(
        world,
        a,
        [_person(a.tech_a, condition=condition), _person(a.tech_b, condition=condition)],
        model="air",
    )
    assert {e["state"] for e in await approvals(world, a, a.admin, record)} == {"skipped"}
    assert (await fresh(world, a, record))["approval_status"] == "approved"


async def test_the_requester_never_approves_their_own_request(world: World) -> None:
    """The coordinator's S2 condition 2: left out even with self-approval on, and audited."""
    a = world.a
    before = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        "service_request.approver_was_requester",
    )
    record = await _raised(world, a, [_person(a.requester, self_approval=True), _person(a.tech_b)])
    [entry] = _of(await approvals(world, a, a.admin, record), 1)
    assert (entry["approver_id"], entry["origin"], entry["route_reason"]) == (
        None,
        "administrators",
        "self_approval_blocked",
    )
    after = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        "service_request.approver_was_requester",
    )
    assert after[0]["n"] == before[0]["n"] + 1


async def test_a_stage_naming_nobody_goes_to_the_administrators_recorded(world: World) -> None:
    """Condition 3: a CI owner with no CI linked (until WP-053 S5) names nobody."""
    a = world.a
    record = await _raised(world, a, [{"approvers": [{"kind": "ci_owner"}]}])
    [entry] = await approvals(world, a, a.admin, record)
    assert (entry["origin"], entry["route_reason"]) == ("administrators", "no_approver")


async def test_an_erased_person_leaves_the_snapshot(world: World) -> None:
    """The snapshot condition 2: named approvers and backups come off requests in flight."""
    a = world.a
    record = await _raised(
        world, a, [_person(a.tech_a), _person(a.tech_b, backup_id=str(a.tech_c))]
    )
    assert str(a.tech_b) in json.dumps(await _snapshot(world, record))
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        cursor: str | None = None
        counts: dict[str, int] = {}
        for _ in range(20):
            batch = await REFERENCES.erase_person(
                session,
                a.tech_b,
                successor_id=a.tech_c,
                keep_files={},
                now=datetime.now(UTC),
                cursor=cursor,
            )
            for kind, n in batch.counts.items():
                counts[kind] = counts.get(kind, 0) + n
            cursor = batch.cursor
            if cursor is None:
                break
    assert counts.get("stage_approvers_removed", 0) >= 1
    stored = await _snapshot(world, record)
    assert str(a.tech_b) not in json.dumps(stored)
    assert stored["stages"][1]["backup_id"] == str(a.tech_c)


async def test_editions_todays_single_stage_stays_on_essentials(world: World) -> None:
    """The coordinator's rule: each REQ gated by its own spec edition, on the server.

    REQ-SR-029 (several stages, a rule), -030 (parallel), -031 (the new kinds) and -032
    (conditions) are Professional; an item with today's one stage saves and is approved on
    Essentials exactly as before.
    """
    tenant = await create_tenant(world.db.migrator_url, "Essentials stages", edition="essentials")
    (admin, approver, requester) = await seed_users(
        world.db,
        tenant,
        [{"user_type": "technician"}, {"user_type": "technician"}, {"user_type": "requester"}],
    )
    await assign_system_role(world.db.admin_url, tenant, admin, "tenant_admin")
    await assign_system_role(world.db.admin_url, tenant, approver, "tenant_admin")
    await assign_system_role(world.db.admin_url, tenant, requester, "requester")
    org = Org(tenant, admin, admin, admin, admin, admin, requester, requester)
    group = await world.call("POST", "/organization/groups", org, admin, json={"name": "Desk"})
    assert group.status_code == 201, group.text
    base = {
        "questions": [
            {
                "key": "model",
                "label": {"en": "Model"},
                "kind": "choice",
                "required": True,
                "options": ["air", "pro"],
            }
        ],
        "status": "published",
        "group_id": group.json()["id"],
    }
    named = {"approvers": [{"kind": "person", "person_id": str(approver)}]}
    professional = {
        "REQ-SR-029 stages": _staged([named, named]),
        "REQ-SR-029 rule": {**named, "rule": "all"},
        "REQ-SR-030": _staged([{**named, "parallel_group": "pair"}]),
        "REQ-SR-031": {"approvers": [{"kind": "department_head"}]},
        "REQ-SR-032": {**named, "condition": {"field": "model", "op": "eq", "value": "pro"}},
    }
    for req, approval in professional.items():
        refused = await add_item(world, org, admin, **base, approval=approval)
        assert problem(refused) == (403, "entitlement_required"), req

    made = await add_item(world, org, admin, **base, approval=named)
    assert made.status_code == 201, made.text
    record = await raise_request(
        world, org, requester, catalog_item_id=made.json()["id"], answers={"model": "air"}
    )
    assert record.status_code == 201, record.text
    assert await _snapshot(world, record.json()) is None  # today's path, no stages engine
    [entry] = await approvals(world, org, approver, record.json())
    approved = await decide(world, org, approver, record.json(), entry, "approve")
    assert approved.status_code == 200, approved.text
    assert (await fresh(world, org, record.json()))["approval_status"] == "approved"


async def test_a_downgrade_finishes_requests_in_flight_and_refuses_new_ones_clearly(
    world: World,
) -> None:
    """The coordinator's downgrade case, from Professional to Essentials with stages in use.

    - A request already submitted finishes on its snapshot (never stranded).
    - Saving the item with its stages again is refused (labelled `entitlement_required`), but
      reducing it to one stage of today's kinds is allowed.
    - A new request on the still-staged item is refused clearly, never run on stage 1 alone
      (that would skip the approvals the later stages ask for). Recorded in the PR and PROGRESS.
    """
    tenant = await create_tenant(world.db.migrator_url, "Downgraded stages", edition="enterprise")
    (admin, first, second, requester) = await seed_users(
        world.db,
        tenant,
        [
            {"user_type": "technician"},
            {"user_type": "technician"},
            {"user_type": "technician"},
            {"user_type": "requester"},
        ],
    )
    for person in (admin, first, second):
        await assign_system_role(world.db.admin_url, tenant, person, "tenant_admin")
    await assign_system_role(world.db.admin_url, tenant, requester, "requester")
    org = Org(tenant, admin, admin, admin, admin, admin, requester, requester)
    group = await world.call("POST", "/organization/groups", org, admin, json={"name": "Desk"})
    assert group.status_code == 201, group.text
    base = {
        "questions": [
            {
                "key": "model",
                "label": {"en": "Model"},
                "kind": "choice",
                "required": True,
                "options": ["air", "pro"],
            }
        ],
        "status": "published",
        "group_id": group.json()["id"],
    }
    staged = _staged([_person(first), _person(second)])
    made = await add_item(world, org, admin, **base, approval=staged)
    assert made.status_code == 201, made.text
    item = made.json()
    raised = await raise_request(
        world, org, requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert raised.status_code == 201, raised.text
    record = raised.json()

    await world.sql(
        "UPDATE tenant_subscriptions SET edition = 'essentials' WHERE tenant_id = $1", tenant
    )
    await world.app.state.entitlements.invalidate(tenant)  # the plan changed under it

    # In flight: both stages still decide it, on the snapshot.
    [one] = _of(await approvals(world, org, admin, record), 1)
    assert (await decide(world, org, first, record, one, "approve")).status_code == 200
    [two] = _of(await approvals(world, org, admin, record), 2)
    assert (await decide(world, org, second, record, two, "approve")).status_code == 200
    assert (await fresh(world, org, record))["approval_status"] == "approved"

    # New requests on the still-staged item: refused, labelled.
    again = await raise_request(
        world, org, requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert problem(again) == (403, "entitlement_required")

    # The item: its stages refused again, one stage allowed.
    path = f"/catalog/items/{item['id']}"
    current = (await world.call("GET", path, org, admin)).json()
    kept = await world.call(
        "PATCH",
        path,
        org,
        admin,
        json={"approval": staged},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert problem(kept) == (403, "entitlement_required")
    reduced = await world.call(
        "PATCH",
        path,
        org,
        admin,
        json={"approval": _person(first)},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert reduced.status_code == 200, reduced.text
    later = await raise_request(
        world, org, requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert later.status_code == 201, later.text
    assert await _snapshot(world, later.json()) is None  # today's single stage again
