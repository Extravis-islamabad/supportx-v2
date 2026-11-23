"""Adjusting a request's running approval over HTTP (WP-047a S2b; REQ-SR-042).

Real PostgreSQL with RLS. A holder of `requests.modify_approvers` (the service desk manager by
default) adds an approver, replaces one (AC1: the old one withdrawn and their link dead, the new
one asked), adds a stage or reminds, each with a reason in the history and an audit entry; the
coordinator's conditions 3-5 and lane B's L1-L6 are pinned here. Without the right the screen
learns why (AC2) and the server refuses.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.errors import PermissionDenied
from app.core.tenancy import TenantContext
from app.modules.audit import WORKER
from app.modules.identity_access.service.policy import for_key
from app.modules.work_items.infra.models import WorkItemApproval
from app.modules.work_items.service import approver_changes
from app.modules.work_items.service.approvals import issue_links
from conftest import assign_system_role
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_approvals_api import approvals, decide, fresh
from tests.db.test_incidents_api import CONSOLE, Org, World, problem, role
from tests.db.test_service_requests_api import an_item, raise_request
from tests.db.test_users_api import seed_users

pytestmark = MODULE_LOOP
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

SR = "/service-requests"
WHY = "Finance asked for a second look"


def _person(user: uuid.UUID, **stage: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"approvers": [{"kind": "person", "person_id": str(user)}], **stage}


async def _manager(world: World, org: Org) -> uuid.UUID:
    """A fresh service desk manager of the org (they hold the right by default)."""
    [sdm] = await seed_users(world.db, org.tenant, [{"user_type": "technician"}])
    await assign_system_role(world.db.admin_url, org.tenant, sdm, "service_desk_manager")
    return sdm


async def _raised(world: World, org: Org, stages: list[dict[str, Any]]) -> dict[str, Any]:
    approval = (
        {"approvers": stages[0]["approvers"], "stages": stages} if len(stages) > 1 else stages[0]
    )
    item = await an_item(world, org, approval=approval)
    made = await raise_request(
        world, org, org.requester, catalog_item_id=item["id"], answers={"model": "air"}
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _act(
    world: World,
    org: Org,
    user: uuid.UUID,
    record: dict[str, Any],
    path: str,
    **body: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - the response
    current = await fresh(world, org, record)
    return await world.call(
        "POST",
        f"{SR}/{record['id']}/approvals/{path}",
        org,
        user,
        json={"reason": WHY, **body},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )


def _of(entries: list[dict[str, Any]], stage: int) -> list[dict[str, Any]]:
    return [e for e in entries if e["stage"] == stage]


async def _listed(world: World, org: Org, user: uuid.UUID, record: dict[str, Any]) -> Any:  # noqa: ANN401 - JSON
    got = await world.call("GET", f"{SR}/{record['id']}/approvals", org, user)
    assert got.status_code == 200, got.text
    return got.json()


async def _history(world: World, org: Org, record: dict[str, Any], field: str) -> list[Any]:
    rows = await world.sql(
        "SELECT new_value, reason FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = $3 ORDER BY occurred_at",
        org.tenant,
        uuid.UUID(record["id"]),
        field,
    )
    return [(json.loads(r["new_value"]), r["reason"]) for r in rows]


async def test_adding_an_approver_asks_them_with_the_reason_recorded(world: World) -> None:
    a = world.a
    sdm = await _manager(world, a)
    record = await _raised(world, a, [_person(a.tech_a), _person(a.tech_c)])
    added = await _act(world, a, sdm, record, "approvers", stage=1, approver_id=str(a.tech_b))
    assert added.status_code == 200, added.text
    first = _of(added.json()["items"], 1)
    assert {(e["approver_id"], e["state"]) for e in first} == {
        (str(a.tech_a), "pending"),
        (str(a.tech_b), "pending"),
    }
    [(said, reason)] = await _history(world, a, record, "approvers")
    assert (said["action"], said["stage"], reason) == ("added", 1, WHY)
    audit = await world.sql(
        "SELECT details, actor_id FROM audit_entries WHERE tenant_id = $1 AND action = $2"
        " AND object_id = $3",
        a.tenant,
        "service_request.approvers_modified",
        record["id"],
    )
    [entry] = audit
    assert json.loads(entry["details"])["approver_id"] == str(a.tech_b)  # IDs, never names
    new = next(e for e in first if e["approver_id"] == str(a.tech_b))
    assert (await decide(world, a, a.tech_b, record, new, "approve")).status_code == 200
    assert len(_of(await approvals(world, a, a.admin, record), 2)) == 1  # stage 1 passed


async def test_who_may_never_be_named(world: World) -> None:
    """Lane B's L1 (never the actor) and the coordinator's condition 3 (never the requester or
    the person it is for, never someone already on the stage); a closed stage is refused."""
    a = world.a
    sdm = await _manager(world, a)
    record = await _raised(world, a, [_person(a.tech_a), _person(a.tech_c)])
    cases = {
        sdm: "approver_not_eligible",  # L1: whoever changes it never names themself
        a.requester: "approver_is_requester",
        a.tech_a: "approver_already_named",
        uuid.uuid4(): "approver_not_eligible",  # nobody here; the ID is never echoed
    }
    for person, code in cases.items():
        refused = await _act(world, a, sdm, record, "approvers", stage=1, approver_id=str(person))
        assert refused.status_code == 422, refused.text
        assert [e["code"] for e in refused.json()["errors"]] == [code], person
        assert str(person) not in refused.text
    later = await _act(world, a, sdm, record, "approvers", stage=2, approver_id=str(a.tech_b))
    assert [e["code"] for e in later.json()["errors"]] == ["stage_not_open"]


async def test_replacing_withdraws_the_old_approver_and_kills_their_link(world: World) -> None:
    """AC1 and lane B's L4: the old approval is `replaced` and its link answers as unknown,
    deciding nothing; the new person is asked; a decided approval is never replaced (L2)."""
    a = world.a
    sdm = await _manager(world, a)
    record = await _raised(world, a, [_person(a.tech_a), _person(a.tech_c)])
    [old] = _of(await approvals(world, a, a.admin, record), 1)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        row = await session.scalar(
            select(WorkItemApproval).where(WorkItemApproval.id == uuid.UUID(old["id"]))
        )
        assert row is not None
        token = (await issue_links(session, [row]))[row.id]
    swapped = await _act(world, a, sdm, record, f"{old['id']}/replace", approver_id=str(a.tech_b))
    assert swapped.status_code == 200, swapped.text
    first = {e["approver_id"]: e["state"] for e in _of(swapped.json()["items"], 1)}
    assert first == {str(a.tech_a): "replaced", str(a.tech_b): "pending"}
    used = await world.call(
        "POST",
        "/action-links/use",
        a,
        a.tech_a,
        json={"token": token, "body": {"decision": "approve"}},
        headers=CONSOLE,
    )
    assert problem(used) == (409, "action_link_revoked")  # the labelled "no longer valid"
    assert (await fresh(world, a, record))["approval_status"] == "pending"  # no decision
    [(said, reason)] = await _history(world, a, record, "approvers")
    assert (said["action"], said["replaced_id"], reason) == ("replaced", str(a.tech_a), WHY)

    new = next(e for e in swapped.json()["items"] if e["approver_id"] == str(a.tech_b))
    assert (await decide(world, a, a.tech_b, record, new, "approve")).status_code == 200
    again = await _act(world, a, sdm, record, f"{new['id']}/replace", approver_id=str(a.tech_c))
    assert problem(again) == (409, "approval_closed")  # L2: a decided row is never rewritten


async def test_a_stage_added_opens_after_the_others(world: World) -> None:
    """A stage after the last; on today's single stage the open one becomes stage 1 as is."""
    a = world.a
    sdm = await _manager(world, a)
    record = await _raised(world, a, [_person(a.tech_a)])  # today's single stage
    added = await _act(world, a, sdm, record, "stages", approver_ids=[str(a.tech_b)], rule="any")
    assert added.status_code == 200, added.text
    assert {e["stage"] for e in added.json()["items"]} == {1}  # not open yet
    [first] = _of(added.json()["items"], 1)
    assert (await decide(world, a, a.tech_a, record, first, "approve")).status_code == 200
    assert (await fresh(world, a, record))["approval_status"] == "pending"
    [second] = _of(await approvals(world, a, a.admin, record), 2)
    assert second["approver_id"] == str(a.tech_b)
    assert (await decide(world, a, a.tech_b, record, second, "approve")).status_code == 200
    assert (await fresh(world, a, record))["approval_status"] == "approved"

    full = await _raised(world, a, [_person(a.tech_c)] * 10)
    capped = await _act(world, a, sdm, full, "stages", approver_ids=[str(a.tech_b)])
    assert [e["code"] for e in capped.json()["errors"]] == ["too_many_stages"]


