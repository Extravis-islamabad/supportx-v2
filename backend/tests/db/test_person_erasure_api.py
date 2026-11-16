"""GDPR erasure requests and legal hold over HTTP (D-171, ADR-052 S1).

- Admin A requests; admin B approves. Until the mentions report ships (S1b) every approval is
  refused with `erasure_report_unavailable`, and nothing changes: no erasure can run.
- Refusals, each with its labelled code: yourself, the last tenant admin, a break-glass account,
  a person on legal hold, a second open erasure, an expired request, the requester approving.
- Legal hold: set and lifted under `audit.manage_holds`, If-Match, audited with the reason.
- Every step is audited; other tenants see nothing.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.core.tenancy import TenantContext
from app.modules.identity_access.service import erasure_job
from conftest import assign_system_role
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import Org, World, role

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the incidents fixture, re-used


async def _name(world: World, org: Org, user: uuid.UUID) -> str:
    rows = await world.sql(
        "SELECT display_name FROM users WHERE tenant_id = $1 AND id = $2", org.tenant, user
    )
    return str(rows[0]["display_name"])


async def _version(world: World, org: Org, user: uuid.UUID) -> int:
    rows = await world.sql(
        "SELECT version FROM users WHERE tenant_id = $1 AND id = $2", org.tenant, user
    )
    return int(rows[0]["version"])


async def _request(
    world: World,
    org: Org,
    by: uuid.UUID,
    person: uuid.UUID,
    **body: Any,  # noqa: ANN401 - JSON overrides
) -> httpx.Response:
    payload: dict[str, Any] = {
        "reason_code": "subject_request",
        "reason_text": "Asked by e-mail, ticket REQ-12",
        "successor_id": str(org.tech_b),
        "confirm_name": await _name(world, org, person),
        **body,
    }
    return await world.call(
        "POST",
        f"/people/{person}/erasure",
        org,
        by,
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )


async def _second_admin(world: World, org: Org) -> uuid.UUID:
    await assign_system_role(world.db.admin_url, org.tenant, org.lead, "tenant_admin")
    return org.lead


async def _audit(world: World, org: Org, action: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT outcome, reason_code, object_id, details FROM audit_entries"
        " WHERE tenant_id = $1 AND action = $2 ORDER BY occurred_at",
        org.tenant,
        action,
    )
    return [{**dict(row), "details": json.loads(row["details"])} for row in rows]


def _code(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


async def test_request_then_every_approval_is_refused_until_the_report_ships(
    world: World,
) -> None:
    a = world.a
    approver = await _second_admin(world, a)
    asked = await _request(world, a, a.admin, a.tech_a)
    assert asked.status_code == 201, asked.text
    erasure = asked.json()
    assert (erasure["state"], erasure["step"], erasure["steps"]) == ("requested", 0, 8)
    assert erasure["report_ready"] is False
    assert asked.headers["ETag"] == '"1"'
    (logged,) = await _audit(world, a, "person.erasure_requested")
    assert logged["object_id"] == str(a.tech_a)
    assert logged["details"]["erasure_id"] == erasure["id"]
    assert logged["details"]["reason_code"] == "subject_request"

    approved = await world.call(
        "POST",
        f"/erasures/{erasure['id']}/approve",
        a,
        approver,
        json={"confirm_name": await _name(world, a, a.tech_a)},
        headers={"If-Match": '"1"'},
    )
    assert _code(approved) == (409, "erasure_report_unavailable")
    # Nothing moved: the row, the person and the outbox are as before.
    shown = (await world.call("GET", f"/erasures/{erasure['id']}", a, a.admin)).json()
    assert (shown["state"], shown["approved_by"], shown["version"]) == ("requested", None, 1)
    person = await world.sql(
        "SELECT status, erased_at FROM users WHERE tenant_id = $1 AND id = $2", a.tenant, a.tech_a
    )
    assert (person[0]["status"], person[0]["erased_at"]) == ("active", None)
    states = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2",
        a.tenant,
        "identity_access.person_erasure.changed",
    )
    assert [json.loads(e["envelope"])["payload"]["state"] for e in states] == ["requested"]
    (refused,) = await _audit(world, a, "person.erasure_approved")
    assert (refused["outcome"], refused["reason_code"]) == ("failed", "erasure_report_unavailable")
    # And the job will not run it either, now or after a forged approval without the report.
    erasure_id = uuid.UUID(erasure["id"])
    db = world.app.state.db
    outcome = await erasure_job.run_erasure(db, a.tenant, erasure_id, erasure_job.JobEffects())
    assert (outcome.state, outcome.step) == ("requested", 0)
    await world.sql(
        "UPDATE person_erasures SET state = 'approved', approved_by = $3, approved_at = now()"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        erasure_id,
        approver,
    )
    outcome = await erasure_job.run_erasure(db, a.tenant, erasure_id, erasure_job.JobEffects())
    assert (outcome.state, outcome.error_code) == ("failed", "erasure_report_unavailable")
    person = await world.sql(
        "SELECT status FROM users WHERE tenant_id = $1 AND id = $2", a.tenant, a.tech_a
    )
    assert person[0]["status"] == "active"  # refused before the freeze: nothing was touched


async def test_the_requester_cannot_approve_their_own_request(world: World) -> None:
    a = world.a
    erasure = (await _request(world, a, a.admin, a.tech_a)).json()
    approved = await world.call(
        "POST",
        f"/erasures/{erasure['id']}/approve",
        a,
        a.admin,
        json={"confirm_name": await _name(world, a, a.tech_a)},
        headers={"If-Match": '"1"'},
    )
    assert _code(approved) == (409, "erasure_needs_another_admin")


async def test_erasing_yourself_is_refused(world: World) -> None:
    a = world.a
    assert _code(await _request(world, a, a.admin, a.admin)) == (409, "erasure_of_self")


async def test_the_last_tenant_admin_is_never_erased(world: World) -> None:
    a = world.a
    eraser = await role(world, a, "Privacy officer", [("people.erase", "all")])
    assigned = await world.call("PUT", f"/users/{a.lead}/roles/{eraser}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    assert _code(await _request(world, a, a.lead, a.admin)) == (409, "last_tenant_admin")


async def test_a_break_glass_account_is_never_erased(world: World) -> None:
    a = world.a
    await world.sql(
        "UPDATE users SET break_glass = true WHERE tenant_id = $1 AND id = $2", a.tenant, a.tech_a
    )
    assert _code(await _request(world, a, a.admin, a.tech_a)) == (
        409,
        "erasure_break_glass_account",
    )


async def test_a_held_person_is_refused_and_the_hold_is_audited(world: World) -> None:
    a = world.a
    held = await world.call(
        "PUT",
        f"/people/{a.tech_a}/legal-hold",
        a,
        a.admin,
        json={"reason": "Litigation hold, case 2026-14"},
        headers={"If-Match": f'"{await _version(world, a, a.tech_a)}"'},
    )
    assert held.status_code == 200, held.text
    assert held.json()["held"] is True
    assert held.json()["held_by"] == str(a.admin)
    assert held.headers["ETag"] == f'"{held.json()["version"]}"'
    assert _code(await _request(world, a, a.admin, a.tech_a)) == (409, "person_on_legal_hold")
    (logged,) = await _audit(world, a, "person.legal_hold_set")
    assert (logged["outcome"], logged["object_id"]) == ("done", str(a.tech_a))

    stale = await world.call(
        "POST",
        f"/people/{a.tech_a}/legal-hold/lift",
        a,
        a.admin,
        json={"reason": "Case closed"},
        headers={"If-Match": '"1"'},
    )
    assert stale.status_code == 409
    lifted = await world.call(
        "POST",
        f"/people/{a.tech_a}/legal-hold/lift",
        a,
        a.admin,
        json={"reason": "Case closed"},
        headers={"If-Match": f'"{held.json()["version"]}"'},
    )
    assert lifted.status_code == 200, lifted.text
    assert lifted.json()["held"] is False
    again = await world.call(
        "POST",
        f"/people/{a.tech_a}/legal-hold/lift",
        a,
        a.admin,
        json={},
        headers={"If-Match": f'"{lifted.json()["version"]}"'},
    )
    assert _code(again) == (409, "legal_hold_not_set")
    lifts = await _audit(world, a, "person.legal_hold_lifted")
    assert [(e["outcome"], e["reason_code"]) for e in lifts] == [
        ("failed", "version_conflict"),
        ("done", None),
        ("failed", "legal_hold_not_set"),
    ]
    assert (await _request(world, a, a.admin, a.tech_a)).status_code == 201


async def test_holds_need_their_right(world: World) -> None:
    a = world.a
    refused = await world.call(
        "PUT",
        f"/people/{a.tech_b}/legal-hold",
        a,
        a.tech_a,
        json={"reason": "x"},
        headers={"If-Match": '"1"'},
    )
    assert refused.status_code == 403
    erasure = await _request(world, a, a.tech_a, a.tech_b)
    assert erasure.status_code == 403
    assert (await world.call("GET", "/erasures", a, a.tech_a)).status_code == 403


async def test_a_second_open_erasure_is_refused(world: World) -> None:
    a = world.a
    first = await _request(world, a, a.admin, a.tech_a)
    assert first.status_code == 201
    second = await _request(world, a, a.admin, a.tech_a)
    assert _code(second) == (409, "erasure_already_open")
    assert second.json()["params"]["erasure_id"] == first.json()["id"]


async def test_the_request_checks_name_successor_and_kept_files(world: World) -> None:
    a = world.a
    wrong = await _request(
        world,
        a,
        a.admin,
        a.tech_a,
        confirm_name="Somebody Else",
        successor_id=str(a.tech_a),
        keep_files={str(uuid.uuid4()): "Contract evidence"},
    )
    assert wrong.status_code == 422, wrong.text
    codes = {e["field"]: e["code"] for e in wrong.json()["errors"]}
    assert codes["body.confirm_name"] == "erasure_confirm_name_mismatch"
    assert codes["body.successor_id"] == "erasure_successor_is_person"
    assert set(codes.values()) >= {"erasure_keep_file_unknown"}
    gone = await _request(world, a, a.admin, a.tech_a, successor_id=str(world.b.tech_b))
    assert {e["code"] for e in gone.json()["errors"]} == {"erasure_successor_not_active"}


async def test_expired_requests_cannot_be_approved_and_the_schedule_marks_them(
    world: World,
) -> None:
    a = world.a
    approver = await _second_admin(world, a)
    erasure = (await _request(world, a, a.admin, a.tech_a)).json()
    old = datetime.now(UTC) - timedelta(days=8)
    await world.sql(
        "UPDATE person_erasures SET requested_at = $3, expires_at = $4"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(erasure["id"]),
        old,
        old + timedelta(days=7),
    )
    approved = await world.call(
        "POST",
        f"/erasures/{erasure['id']}/approve",
        a,
        approver,
        json={"confirm_name": await _name(world, a, a.tech_a)},
        headers={"If-Match": '"1"'},
    )
    assert _code(approved) == (409, "erasure_request_expired")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await erasure_job.expire_and_audit(session, datetime.now(UTC)) == 1
    shown = (await world.call("GET", f"/erasures/{erasure['id']}", a, a.admin)).json()
    assert shown["state"] == "expired"
    (logged,) = await _audit(world, a, "person.erasure_expired")
    assert logged["details"]["erasure_id"] == erasure["id"]
    # Expired is closed: a new request may be made.
    assert (await _request(world, a, a.admin, a.tech_a)).status_code == 201


async def test_reject_list_and_get_and_other_tenants_see_nothing(world: World) -> None:
    a, b = world.a, world.b
    approver = await _second_admin(world, a)
    erasure = (await _request(world, a, a.admin, a.tech_a)).json()
    listed = await world.call("GET", "/erasures?state=requested", a, approver)
    assert [item["id"] for item in listed.json()["items"]] == [erasure["id"]]
    rejected = await world.call(
        "POST",
        f"/erasures/{erasure['id']}/reject",
        a,
        approver,
        json={"reason_text": "Data still needed for an open dispute"},
        headers={"If-Match": '"1"'},
    )
    assert rejected.status_code == 200, rejected.text
    assert (rejected.json()["state"], rejected.json()["rejected_by"]) == ("rejected", str(approver))
    assert rejected.headers["ETag"] == '"2"'
    again = await world.call(
        "POST",
        f"/erasures/{erasure['id']}/reject",
        a,
        approver,
        json={},
        headers={"If-Match": '"2"'},
    )
    assert _code(again) == (409, "erasure_not_pending")
    (logged,) = [
        e for e in await _audit(world, a, "person.erasure_rejected") if e["outcome"] == "done"
    ]
    assert logged["object_id"] == erasure["id"]
    assert (await world.call("GET", "/erasures", b, b.admin)).json()["items"] == []
    elsewhere = await world.call("GET", f"/erasures/{erasure['id']}", b, b.admin)
    assert _code(elsewhere) == (404, "erasure_not_found")
