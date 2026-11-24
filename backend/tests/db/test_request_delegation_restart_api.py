"""Approval delegation and restarting approval for requests (WP-047a S3b; REQ-SR-035, -041).

Real PostgreSQL with RLS. Delegation: AC1-AC3 and the coordinator's condition 1 (eligibility,
never the requester, both dates and a cap, no chains, audited, both told). Restart: AC1-AC3 and
condition 3 (the old round voided with a reason, its approvers told, its links revoked).
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules.work_items.service import delegations
from conftest import assign_system_role
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import approvals, decide, fresh, inbox
from tests.db.test_incidents_api import CONSOLE, Org, World, problem
from tests.db.test_service_requests_api import an_item, raise_request
from tests.db.test_users_api import seed_users

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

SR = "/service-requests"
DEL = "/approval-delegations"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4()), **CONSOLE}


def _window(days: float = 7, start: float = -1) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "starts_at": (now + timedelta(days=start)).isoformat(),
        "ends_at": (now + timedelta(days=start + days)).isoformat(),
    }


async def _delegate(
    world: World,
    org: Org,
    by: uuid.UUID,
    to: uuid.UUID,
    **extra: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - the response
    return await world.call(
        "POST",
        DEL,
        org,
        by,
        json={"delegate_id": str(to), **_window(), **extra},
        headers=_key(),
    )


async def _raised(
    world: World,
    org: Org,
    approver: uuid.UUID,
    **item: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    made_item = await an_item(
        world,
        org,
        approval={"approvers": [{"kind": "person", "person_id": str(approver)}]},
        **item,
    )
    made = await raise_request(
        world, org, org.requester, catalog_item_id=made_item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _end_all(world: World, org: Org) -> None:
    """Earlier tests' delegations in the shared world are ended (one at a time per person)."""
    await world.sql(
        "UPDATE approval_delegations SET ended_at = starts_at WHERE tenant_id = $1"
        " AND ended_at IS NULL",
        org.tenant,
    )


async def test_ac1_ac2_a_delegate_gets_new_approvals_and_decides_on_behalf(world: World) -> None:
    """035 AC1: routed to the delegate and in their inbox; AC2: "A on behalf of B"."""
    a = world.a
    await _end_all(world, a)
    made = await _delegate(world, a, a.tech_a, a.tech_b, reason="Leave")
    assert made.status_code == 201, made.text
    record = await _raised(world, a, a.tech_a)
    [row] = await approvals(world, a, a.admin, record)
    assert (row["approver_id"], row["on_behalf_of_id"]) == (str(a.tech_b), str(a.tech_a))
    assert record["id"] in await inbox(world, a, a.tech_b)
    assert record["id"] in await inbox(world, a, a.tech_a)  # the approver can still act
    assert (await decide(world, a, a.tech_b, record, row, "approve")).status_code == 200
    [done] = await approvals(world, a, a.admin, record)
    assert (done["decided_by"], done["on_behalf_of_id"]) == (str(a.tech_b), str(a.tech_a))
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND action = $2",
        a.tenant,
        delegations.AUDIT_CREATED,
    )
    assert audit[0]["n"] >= 1


async def test_the_approver_can_still_decide_a_delegated_approval(world: World) -> None:
    a = world.a
    await _end_all(world, a)
    assert (await _delegate(world, a, a.tech_a, a.tech_b)).status_code == 201
    record = await _raised(world, a, a.tech_a)
    [row] = await approvals(world, a, a.admin, record)
    assert (await decide(world, a, a.tech_a, record, row, "approve")).status_code == 200


