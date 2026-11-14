"""Approvals on an incident (WP-046b S1; REQ-INC-083 AC1-AC4; lane B's conditions).

A technician asks named people, with a rule (any one, all, a majority); approvers decide through
the same engine as service requests (segregation of duties, comments, links); the incident's
status never moves, its approval status says how it went.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world  # noqa: F401 - fixture


async def _ask(
    world: World,  # noqa: F811 - the fixture's name
    org: Org,
    item: dict[str, Any],
    approvers: list[uuid.UUID],
    rule: str | None = None,
    user: uuid.UUID | None = None,
) -> Any:  # noqa: ANN401 - an httpx response
    body: dict[str, Any] = {"approver_ids": [str(a) for a in approvers]}
    if rule is not None:
        body["rule"] = rule
    return await world.call(
        "POST",
        f"{BASE}/{item['id']}/approvals",
        org,
        user or org.tech_a,
        json=body,
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )


async def _rows(world: World, org: Org, item: dict[str, Any]) -> list[dict[str, Any]]:  # noqa: F811
    shown = await world.call("GET", f"{BASE}/{item['id']}/approvals", org, org.admin)
    assert shown.status_code == 200, shown.text
    return list(shown.json()["items"])


async def _decide(
    world: World,  # noqa: F811
    org: Org,
    item: dict[str, Any],
    entry: dict[str, Any],
    user: uuid.UUID,
    decision: str,
) -> Any:  # noqa: ANN401 - an httpx response
    return await world.call(
        "POST",
        f"{BASE}/{item['id']}/approvals/{entry['id']}/decision",
        org,
        user,
        json={"decision": decision, **({"comment": "Not now"} if decision == "reject" else {})},
        headers={"If-Match": f'"{entry["version"]}"', **CONSOLE},
    )


async def test_under_all_every_approver_decides_and_the_status_follows(world: World) -> None:  # noqa: F811
    """AC1 every approver listed pending; AC2 decided in the app; the status never moves."""
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    asked = await _ask(world, a, item, [a.admin, a.tech_b], rule="all")
    assert asked.status_code == 200, asked.text
    assert asked.json()["approval_status"] == "pending"
    rows = await _rows(world, a, item)
    assert {r["state"] for r in rows} == {"pending"}
    assert len(rows) == 2
    by_person = {r["approver_id"]: r for r in rows}
    first = await _decide(world, a, item, by_person[str(a.admin)], a.admin, "approve")
    assert first.status_code == 200, first.text
    still = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    assert still["approval_status"] == "pending"  # "all": one approval is not enough
    second = await _decide(world, a, item, by_person[str(a.tech_b)], a.tech_b, "approve")
    assert second.status_code == 200, second.text
    done = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    assert done["approval_status"] == "approved"
    assert done["status"] == still["status"]  # its work goes on: the status never moves


async def test_under_all_one_rejection_rejects(world: World) -> None:  # noqa: F811
    """AC3: one rejection under "all" rejects at once; the others are no longer needed."""
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    assert (await _ask(world, a, item, [a.admin, a.tech_b], rule="all")).status_code == 200
    rows = {r["approver_id"]: r for r in await _rows(world, a, item)}
    rejected = await _decide(world, a, item, rows[str(a.admin)], a.admin, "reject")
    assert rejected.status_code == 200, rejected.text
    after = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    assert after["approval_status"] == "rejected"
    states = {r["approver_id"]: r["state"] for r in await _rows(world, a, item)}
    assert states[str(a.tech_b)] == "not_needed"


async def test_the_requester_never_approves_their_own_incident(world: World) -> None:  # noqa: F811
    """AC4: segregation of duties, the engine's own rule (requester and the person it is for)."""
    a = world.a
    item = await world.create(
        a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a), requester_id=str(a.tech_b)
    )
    assert (await _ask(world, a, item, [a.tech_b, a.admin])).status_code == 200
    rows = {r["approver_id"]: r for r in await _rows(world, a, item)}
    refused = await _decide(world, a, item, rows[str(a.tech_b)], a.tech_b, "approve")
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "approval_segregation"


async def test_a_problem_keeps_its_first_decision_rule(world: World) -> None:  # noqa: F811
    """A rule is the incidents' choice: a problem refuses one (its first decision decides)."""
    a = world.a
    problem = await world.call(
        "POST",
        "/problems",
        a,
        a.admin,
        json={"subject": "Mail keeps failing", "group_id": str(a.ga), "requester_id": str(a.admin)},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert problem.status_code == 201, problem.text
    item = problem.json()
    refused = await world.call(
        "POST",
        f"/problems/{item['id']}/approvals",
        a,
        a.admin,
        json={"approver_ids": [str(a.tech_b)], "rule": "all"},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert refused.status_code == 422, refused.text
