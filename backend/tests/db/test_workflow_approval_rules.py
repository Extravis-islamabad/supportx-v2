"""A workflow's approval follows the approval rules of the record it is on (WP-048b S2 reviews).

- The D-146 chair breaks an exact majority split on a workflow's level, but only a chair who
  may: active, not the record's requester (or the person it is for), not in its segregated
  roles. Otherwise there is no chair and the split rejects (lane A's review).
- Segregation of duties (REQ-CHG-039) holds on a workflow's approval as on a stage's: a change's
  implementer is refused; under strict, every member of an implementing group (lane B's review).

Cast (tests/db/test_incidents_api.py): tech_a in GA, tech_b in GB, tech_c in both.
"""

import uuid
from typing import Any

from app.core.tenancy import TenantContext
from app.modules.automation.infra.models import Workflow, WorkflowVersion
from app.modules.automation.service import workflow_runtime
from tests.db.test_change_approval_settings import group_implements, settings
from tests.db.test_changes_api import CHG, a_change
from tests.db.test_incidents_api import CONSOLE, Org, World, world
from tests.db.test_releases_api import new_release
from tests.db.test_workflow_approvals import _deliver_result
from tests.db.test_workflow_events import _flow, _node

__all__ = ["world"]  # the fixture, re-used

REL = "/releases"


def _ask(*approvers: uuid.UUID, rule: str) -> dict[str, Any]:
    return _flow(
        _node("s", "start"),
        _node("ask", "approval", approvers={"user_ids": [str(p) for p in approvers]}, rule=rule),
        _node("yes", "end"),
        _node("no", "end"),
        links=[("s", "next", "ask"), ("ask", "approved", "yes"), ("ask", "rejected", "no")],
    )


async def _run(
    world: World, record_type: str, record_id: str, definition: dict[str, Any]
) -> uuid.UUID:
    a = world.a
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        flow = Workflow(
            tenant_id=a.tenant,
            record_type=record_type,
            name=f"Ask {uuid.uuid4().hex[:6]}",
            draft=definition,
            enabled=True,
            service_identity_id=a.admin,
            published_version=1,
        )
        session.add(flow)
        await session.flush()
        session.add(
            WorkflowVersion(
                tenant_id=a.tenant, workflow_id=flow.id, number=1, definition=definition
            )
        )
        await session.flush()
        instance = await workflow_runtime.start(
            session,
            workflow_id=flow.id,
            record_type=record_type,
            record_id=uuid.UUID(record_id),
            how="manual",
        )
        return instance.id


async def _chair(world: World, person: uuid.UUID) -> None:
    a = world.a
    current = (await world.call("GET", "/approvals/settings", a, a.admin)).json()
    set_ = await world.call(
        "PATCH",
        "/approvals/settings",
        a,
        a.admin,
        json={"chair_user_id": str(person)},
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert set_.status_code == 200, set_.text


async def _pending(world: World, base: str, record: str, person: uuid.UUID) -> dict[str, Any]:
    listed = await world.call("GET", f"{base}/{record}/approvals", world.a, world.a.admin)
    assert listed.status_code == 200, listed.text
    [row] = [
        r
        for r in listed.json()["items"]
        if r["state"] == "pending" and r["approver_id"] == str(person)
    ]
    return dict(row)


async def _vote(world: World, base: str, record: str, person: uuid.UUID, decision: str) -> Any:  # noqa: ANN401 - an httpx response
    row = await _pending(world, base, record, person)
    return await world.call(
        "POST",
        f"{base}/{record}/approvals/{row['id']}/decision",
        world.a,
        person,
        json={"decision": decision, "comment": "No" if decision == "reject" else None},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )


async def _split(
    world: World, chair: uuid.UUID | None, requester: uuid.UUID | None = None
) -> tuple[str, uuid.UUID]:
    """A release whose workflow asks tech_a and tech_b by majority; they split."""
    a = world.a
    if chair is not None:
        await _chair(world, chair)
    extra = {} if requester is None else {"requester_id": str(requester)}
    made = await new_release(world, a, a.admin, **extra)
    assert made.status_code == 201, made.text
    release = str(made.json()["id"])
    instance = await _run(world, "release", release, _ask(a.tech_a, a.tech_b, rule="majority"))
    assert (await _vote(world, REL, release, a.tech_a, "approve")).status_code == 200
    assert (await _vote(world, REL, release, a.tech_b, "reject")).status_code == 200
    return release, instance


async def _chair_rows(world: World, release: str) -> list[Any]:
    return await world.sql(
        "SELECT approver_id, state FROM work_item_approvals WHERE work_item_id = $1 AND advisory",
        uuid.UUID(release),
    )


async def test_d146_the_chair_breaks_a_workflow_s_split(world: World) -> None:
    a = world.a
    release, instance = await _split(world, chair=a.tech_c)
    [row] = await _chair_rows(world, release)
    assert (row["approver_id"], row["state"]) == (a.tech_c, "pending")  # the tie waits for them
    assert (await _vote(world, REL, release, a.tech_c, "approve")).status_code == 200
    assert (await _deliver_result(world, instance))["port"] == "approved"


async def test_a_chair_who_requested_the_record_never_breaks_its_tie(world: World) -> None:
    a = world.a
    # The chair asked for this release themself: they never decide its tie.
    release, instance = await _split(world, chair=a.tech_c, requester=a.tech_c)
    assert await _chair_rows(world, release) == []
    assert (await _deliver_result(world, instance))["port"] == "rejected"  # no chair: rejects


async def test_an_inactive_chair_leaves_no_tie_waiting(world: World) -> None:
    a = world.a
    await _chair(world, a.tech_c)
    await world.sql("UPDATE users SET status = 'disabled' WHERE id = $1", a.tech_c)
    release, instance = await _split(world, chair=None)
    assert await _chair_rows(world, release) == []
    assert (await _deliver_result(world, instance))["port"] == "rejected"


async def _change_asking(world: World, org: Org, person: uuid.UUID) -> str:
    change = await a_change(world, org)
    await _run(world, "change", str(change["id"]), _ask(person, rule="any"))
    return str(change["id"])


async def test_req_chg_039_a_change_s_implementer_may_not_approve_its_workflow_approval(
    world: World,
) -> None:
    a = world.a
    change = await a_change(world, a)
    fresh = (await world.call("GET", f"{CHG}/{change['id']}", a, a.admin)).json()
    named = await world.call(
        "PUT",
        f"{CHG}/{change['id']}/roles/implementer",
        a,
        a.admin,
        json={"user_ids": [str(a.tech_a)]},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert named.status_code == 200, named.text
    await _run(world, "change", str(change["id"]), _ask(a.tech_a, rule="any"))
    refused = await _vote(world, CHG, str(change["id"]), a.tech_a, "approve")
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "approval_segregation"


async def test_req_chg_039_strict_bars_the_implementing_group_on_a_workflow_approval(
    world: World,
) -> None:
    a = world.a
    turned = await settings(world, a, segregation_strict=True)
    assert turned["status"] == 200, turned
    change = await group_implements(world, a, await a_change(world, a))  # GA implements
    await _run(world, "change", str(change["id"]), _ask(a.tech_c, rule="any"))  # tech_c in GA
    refused = await _vote(world, CHG, str(change["id"]), a.tech_c, "approve")
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "approval_segregation"