async def test_ac3_ending_it_moves_pending_approvals_back(world: World) -> None:
    a = world.a
    await _end_all(world, a)
    made = (await _delegate(world, a, a.tech_a, a.tech_b)).json()
    record = await _raised(world, a, a.tech_a)
    ended = await world.call(
        "POST",
        f"{DEL}/{made['id']}/end",
        a,
        a.tech_a,
        headers={"If-Match": f'"{made["version"]}"', **CONSOLE},
    )
    assert ended.status_code == 200, ended.text
    [row] = await approvals(world, a, a.admin, record)
    assert (row["approver_id"], row["on_behalf_of_id"], row["state"]) == (
        str(a.tech_a),
        None,
        "pending",
    )
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type ="
        " 'work_items.approval_delegation.changed'"
    )
    changes = [
        json.loads(e["envelope"])["payload"]["change"]
        for e in events
        if json.loads(e["envelope"])["payload"]["delegation_id"] == made["id"]
    ]
    assert changes == ["created", "ended"]  # both people are told each time (condition 1)


async def test_a_window_that_no_longer_covers_now_gives_approvals_back(world: World) -> None:
    """Lane C's #612 note: moved to start later, pending approvals move back; audited, both told."""
    a = world.a
    await _end_all(world, a)
    made = (await _delegate(world, a, a.tech_a, a.tech_b)).json()
    record = await _raised(world, a, a.tech_a)
    [routed] = await approvals(world, a, a.admin, record)
    assert routed["approver_id"] == str(a.tech_b)
    later = await world.call(
        "PATCH",
        f"{DEL}/{made['id']}",
        a,
        a.tech_a,
        json=_window(days=3, start=2),
        headers={"If-Match": f'"{made["version"]}"', **CONSOLE},
    )
    assert later.status_code == 200, later.text
    [row] = await approvals(world, a, a.admin, record)
    assert (row["approver_id"], row["on_behalf_of_id"]) == (str(a.tech_a), None)
    audit = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1 AND action = $2 AND object_id = $3",
        a.tenant,
        delegations.AUDIT_CHANGED,
        made["id"],
    )
    assert len(audit) == 1
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type ="
        " 'work_items.approval_delegation.changed'"
    )
    changed = [
        p
        for e in events
        if (p := json.loads(e["envelope"])["payload"])["delegation_id"] == made["id"]
        and p["change"] == "changed"
    ]
    assert [(c["delegator_id"], c["delegate_id"]) for c in changed] == [
        (str(a.tech_a), str(a.tech_b))
    ]  # the notice goes to both people (delegation_notifications)


