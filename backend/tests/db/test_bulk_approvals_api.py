"""Approve several at once from the portal inbox (WP-032 D6; REQ-PRT-008). Real Postgres.

One comment for all after the confirmation, each one a decision of its own (audited); one
withdrawn meanwhile is skipped with the reason; never more than 20; no bulk reject; the
decided list shows them afterwards.
"""

import uuid
from typing import Any

from tests.db.test_approvals_api import approvals, manager_of, waiting
from tests.db.test_incidents_api import CONSOLE, World, field_codes, world

__all__ = ["world"]  # the fixture, re-used

SR = "/service-requests"


async def test_approving_three_at_once_with_one_comment(world: World) -> None:
    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    records = [await waiting(world, a) for _ in range(4)]
    refs: list[dict[str, Any]] = []
    for record in records:
        [entry] = await approvals(world, a, a.tech_a, record)
        refs.append(
            {"record_id": record["id"], "approval_id": entry["id"], "version": entry["version"]}
        )
    # The fourth is withdrawn by its requester before the approver confirms.
    last = records[3]
    withdrawn = await world.call(
        "POST",
        f"{SR}/{last['id']}/withdraw",
        a,
        a.requester,
        headers={"If-Match": f'"{last["version"]}"', **CONSOLE},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    done = await world.call(
        "POST",
        f"{SR}/approvals/decisions",
        a,
        a.tech_a,
        json={"items": refs, "comment": "Budget approved for Q4"},
    )
    assert done.status_code == 200, done.text
    outcomes = {i["record_id"]: (i["decided"], i["code"]) for i in done.json()["items"]}
    assert [outcomes[r["id"]][0] for r in records[:3]] == [True, True, True]
    assert outcomes[last["id"]][0] is False  # withdrawn meanwhile: skipped, with why
    assert outcomes[last["id"]][1] is not None
    for record in records[:3]:
        [entry] = await approvals(world, a, a.tech_a, record)
        assert (entry["state"], entry["comment"]) == ("approved", "Budget approved for Q4")
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'service_request.approval_decided' AND outcome = 'done'",
        a.tenant,
    )
    assert audit[0]["n"] == 3  # one entry per decision
    decided = await world.call("GET", f"{SR}/my-approvals/decided", a, a.tech_a)
    assert {i["record_id"] for i in decided.json()["items"]} == {r["id"] for r in records[:3]}
    assert (await world.call("GET", f"{SR}/my-approvals", a, a.tech_a)).json()["items"] == []


async def test_not_more_than_twenty_and_nobody_else_s_approvals(world: World) -> None:
    a = world.a
    too_many = [
        {"record_id": str(uuid.uuid4()), "approval_id": str(uuid.uuid4()), "version": 1}
        for _ in range(21)
    ]
    refused = await world.call(
        "POST", f"{SR}/approvals/decisions", a, a.tech_a, json={"items": too_many}
    )
    assert field_codes(refused) == {"items": "too_many_records"}
    await manager_of(world, a.requester, a.tech_a)
    record = await waiting(world, a)
    [entry] = await approvals(world, a, a.tech_a, record)
    ref = {"record_id": record["id"], "approval_id": entry["id"], "version": entry["version"]}
    other = await world.call(
        "POST", f"{SR}/approvals/decisions", a, a.tech_b, json={"items": [ref]}
    )
    assert other.status_code == 200, other.text
    assert other.json()["items"][0]["decided"] is False  # not their approval
    [still] = await approvals(world, a, a.tech_a, record)
    assert still["state"] == "pending"
