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


async def test_approvers_are_asked_by_mail_and_the_technician_hears_of_a_rejection(
    world: World,  # noqa: F811
) -> None:
    """AC2/AC3: each approver gets their own one-time link (D-132's path, the marker stored,
    never a token); the technician is told once the rule has rejected it, not at every vote."""
    from tests.db.test_notifications_api import MAIL, run_engine  # noqa: PLC0415 - one test

    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    assert (await _ask(world, a, item, [a.admin, a.tech_b], rule="majority")).status_code == 200
    await run_engine(world, a, settings=MAIL)
    asked = await world.sql(
        "SELECT d.user_id, m.text_body FROM notification_deliveries d"
        " JOIN mail_messages m ON m.id = d.mail_id"
        " WHERE d.tenant_id = $1 AND d.record_id = $2 AND d.channel = 'email'"
        " AND d.event_code = 'incident.approval_requested'",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    mailed = {r["user_id"]: r["text_body"] for r in asked}
    # tech_b works another group: an approver need not see the incident to be asked.
    assert set(mailed) == {a.admin, a.tech_b}
    assert all("[[supportx-link:approval_link]]" in body for body in mailed.values())
    rows = {r["approver_id"]: r for r in await _rows(world, a, item)}
    # Majority of two: one rejection leaves it undecided (nobody told), the second decides.
    assert (await _decide(world, a, item, rows[str(a.admin)], a.admin, "reject")).status_code == 200
    await run_engine(world, a, settings=MAIL)
    told = await world.sql(
        "SELECT user_id FROM notification_deliveries WHERE tenant_id = $1 AND record_id = $2"
        " AND event_code = 'incident.approval_rejected'",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    pending = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    if pending["approval_status"] == "pending":
        assert told == []
        second = await _decide(world, a, item, rows[str(a.tech_b)], a.tech_b, "reject")
        assert second.status_code == 200, second.text
        await run_engine(world, a, settings=MAIL)
        told = await world.sql(
            "SELECT user_id FROM notification_deliveries WHERE tenant_id = $1"
            " AND record_id = $2 AND event_code = 'incident.approval_rejected'",
            a.tenant,
            uuid.UUID(item["id"]),
        )
    assert {r["user_id"] for r in told} == {a.tech_a}


async def test_a_decision_link_is_bound_and_keeps_segregation(world: World) -> None:  # noqa: F811
    """Lane B: the same D-132 link and handler as requests; a link names one approval and one
    person (no one else, no other approval decides with it), and segregation of duties holds on
    the link path as in the app."""
    import pytest  # noqa: PLC0415 - one test

    from app.core.errors import AppError  # noqa: PLC0415
    from app.core.tenancy import TenantContext  # noqa: PLC0415
    from app.modules.work_items.service import approvals  # noqa: PLC0415
    from app.shared import action_links  # noqa: PLC0415

    a = world.a
    item = await world.create(
        a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a), requester_id=str(a.tech_b)
    )
    assert (await _ask(world, a, item, [a.tech_b, a.admin])).status_code == 200
    rows = {r["approver_id"]: r for r in await _rows(world, a, item)}
    database = world.app.state.db

    async def issued(person: uuid.UUID) -> str:
        row = rows[str(person)]
        (stored,) = await world.sql(
            "SELECT version FROM work_item_approvals WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            uuid.UUID(row["id"]),
        )
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            return await action_links.issue(
                session,
                recipient_id=person,
                action=approvals.LINK_ACTION,
                object_type=approvals.LINK_OBJECT,
                object_id=uuid.UUID(row["id"]),
                object_version=stored["version"],
            )

    async def used(secret: str, person: uuid.UUID) -> Any:  # noqa: ANN401 - the handler's answer
        subject = await world.app.state.policy.subject(a.tenant, person)
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            return await action_links.use(session, secret, subject, {"decision": "approve"})

    own = await issued(a.tech_b)
    # Segregation of duties on the link path: the engine refuses, and the shared link service
    # answers as for requests ("no longer yours to decide"); nothing is decided.
    with pytest.raises(AppError):
        await used(own, a.tech_b)
    still = {r["approver_id"]: r["state"] for r in await _rows(world, a, item)}
    assert still[str(a.tech_b)] == "pending"
    admins = await issued(a.admin)
    with pytest.raises(AppError):  # bound to its recipient: nobody else uses it
        await used(admins, a.tech_a)
    await used(admins, a.admin)
    states = {r["approver_id"]: r["state"] for r in await _rows(world, a, item)}
    assert states == {str(a.admin): "approved", str(a.tech_b): "not_needed"}
    after = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    assert after["approval_status"] == "approved"


async def test_an_erased_approver_s_pending_approval_goes_to_the_administrators(
    world: World,  # noqa: F811
) -> None:
    """Lane B: the 0166 reroute (`approver_erased`) covers incident approvals too; never granted."""
    from app.modules.work_items.service.person_data import REFERENCES  # noqa: PLC0415
    from tests.db.test_erasure_ports_lane_a import _erase  # noqa: PLC0415 - the shared runner

    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    assert (await _ask(world, a, item, [a.tech_b])).status_code == 200
    await _erase(world, a.tenant, a.tech_b, REFERENCES)
    rows = await world.sql(
        "SELECT approver_id, origin, state, route_reason FROM work_item_approvals"
        " WHERE tenant_id = $1 AND work_item_id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    pending = [r for r in rows if r["state"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["approver_id"] is None  # the approval administrators hold it
    assert pending[0]["route_reason"] == "approver_erased"
    assert all(r["state"] != "approved" for r in rows)