async def test_reminders_are_limited_and_never_reach_a_replaced_approver(world: World) -> None:
    """The coordinator's condition 5 and lane B's L6: checked on the server, in the history."""
    a = world.a
    sdm = await _manager(world, a)
    record = await _raised(world, a, [_person(a.tech_a), _person(a.tech_c)])
    [old] = _of(await approvals(world, a, a.admin, record), 1)
    swapped = await _act(world, a, sdm, record, f"{old['id']}/replace", approver_id=str(a.tech_b))
    assert swapped.status_code == 200, swapped.text

    async def opened(approval_id: str) -> int:
        rows = await world.sql(
            "SELECT envelope FROM outbox_events WHERE event_type = 'work_items.approval.changed'"
        )
        return sum(
            1
            for r in rows
            if json.loads(r["envelope"])["payload"]["approval_id"] == approval_id
            and json.loads(r["envelope"])["payload"]["change"] == "opened"
        )

    new = next(e for e in swapped.json()["items"] if e["state"] == "pending")
    before_old, before_new = await opened(old["id"]), await opened(new["id"])
    reminded = await _act(world, a, sdm, record, "reminders")
    assert reminded.status_code == 200, reminded.text
    assert (await opened(old["id"]), await opened(new["id"])) == (before_old, before_new + 1)
    [(said, reason)] = await _history(world, a, record, "approval_reminder")
    assert (said["count"], reason) == (1, WHY)
    soon = await _act(world, a, sdm, record, "reminders")
    assert problem(soon) == (409, "reminded_recently")