async def test_ac3_an_expired_delegation_gives_approvals_back(world: World) -> None:
    a = world.a
    await _end_all(world, a)
    made = (await _delegate(world, a, a.tech_a, a.tech_b)).json()
    record = await _raised(world, a, a.tech_a)
    await world.sql(
        "UPDATE approval_delegations SET ends_at = now() - interval '1 minute'"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(made["id"]),
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await delegations.expire(session) >= 1
        assert await delegations.expire(session) == 0  # claimed once
    [row] = await approvals(world, a, a.admin, record)
    assert row["approver_id"] == str(a.tech_a)


async def test_condition_1_checks(world: World) -> None:
    """Never oneself, at most 90 days, one at a time, an eligible delegate; others need a right."""
    a = world.a
    await _end_all(world, a)
    assert problem(await _delegate(world, a, a.tech_a, a.tech_a))[0] == 422
    too_long = await world.call(
        "POST",
        DEL,
        a,
        a.tech_a,
        json={"delegate_id": str(a.tech_b), **_window(days=91)},
        headers=_key(),
    )
    assert problem(too_long)[0] == 422
    assert (await _delegate(world, a, a.tech_a, a.tech_b)).status_code == 201
    overlap = await _delegate(world, a, a.tech_a, a.tech_c)
    assert problem(overlap)[0] == 422
    [gone] = await seed_users(
        world.db, a.tenant, [{"user_type": "technician", "status": "disabled"}]
    )
    assert problem(await _delegate(world, a, a.tech_b, gone))[0] == 422
    for_someone = await world.call(
        "POST",
        DEL,
        a,
        a.tech_c,
        json={"delegator_id": str(a.tech_b), "delegate_id": str(a.lead), **_window()},
        headers=_key(),
    )
    assert problem(for_someone)[0] == 403
    by_admin = await world.call(
        "POST",
        DEL,
        a,
        a.admin,
        json={"delegator_id": str(a.tech_b), "delegate_id": str(a.lead), **_window()},
        headers=_key(),
    )
    assert by_admin.status_code == 201, by_admin.text


async def test_two_first_delegations_at_once_leave_one(world: World) -> None:
    """Lane B's #612 review: with no row yet, the advisory lock still makes the second wait."""
    a = world.a
    await _end_all(world, a)
    [x] = await seed_users(world.db, a.tenant, [{"user_type": "technician"}])
    first, second = await asyncio.gather(
        _delegate(world, a, a.admin, a.tech_b, delegator_id=str(x)),
        _delegate(world, a, a.admin, a.tech_c, delegator_id=str(x)),
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes == [201, 422], (first.text, second.text)  # one set, one delegation_overlaps
    rows = await world.sql(
        "SELECT count(*) AS n FROM approval_delegations WHERE tenant_id = $1 AND delegator_id = $2",
        a.tenant,
        x,
    )
    assert rows[0]["n"] == 1


async def test_a_manager_never_names_themself_someone_elses_delegate(world: World) -> None:
    """The coordinator's decision: refused (segregation of duties), and the attempt audited."""
    a = world.a
    await _end_all(world, a)
    refused = await world.call(
        "POST",
        DEL,
        a,
        a.admin,
        json={"delegator_id": str(a.tech_b), "delegate_id": str(a.admin), **_window()},
        headers=_key(),
    )
    assert problem(refused)[0] == 403
    assert refused.json()["params"]["reason"] == "delegation_self_appointed"
    audit = await world.sql(
        "SELECT outcome FROM audit_entries WHERE tenant_id = $1 AND action = $2"
        " AND outcome <> 'done'",
        a.tenant,
        delegations.AUDIT_CREATED,
    )
    assert [r["outcome"] for r in audit] == ["refused"]
    # Since #625 the refused entry names whom the attempt named (lane B's #612 nit).
    named = await world.sql(
        "SELECT details->'requested' AS requested FROM audit_entries WHERE tenant_id = $1"
        " AND action = $2 AND outcome = 'refused'",
        a.tenant,
        delegations.AUDIT_CREATED,
    )
    assert json.loads(named[0]["requested"]) == {
        "delegator_id": str(a.tech_b),
        "delegate_id": str(a.admin),
    }


async def test_vendor_support_is_never_a_delegate_or_a_delegator(world: World) -> None:
    """D-173 (lane B, the coordinator): support accounts never decide for the tenant."""
    a = world.a
    await _end_all(world, a)
    [support] = await seed_users(world.db, a.tenant, [{"user_type": "technician"}])
    await world.sql(
        "UPDATE users SET user_type = 'vendor_support' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        support,
    )
    as_delegate = await _delegate(world, a, a.tech_a, support)
    assert problem(as_delegate)[0] == 422
    as_delegator = await world.call(
        "POST",
        DEL,
        a,
        a.admin,
        json={"delegator_id": str(support), "delegate_id": str(a.tech_b), **_window()},
        headers=_key(),
    )
    assert problem(as_delegator)[0] == 422


async def test_the_requester_is_never_the_delegate(world: World) -> None:
    """Condition 1: a delegate who is the request's own person leaves it with the approver."""
    a = world.a
    await _end_all(world, a)
    await assign_system_role(world.db.admin_url, a.tenant, a.requester, "technician")
    assert (await _delegate(world, a, a.tech_a, a.requester)).status_code == 201
    record = await _raised(world, a, a.tech_a)
    [row] = await approvals(world, a, a.admin, record)
    assert (row["approver_id"], row["on_behalf_of_id"]) == (str(a.tech_a), None)


async def test_no_chains(world: World) -> None:
    """B delegates to A, A to C: B's approval goes to A, never on to C."""
    a = world.a
    await _end_all(world, a)
    assert (await _delegate(world, a, a.tech_a, a.tech_b)).status_code == 201
    assert (await _delegate(world, a, a.tech_b, a.tech_c)).status_code == 201
    record = await _raised(world, a, a.tech_a)
    [row] = await approvals(world, a, a.admin, record)
    assert row["approver_id"] == str(a.tech_b)


async def test_delegations_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    await _end_all(world, a)
    assert (await _delegate(world, a, a.tech_a, a.tech_b)).status_code == 201
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.scalar(
            text("SELECT count(*) FROM approval_delegations WHERE tenant_id = :a"),
            {"a": a.tenant},
        )
        assert seen == 0
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO approval_delegations (id, tenant_id, delegator_id, delegate_id,"
                    " starts_at, ends_at) VALUES (:i, :t, :x, :y, now(), now() + interval '1 day')"
                ),
                {"i": uuid.uuid4(), "t": a.tenant, "x": a.tech_a, "y": a.tech_b},
            )


async def _answers(
    world: World,
    org: Org,
    record: dict[str, Any],
    **body: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - the response
    now = await fresh(world, org, record)
    return await world.call(
        "PATCH",
        f"{SR}/{record['id']}/answers",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{now["version"]}"', **CONSOLE},
    )


MARKED = [
    {
        "key": "model",
        "label": {"en": "Model"},
        "kind": "choice",
        "required": True,
        "options": ["air", "pro"],
        "restarts_approval": True,
    }
]


async def test_041_ac1_ac3_a_marked_change_restarts_from_stage_1(world: World) -> None:
    """AC1: back to awaiting approval; condition 3: voided with a reason, told, links revoked."""
    a = world.a
    await _end_all(world, a)
    record = await _raised(world, a, a.tech_a, questions=MARKED)
    [first] = await approvals(world, a, a.admin, record)
    assert (await decide(world, a, a.tech_a, record, first, "approve")).status_code == 200
    assert (await fresh(world, a, record))["approval_status"] == "approved"
    changed = await _answers(world, a, record, answers={"model": "pro"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["restarted"] == ["model"]
    now = await fresh(world, a, record)
    assert (now["approval_status"], now["status"]) == ("pending", "awaiting_approval")
    rows = await approvals(world, a, a.admin, record)
    assert sorted((r["round"], r["state"]) for r in rows) == [(1, "approved"), (2, "pending")]
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE event_type = 'work_items.approval.restarted'"
    )
    [told] = [
        json.loads(e["envelope"])["payload"]
        for e in events
        if json.loads(e["envelope"])["payload"]["work_item_id"] == record["id"]
    ]
    assert (told["round"], told["approver_ids"], told["keys"]) == (2, [str(a.tech_a)], ["model"])
    assert '"pro"' not in json.dumps(told)  # the keys, never the answers
    links = await world.sql(
        "SELECT count(*) AS n FROM action_links WHERE tenant_id = $1 AND object_id = $2"
        " AND revoked_at IS NULL",
        a.tenant,
        uuid.UUID(first["id"]),
    )
    assert links[0]["n"] == 0  # the old round's link never works again


async def test_041_ac2_an_unmarked_change_restarts_nothing(world: World) -> None:
    a = world.a
    await _end_all(world, a)
    record = await _raised(world, a, a.tech_a)  # no question marked
    [first] = await approvals(world, a, a.admin, record)
    assert (await decide(world, a, a.tech_a, record, first, "approve")).status_code == 200
    changed = await _answers(world, a, record, answers={"model": "pro"})
    assert changed.json()["restarted"] == []
    assert (await fresh(world, a, record))["approval_status"] == "approved"


async def test_041_a_quantity_change_restarts_when_the_item_says_so(world: World) -> None:
    a = world.a
    await _end_all(world, a)
    made_item = await an_item(
        world,
        a,
        max_quantity=5,
        approval={
            "approvers": [{"kind": "person", "person_id": str(a.tech_a)}],
            "restart_on": ["quantity"],
        },
    )
    made = await raise_request(
        world,
        a,
        a.requester,
        catalog_item_id=made_item["id"],
        answers={"model": "air"},
        quantity=1,
    )
    record = dict(made.json())
    changed = await _answers(world, a, record, quantity=3)
    assert changed.status_code == 200, changed.text
    assert changed.json()["restarted"] == ["quantity"]
