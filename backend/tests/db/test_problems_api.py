"""Problems on the work-item engine (WP-044a s1; REQ-PRB-001..003, -009, -023). Real Postgres.

A problem is a work item of its own type: PRB display IDs from its own counter, the Appendix A
life cycle (on hold resumes where it was put on hold), the engine's permissions under
`problems.*` (technicians see every problem, create them and work their groups' ones), and
tenant isolation. Requesters never reach a problem.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import CONSOLE, Org, World, problem, role, world

__all__ = ["world"]  # the fixture, re-used

PRB = "/problems"


async def new_problem(world: World, org: Org, user: uuid.UUID, **values: Any) -> Any:  # noqa: ANN401
    body = {"subject": "Mail keeps timing out", "requester_id": str(user), **values}
    return await world.call("POST", PRB, org, user, json=body, headers=CONSOLE)


async def act(
    world: World,
    org: Org,
    user: uuid.UUID,
    record: dict[str, Any],
    action: str,
    **body: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - an httpx response
    return await world.call(
        "POST",
        f"{PRB}/{record['id']}/actions/{action}",
        org,
        user,
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
        json=body or None,
    )


async def test_a_problem_has_its_own_ids_and_stays_in_its_tenant(world: World) -> None:
    a, b = world.a, world.b
    first = await new_problem(world, a, a.tech_a, group_id=str(a.ga))
    assert first.status_code == 201, first.text
    second = await new_problem(world, a, a.tech_a, group_id=str(a.ga))
    made = first.json()
    assert (made["display_id"], second.json()["display_id"]) == ("PRB-1", "PRB-2")
    assert made["type"] == "problem"
    assert made["status"] == "new"
    incident = await world.create(a, a.admin)
    assert incident["display_id"].startswith("INC-")  # its own counter
    other = await world.call("GET", f"{PRB}/{made['id']}", b, b.admin)
    assert problem(other)[0] == 404  # RLS
    listed = await world.call("GET", PRB, b, b.admin)
    assert made["id"] not in {r["id"] for r in listed.json()["items"]}
    as_incident = await world.call("GET", f"/incidents/{made['id']}", a, a.admin)
    assert problem(as_incident)[0] == 404  # a problem is never read as an incident


async def test_the_life_cycle_and_on_hold_resuming_where_it_was(world: World) -> None:
    a = world.a
    record = (await new_problem(world, a, a.tech_a, group_id=str(a.ga))).json()

    async def move(action: str, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
        nonlocal record
        done = await act(world, a, a.tech_a, record, action, **body)
        assert done.status_code == 200, done.text
        record = dict(done.json())
        return record

    assert (await move("investigate"))["status"] == "investigating"
    refused = await act(world, a, a.tech_a, record, "hold")
    assert problem(refused)[0] == 422  # putting on hold asks for a reason
    assert (await move("hold", reason_code="more_information"))["status"] == "on_hold"
    assert record["status_category"] == "paused"
    assert (await move("resume"))["status"] == "investigating"
    assert (await move("confirm_root_cause"))["status"] == "root_cause_found"
    assert (await move("await_fix"))["status"] == "awaiting_fix"
    assert (await move("hold", reason_code="more_information"))["status"] == "on_hold"
    assert (await move("resume"))["status"] == "awaiting_fix"  # where it was, not a default
    not_here = await act(world, a, a.tech_a, record, "confirm_root_cause")
    assert problem(not_here) == (409, "invalid_transition")
    assert (await move("investigate"))["status"] == "investigating"  # the fix failed


async def test_who_may_do_what_with_problems(world: World) -> None:
    a = world.a
    mine = (await new_problem(world, a, a.admin, group_id=str(a.ga))).json()
    theirs = (await new_problem(world, a, a.admin, group_id=str(a.gb))).json()
    # Technicians see every problem (problems.view all) and create them.
    seen = await world.call("GET", PRB, a, a.tech_a)
    assert {mine["id"], theirs["id"]} <= {r["id"] for r in seen.json()["items"]}
    assert (await new_problem(world, a, a.tech_a)).status_code == 201
    # They work their groups' problems only (what "manage at group" gave them).
    assert (await act(world, a, a.tech_a, mine, "investigate")).status_code == 200
    refused = await act(world, a, a.tech_a, theirs, "investigate")
    assert problem(refused)[0] == 403
    # Delete stays with the admins.
    gone = await world.call(
        "DELETE",
        f"{PRB}/{theirs['id']}",
        a,
        a.tech_b,
        headers={"If-Match": f'"{theirs["version"]}"', **CONSOLE},
    )
    assert problem(gone)[0] == 403
    # Requesters never reach a problem.
    assert problem(await world.call("GET", PRB, a, a.requester))[0] == 403
    assert (await new_problem(world, a, a.requester)).status_code == 403


async def test_a_role_with_the_mapped_grants_works_group_problems(world: World) -> None:
    """Lane B's check: what 0077 gives a role saved with problems.manage(group) still works."""
    a = world.a
    lead = await role(
        world,
        a,
        "Problem lead",
        [
            ("problems.view", "all"),
            ("problems.create", "all"),
            ("problems.edit", "group"),
            ("problems.assign", "group"),
            ("problems.close", "group"),
        ],
    )
    granted = await world.call("PUT", f"/users/{a.requester2}/roles/{lead}", a, a.admin)
    assert granted.status_code in {200, 204}, granted.text
    await world.call("PUT", f"/organization/groups/{a.ga}/members/{a.requester2}", a, a.admin)
    record = (await new_problem(world, a, a.admin, group_id=str(a.ga))).json()
    changed = await world.call(
        "PATCH",
        f"{PRB}/{record['id']}",
        a,
        a.requester2,
        json={"subject": "Mail times out every morning"},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text


async def test_a_problem_gets_a_target_date_and_no_first_response(world: World) -> None:
    """REQ-PRB-008, Appendix A: business days by priority; response SLAs are off for problems."""
    a = world.a
    made = await new_problem(
        world, a, a.admin, group_id=str(a.ga), impact="organisation", urgency="high"
    )
    assert made.status_code == 201, made.text
    record = made.json()
    assert record["resolution_due_at"] is not None  # the target date
    assert record["first_response_due_at"] is None
    targets = await world.sql(
        "SELECT t.kind, t.priority, t.amount, t.unit FROM sla_policy_targets t"
        " JOIN sla_policies p ON p.id = t.policy_id"
        " WHERE p.tenant_id = $1 AND p.record_type = 'problem' AND p.fallback ORDER BY t.priority",
        a.tenant,
    )
    assert [(r["kind"], r["priority"], r["amount"], r["unit"]) for r in targets] == [
        ("resolution", "p1", 5, "business_days"),
        ("resolution", "p2", 10, "business_days"),
        ("resolution", "p3", 20, "business_days"),
        ("resolution", "p4", 40, "business_days"),
    ]


async def test_a_problems_own_fields(world: World) -> None:
    """REQ-PRB-005, -006: type and root cause from the tenant's lists; the outage window."""
    a = world.a
    made = await new_problem(
        world,
        a,
        a.admin,
        problem_type="proactive",
        root_cause_category="capacity_or_performance",
        outage_started_at="2026-11-04T08:00:00+05:00",
        outage_ended_at="2026-11-04T09:30:00+05:00",
    )
    assert made.status_code == 201, made.text
    record = made.json()
    assert (record["problem_type"], record["root_cause_category"]) == (
        "proactive",
        "capacity_or_performance",
    )
    wrong = await new_problem(world, a, a.admin, problem_type="sideways")
    assert {e["field"]: e["code"] for e in wrong.json()["errors"]} == {
        "body.problem_type": "invalid_choice"
    }
    backwards = await world.call(
        "PATCH",
        f"{PRB}/{record['id']}",
        a,
        a.admin,
        json={"outage_ended_at": "2026-11-04T07:00:00+05:00"},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )
    assert {e["field"]: e["code"] for e in backwards.json()["errors"]} == {
        "body.outage_ended_at": "before_start"
    }
    history = await world.sql(
        "SELECT field FROM field_changes WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        uuid.UUID(record["id"]),
    )
    assert {"problem_type", "root_cause_category"} <= {r["field"] for r in history}
    # Never on an incident.
    on_incident = await world.call(
        "POST",
        "/incidents",
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "problem_type": "reactive"},
        headers=CONSOLE,
    )
    assert {e["field"]: e["code"] for e in on_incident.json()["errors"]} == {
        "body.problem_type": "not_allowed"
    }