async def test_without_the_right_the_screen_learns_why_and_the_server_refuses(
    world: World,
) -> None:
    """AC2 and lane B's L3: the reason comes with the approvals; a record the actor cannot
    see is 404 before any 403 (here another tenant's manager: their right never reaches it)."""
    a, b = world.a, world.b
    sdm = await _manager(world, a)
    record = await _raised(world, a, [_person(a.tech_a), _person(a.tech_c)])
    assert (await _listed(world, a, sdm, record))["modify_refused"] is None
    assert (await _listed(world, a, a.tech_b, record))["modify_refused"] == "no_permission"
    refused = await _act(
        world, a, a.tech_b, record, "approvers", stage=1, approver_id=str(a.tech_c)
    )
    assert refused.status_code == 403, refused.text
    other = await _manager(world, b)
    hidden = await world.call(
        "POST",
        f"{SR}/{record['id']}/approvals/reminders",
        b,
        other,
        json={"reason": WHY},
        headers={"If-Match": '"1"', **CONSOLE},
    )
    assert hidden.status_code == 404, hidden.text


async def test_nothing_changes_once_the_approval_is_decided(world: World) -> None:
    """The coordinator's condition 4: decided (or closed or cancelled) is refused, labelled."""
    a = world.a
    sdm = await _manager(world, a)
    record = await _raised(world, a, [_person(a.tech_a)])
    [entry] = await approvals(world, a, a.admin, record)
    assert (await decide(world, a, a.tech_a, record, entry, "approve")).status_code == 200
    assert (await _listed(world, a, sdm, record))["modify_refused"] == "approval_not_running"
    for path, body in (
        ("approvers", {"stage": 1, "approver_id": str(a.tech_b)}),
        ("stages", {"approver_ids": [str(a.tech_b)]}),
        ("reminders", {}),
    ):
        refused = await _act(world, a, sdm, record, path, **body)
        assert problem(refused) == (409, "approval_not_running"), path


async def test_an_ad_hoc_approval_on_a_request_never_moves_it(world: World) -> None:
    """REQ-SR-042: asked as on an incident (REQ-INC-083), apart from the item's approval."""
    a = world.a
    sdm = await _manager(world, a)
    record = await _raised(world, a, [_person(a.tech_a)])
    [entry] = await approvals(world, a, a.admin, record)
    assert (await decide(world, a, a.tech_a, record, entry, "approve")).status_code == 200
    moved = await fresh(world, a, record)
    asked = await world.call(
        "POST",
        f"{SR}/{record['id']}/approvals",
        a,
        sdm,
        json={"approver_ids": [str(a.tech_b)], "rule": "any"},
        headers={"If-Match": f'"{moved["version"]}"', **CONSOLE},
    )
    assert asked.status_code == 200, asked.text
    extra = next(e for e in await approvals(world, a, a.admin, record) if e["stage"] == 2)
    assert extra["approver_id"] == str(a.tech_b)
    assert (await decide(world, a, a.tech_b, record, extra, "reject", "No")).status_code == 200
    after = await fresh(world, a, record)
    assert after["status"] == moved["status"]  # the request's own status never moves
    assert after["approval_status"] == "rejected"
    refused = await world.call(
        "POST",
        f"{SR}/{record['id']}/approvals",
        a,
        a.tech_b,
        json={"approver_ids": [str(a.tech_c)]},
        headers={"If-Match": f'"{after["version"]}"', **CONSOLE},
    )
    assert refused.status_code == 403, refused.text


async def test_an_api_key_needs_its_own_write_scope(world: World) -> None:
    """Lane B's L5: the owner's role default reaches a key only through the key's scopes."""
    a = world.a
    sdm = await _manager(world, a)
    record = await _raised(world, a, [_person(a.tech_a), _person(a.tech_c)])
    owner = await world.app.state.policy.subject(a.tenant, sdm)
    current = await fresh(world, a, record)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        reader = for_key(owner, frozenset({"requests:read"}))
        with pytest.raises(PermissionDenied):
            await approver_changes.remind(
                session,
                reader,
                uuid.UUID(record["id"]),
                reason=WHY,
                expected_version=current["version"],
                source="api",
                facts=WORKER,
            )
        writer = for_key(owner, frozenset({"requests:write", "requests:read"}))
        reminded = await approver_changes.remind(
            session,
            writer,
            uuid.UUID(record["id"]),
            reason=WHY,
            expected_version=current["version"],
            source="api",
            facts=WORKER,
        )
        assert reminded == 1


async def test_each_action_is_a_new_version_so_a_stale_if_match_is_refused(world: World) -> None:
    """Rule 5g (lane B's #593 review): two calls with the same If-Match never both apply."""
    a = world.a
    sdm = await _manager(world, a)
    record = await _raised(world, a, [_person(a.tech_a), _person(a.tech_c)])
    seen = (await fresh(world, a, record))["version"]

    async def add_stage() -> Any:  # noqa: ANN401 - the response
        return await world.call(
            "POST",
            f"{SR}/{record['id']}/approvals/stages",
            a,
            sdm,
            json={"reason": WHY, "approver_ids": [str(a.tech_b)]},
            headers={"If-Match": f'"{seen}"', **CONSOLE},
        )

    first = await add_stage()
    assert first.status_code == 200, first.text
    assert first.headers["ETag"] == f'"{seen + 1}"'  # the next If-Match
    assert (await fresh(world, a, record))["version"] == seen + 1
    again = await add_stage()
    assert problem(again) == (409, "version_conflict")
    rows = await world.sql(
        "SELECT approval_stages FROM work_items WHERE id = $1", uuid.UUID(record["id"])
    )
    stored = rows[0]["approval_stages"]
    stored = json.loads(stored) if isinstance(stored, str) else stored
    assert len(stored["stages"]) == 3  # one stage added, never two


async def test_a_right_that_does_not_reach_the_request_is_404_not_403(world: World) -> None:
    """Lane B's L3 within one tenant: a manager scoped to their groups, none of them the
    request's, gets 404 (the request is not theirs to know of), never a 403 that would say it
    exists."""
    a = world.a
    [scoped] = await seed_users(world.db, a.tenant, [{"user_type": "technician"}])
    made = await role(
        world,
        a,
        f"Group approvals {uuid.uuid4().hex[:6]}",
        [("requests.view", "group"), ("requests.modify_approvers", "group")],
    )
    assigned = await world.call("PUT", f"/users/{scoped}/roles/{made}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    record = await _raised(world, a, [_person(a.tech_a), _person(a.tech_c)])
    hidden = await _act(world, a, scoped, record, "reminders")
    assert hidden.status_code == 404, hidden.text
