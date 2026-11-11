"""Changes on the stage engine over HTTP (WP-045a S1; file 05 Appendix A; REQ-CHG-023..027, -033).

Real PostgreSQL with RLS. A change starts in submission on the normal path with its own CHG
counter; only listed moves are offered; approval outcomes are the approvals code's only; cancel
needs a reason; the technician's identity grants (view, create) still hold once changes.* left
identity's reserved list (lane C's check).
"""

import uuid
from typing import Any

import httpx
import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World, problem

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

CHG = "/changes"


async def new_change(world: World, org: Org, user: uuid.UUID, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "POST",
        CHG,
        org,
        user,
        json={"subject": "Core switch firmware 9.3", "requester_id": str(org.requester), **body},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )


async def a_change(world: World, org: Org, user: uuid.UUID | None = None) -> dict[str, Any]:
    made = await new_change(world, org, user or org.admin)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def move(
    world: World, org: Org, item: dict[str, Any], to: str, reason_text: str | None = None
) -> httpx.Response:
    return await world.call(
        "POST",
        f"{CHG}/{item['id']}/moves",
        org,
        org.admin,
        json={"to_status": to, **({"reason_text": reason_text} if reason_text else {})},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )


async def test_req_chg_023_a_change_starts_in_submission_with_its_own_counter(
    world: World,
) -> None:
    a = world.a
    item = await a_change(world, a)
    assert item["display_id"] == "CHG-1"
    assert (item["stage"], item["stage_path"], item["status"]) == (
        "submission",
        "default",
        "submission_submitted",
    )
    shown = await world.call("GET", f"{CHG}/{item['id']}/stages", a, a.admin)
    assert shown.status_code == 200, shown.text
    offered = {m["to_status"]: m for m in shown.json()["moves"]}
    assert set(offered) == {
        "submission_more_info",
        "submission_awaiting_acceptance",
        "closure_canceled",
    }
    assert offered["closure_canceled"]["reason_mode"] == "required"
    # Incidents keep their own counter.
    assert (await world.create(a, a.admin))["display_id"] == "INC-1"


async def test_approval_outcomes_are_not_a_persons_move(world: World) -> None:
    a = world.a
    item = await a_change(world, a)
    waiting = await move(world, a, item, "submission_awaiting_acceptance")
    assert waiting.status_code == 200, waiting.text
    accepted = await move(world, a, waiting.json(), "submission_accepted")
    assert problem(accepted)[0] == 409


async def test_req_chg_033_cancel_needs_a_reason(world: World) -> None:
    a = world.a
    item = await a_change(world, a)
    assert problem(await move(world, a, item, "closure_canceled"))[0] == 422
    canceled = await move(world, a, item, "closure_canceled", "Replaced by CHG-2")
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "closure_canceled"


async def test_a_technician_views_and_creates_changes_from_identity_s_grants(
    world: World,
) -> None:
    a = world.a
    made = await a_change(world, a, a.tech_a)
    listed = await world.call("GET", CHG, a, a.tech_a)
    assert listed.status_code == 200, listed.text
    assert made["id"] in {i["id"] for i in listed.json()["items"]}
    # Tenant B sees none of A's changes.
    assert (await world.call("GET", CHG, world.b, world.b.admin)).json()["items"] == []


async def test_req_chg_031_the_implementation_records_completed_backed_out_or_failed(
    world: World,
) -> None:
    from tests.db.test_release_templates_api import field_codes  # noqa: PLC0415 - shared helper

    a = world.a
    item = await a_change(world, a)
    shown = (await world.call("GET", f"{CHG}/{item['id']}/schedule", a, a.admin)).json()
    implementation = next(s for s in shown if s["stage"] == "implementation")

    async def outcome(code: str, **extra: Any) -> httpx.Response:  # noqa: ANN401 - JSON
        return await world.call(
            "PATCH",
            f"{CHG}/{item['id']}/schedule/implementation",
            a,
            a.admin,
            json={"outcome": code, **extra},
            headers={"If-Match": f'"{implementation["version"]}"', **CONSOLE},
        )

    # A release's work outcome is not a change implementation's.
    assert field_codes(await outcome("partly_done")) == {("outcome", "invalid_choice")}
    backed_out = await outcome("backed_out", outcome_notes="Rolled back at 02:10")
    assert backed_out.status_code == 200, backed_out.text
    assert backed_out.json()["outcome"] == "backed_out"
    # Submission records no outcome.
    submission = next(s for s in shown if s["stage"] == "submission")
    refused = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/schedule/submission",
        a,
        a.admin,
        json={"outcome": "successful"},
        headers={"If-Match": f'"{submission["version"]}"', **CONSOLE},
    )
    assert ("outcome", "not_allowed") in field_codes(refused)


async def details(
    world: World,
    org: Org,
    item: dict[str, Any],
    version: int,
    **body: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/details",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{version}"', **CONSOLE},
    )


async def test_req_chg_005_011_a_change_has_its_type_and_reason_from_its_own_lists(
    world: World,
) -> None:
    from tests.db.test_release_templates_api import field_codes  # noqa: PLC0415 - shared helper

    a = world.a
    item = await a_change(world, a)
    shown = await world.call("GET", f"{CHG}/{item['id']}/details", a, a.admin)
    assert shown.status_code == 200, shown.text
    # The default template binds the normal type (REQ-CHG-022); no reason yet.
    assert (shown.json()["change_type"], shown.json()["change_reason"]) == ("normal", None)
    # A release's type is not a change's: the lists are their own.
    assert field_codes(
        await details(world, a, item, item["version"], change_type="maintenance")
    ) == {("change_type", "invalid_choice")}
    set_ = await details(
        world, a, item, item["version"], change_type="minor", change_reason="security_fix"
    )
    assert set_.status_code == 200, set_.text
    assert (set_.json()["change_type"], set_.json()["change_reason"]) == ("minor", "security_fix")
    assert set_.json()["version"] == item["version"] + 1
    # A stale version is a conflict; unchanged input makes no new version.
    assert problem(await details(world, a, item, item["version"], change_type="major"))[0] == 409
    same = await details(world, a, item, set_.json()["version"], change_type="minor")
    assert same.json()["version"] == set_.json()["version"]
    history = await world.call("GET", f"{CHG}/{item['id']}/history", a, a.admin)
    changes = {c["field"]: (c["old"], c["new"]) for c in history.json()["items"][0]["changes"]}
    assert changes["change_type"] == ("normal", "minor")
    # Releases have no change fields, and their own route is unchanged.
    release = await world.call(
        "POST",
        "/releases",
        a,
        a.admin,
        json={"subject": "Payroll 4.2", "requester_id": str(a.requester)},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    shown_release = await world.call("GET", f"/releases/{release.json()['id']}/details", a, a.admin)
    assert "change_type" not in shown_release.json()
    assert "release_type" in shown_release.json()


async def test_change_details_are_isolated_by_rls(world: World) -> None:
    from sqlalchemy import text  # noqa: PLC0415 - this test only

    from app.core.tenancy import TenantContext  # noqa: PLC0415 - this test only

    a, b = world.a, world.b
    item = await a_change(world, a)
    made = await details(world, a, item, item["version"], change_type="normal")
    assert made.status_code == 200, made.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        mine = (
            await session.execute(text("SELECT count(*) FROM work_item_change_details"))
        ).scalar_one()
        assert mine == 1
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM work_item_change_details WHERE tenant_id = :a"),
                {"a": a.tenant},
            )
        ).scalar_one()
        assert seen == 0
        changed = await session.execute(
            text("UPDATE work_item_change_details SET change_type = 'x' WHERE tenant_id = :a"),
            {"a": a.tenant},
        )
        assert changed.rowcount == 0
    other = await world.call("GET", f"{CHG}/{item['id']}/details", b, b.admin)
    assert other.status_code == 404


async def test_req_chg_006_a_standard_change_is_approved_at_creation_and_says_why(
    world: World,
) -> None:
    a = world.a
    made = await new_change(world, a, a.admin, change_type="standard")
    assert made.status_code == 201, made.text
    item = made.json()
    # Accepted completes submission: on the standard path the next stage is implementation.
    assert (item["stage_path"], item["stage"], item["status"]) == (
        "standard",
        "implementation",
        "implementation_scheduled",
    )
    history = (await world.call("GET", f"{CHG}/{item['id']}/history", a, a.admin)).json()
    lines = {c["field"]: c["new"] for entry in history["items"] for c in entry["changes"]}
    assert lines["pre_approved"] == "standard"  # the record says why, not a bare tick
    assert lines["change_type"] == "standard"
    shown = (await world.call("GET", f"{CHG}/{item['id']}/details", a, a.admin)).json()
    assert shown["change_type"] == "standard"


@pytest.mark.parametrize(
    ("change_type", "path", "status"),
    [
        ("minor", "minor", "submission_submitted"),
        ("major", "major", "submission_submitted"),
        ("emergency", "emergency", "submission_submitted"),
        ("normal", "default", "submission_submitted"),
    ],
)
async def test_req_chg_005_the_type_s_model_picks_the_path(
    world: World, change_type: str, path: str, status: str
) -> None:
    a = world.a
    made = await new_change(world, a, a.admin, change_type=change_type)
    assert made.status_code == 201, made.text
    assert (made.json()["stage_path"], made.json()["status"]) == (path, status)


async def test_a_change_s_fields_are_checked_and_only_changes_take_them(world: World) -> None:
    from tests.db.test_release_templates_api import field_codes  # noqa: PLC0415 - shared helper

    a = world.a
    wrong = await new_change(world, a, a.admin, change_type="maintenance")
    assert field_codes(wrong) == {("change_type", "invalid_choice")}
    reason = await new_change(world, a, a.admin, change_reason="because")
    assert field_codes(reason) == {("change_reason", "invalid_choice")}
    incident = await world.call(
        "POST",
        "/incidents",
        a,
        a.admin,
        json={"subject": "VPN down", "requester_id": str(a.requester), "change_type": "minor"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert ("change_type", "not_allowed") in field_codes(incident)


async def test_req_chg_022_five_templates_each_bind_their_type_and_path(world: World) -> None:
    a = world.a
    listed = await world.call("GET", f"{CHG}/templates", a, a.admin)
    assert listed.status_code == 200, listed.text
    seeded = {t["code"]: t for t in listed.json()}
    assert set(seeded) == {"standard", "minor", "normal", "major", "emergency"}
    assert [c for c, t in seeded.items() if t["is_default"]] == ["normal"]
    assert {c: t["stage_path"] for c, t in seeded.items()} == {
        "standard": "standard",
        "minor": "minor",
        "normal": "default",
        "major": "major",
        "emergency": "emergency",
    }
    # Raised from the standard template: its type, its path, approved at creation.
    from_standard = await new_change(world, a, a.admin, template_id=seeded["standard"]["id"])
    assert from_standard.status_code == 201, from_standard.text
    assert (from_standard.json()["stage_path"], from_standard.json()["status"]) == (
        "standard",
        "implementation_scheduled",
    )
    # The default (normal) template with another type chosen: that type's path.
    other = await new_change(world, a, a.admin, change_type="emergency")
    assert other.json()["stage_path"] == "emergency"
    plain = await new_change(world, a, a.admin)
    assert (plain.json()["stage_path"], plain.json()["status"]) == (
        "default",
        "submission_submitted",
    )
    shown = (await world.call("GET", f"{CHG}/{plain.json()['id']}/details", a, a.admin)).json()
    assert shown["change_type"] == "normal"  # the default template's type


async def test_req_chg_006_ac2_editing_the_plan_warns_then_makes_the_change_normal(
    world: World,
) -> None:
    a = world.a
    item = (await new_change(world, a, a.admin, change_type="standard")).json()
    assert item["stage"] == "implementation"

    async def plan(**extra: Any) -> httpx.Response:  # noqa: ANN401 - JSON
        return await world.call(
            "PUT",
            f"{CHG}/{item['id']}/plan/rollout",
            a,
            a.admin,
            json={"content": "<p>Roll out at 22:00</p>", **extra},
            headers={"If-Match": '"0"', **CONSOLE},
        )

    warned = await plan()
    assert problem(warned) == (409, "standard_change_locked")
    assert warned.json()["params"]["field"] == "plan.rollout"
    converted = await plan(convert_to_normal=True)
    assert converted.status_code == 200, converted.text
    after = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    # Not submitted again, on the normal path (REQ-CHG-006 AC2).
    assert (after["stage_path"], after["stage"], after["status"]) == (
        "default",
        "submission",
        "submission_submitted",
    )
    shown = (await world.call("GET", f"{CHG}/{item['id']}/details", a, a.admin)).json()
    assert shown["change_type"] == "normal"
    history = (await world.call("GET", f"{CHG}/{item['id']}/history", a, a.admin)).json()
    lines = {c["field"]: (c["old"], c["new"]) for e in history["items"] for c in e["changes"]}
    assert lines["standard_converted"] == (None, "plan.rollout")
    assert lines["stage_path"] == ("standard", "default")
    # The rail keeps the earlier round: submission twice, implementation once (left).
    stages = (await world.call("GET", f"{CHG}/{item['id']}/stages", a, a.admin)).json()
    rail = {s["stage"]: (s["state"], len(s["entries"])) for s in stages["rail"]}
    assert rail["submission"] == ("current", 2)
    assert rail["implementation"][1] == 1
    # A normal change's plan is not locked.
    again = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/plan/rollout",
        a,
        a.admin,
        json={"content": "<p>Roll out at 23:00</p>"},
        headers={"If-Match": f'"{converted.json()["version"]}"', **CONSOLE},
    )
    assert again.status_code == 200, again.text


async def test_req_chg_032_implementation_completes_only_with_its_outcome(world: World) -> None:
    a = world.a
    item = (await new_change(world, a, a.admin, change_type="standard")).json()
    started = await move(world, a, item, "implementation_in_progress")
    assert started.status_code == 200, started.text
    item = started.json()

    async def outcome(code: str) -> dict[str, Any]:
        shown = (await world.call("GET", f"{CHG}/{item['id']}/schedule", a, a.admin)).json()
        row = next(s for s in shown if s["stage"] == "implementation")
        set_ = await world.call(
            "PATCH",
            f"{CHG}/{item['id']}/schedule/implementation",
            a,
            a.admin,
            json={"outcome": code, **({"issues": "Login breaks"} if code == "failed" else {})},
            headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
        )
        assert set_.status_code == 200, set_.text
        return dict((await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json())

    refused = await move(world, a, item, "implementation_implemented")
    assert problem(refused) == (409, "stage_move_refused")
    assert refused.json()["params"]["reason"] == "outcome_required"
    item = await outcome("failed")
    mismatch = await move(world, a, item, "implementation_implemented")
    assert mismatch.json()["params"]["reason"] == "outcome_mismatch"
    item = await outcome("successful_with_issues")
    done = await move(world, a, item, "implementation_implemented")
    assert done.status_code == 200, done.text
    assert done.json()["stage"] == "review"  # implemented completes implementation


async def test_raising_acceptance_opens_the_stage_approval(world: World) -> None:
    """Appendix A's acceptance approval opens on reaching its raising status (the guard)."""
    a = world.a
    item = await a_change(world, a)
    raised = await move(world, a, item, "submission_awaiting_acceptance")
    assert raised.status_code == 200, raised.text
    shown = await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)
    assert shown.status_code == 200, shown.text
    [entry] = shown.json()["items"]
    # Nobody holds the line manager role yet (D5 fills it from the requester): it goes to the
    # approval administrators, and says why.
    assert (entry["record_stage"], entry["state"], entry["route_reason"]) == (
        "submission",
        "pending",
        "no_holder",
    )
    decided = await world.call(
        "POST",
        f"{CHG}/{item['id']}/approvals/{entry['id']}/decision",
        a,
        a.admin,
        json={"decision": "approve"},
        headers={"If-Match": f'"{entry["version"]}"', **CONSOLE},
    )
    assert decided.status_code == 200, decided.text
    after = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    assert (after["stage"], after["status"]) == ("planning", "planning_planning")
    audit = await world.sql(
        "SELECT details->>'outcome' AS outcome FROM audit_entries"
        " WHERE tenant_id = $1 AND action = 'change.approval_decided'",
        a.tenant,
    )
    assert [r["outcome"] for r in audit] == ["approved"]  # QA9-F-03 (#283)


async def test_req_chg_036_the_line_manager_comes_from_the_requester(world: World) -> None:
    from tests.db.test_approvals_api import manager_of  # noqa: PLC0415 - shared helper

    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await a_change(world, a)

    async def line_manager(record_id: str) -> list[str]:
        roles = (await world.call("GET", f"{CHG}/{record_id}/roles", a, a.admin)).json()
        held = next(r for r in roles["roles"] if r["code"] == "line_manager")
        return [str(u) for u in held["user_ids"]]

    assert await line_manager(item["id"]) == [str(a.tech_a)]  # AC1
    # Raising acceptance asks the line manager, not the administrators.
    raised = await move(world, a, item, "submission_awaiting_acceptance")
    [entry] = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    assert entry["approver_id"] == str(a.tech_a)
    # A requester with no manager leaves it empty (AC2).
    other = (await new_change(world, a, a.admin, requester_id=str(a.admin))).json()
    assert await line_manager(other["id"]) == []
    del raised
    # The requester changes: the line manager follows (it was filled in, not chosen).
    await manager_of(world, a.admin, a.tech_b)
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    changed = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}",
        a,
        a.admin,
        json={"requester_id": str(a.admin)},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    assert await line_manager(item["id"]) == [str(a.tech_b)]


async def test_req_chg_039_the_implementer_never_approves(world: World) -> None:
    from tests.db.test_approvals_api import manager_of  # noqa: PLC0415 - shared helper

    a = world.a
    await manager_of(world, a.requester, a.tech_a)  # tech_a is the line manager
    item = await a_change(world, a)

    async def implementer(user: uuid.UUID) -> None:
        fresh = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
        set_ = await world.call(
            "PUT",
            f"{CHG}/{item['id']}/roles/implementer",
            a,
            a.admin,
            json={"user_ids": [str(user)]},
            headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
        )
        assert set_.status_code == 200, set_.text

    await implementer(a.tech_a)
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    raised = await move(world, a, fresh, "submission_awaiting_acceptance")
    assert raised.status_code == 200, raised.text
    [entry] = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    # Skipped when named: the administrators decide, and the record says why (AC1).
    assert (entry["approver_id"], entry["route_reason"]) == (None, "segregation_of_duties")


async def test_req_chg_039_default_an_implementing_group_does_not_bar_its_members(
    world: World,
) -> None:
    """Haider's default: only the assigned implementer and the owner may not approve.

    tech_a is the line manager and a member of GA, which implements as a group: tech_a still
    approves. Barring every member is the tenant's strict option (WP-045b).
    """
    from tests.db.test_approvals_api import manager_of  # noqa: PLC0415 - shared helper

    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await a_change(world, a)
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    set_ = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/roles/implementer",
        a,
        a.admin,
        json={"group_ids": [str(a.ga)]},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert set_.status_code == 200, set_.text
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    assert (await move(world, a, fresh, "submission_awaiting_acceptance")).status_code == 200
    rows = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    assert [(r["approver_id"], r["route_reason"]) for r in rows] == [(str(a.tech_a), None)]


async def test_req_chg_039_the_change_owner_never_approves(world: World) -> None:
    from tests.db.test_approvals_api import manager_of  # noqa: PLC0415 - shared helper

    a = world.a
    await manager_of(world, a.requester, a.tech_a)
    item = await a_change(world, a)
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    owned = await world.call(
        "POST",
        f"{CHG}/{item['id']}/assign",
        a,
        a.admin,
        json={"technician_id": str(a.tech_a)},
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )
    assert owned.status_code == 200, owned.text
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    assert (await move(world, a, fresh, "submission_awaiting_acceptance")).status_code == 200
    rows = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    # The owner is also the line manager: skipped, the administrators decide, saying why.
    assert [(r["approver_id"], r["route_reason"]) for r in rows] == [
        (None, "segregation_of_duties")
    ]


async def test_req_chg_002_a_change_made_from_a_problem_is_prefilled_and_linked(
    world: World,
) -> None:
    from tests.db.test_release_templates_api import field_codes  # noqa: PLC0415 - shared helper

    a, b = world.a, world.b
    made = await world.call(
        "POST",
        "/problems",
        a,
        a.admin,
        json={"subject": "Mail relay drops messages", "requester_id": str(a.requester)},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    problem_ = made.json()
    shown = await world.call("GET", f"{CHG}/prefill?record_id={problem_['id']}", a, a.admin)
    assert shown.status_code == 200, shown.text
    filled = shown.json()
    assert (filled["subject"], filled["from_record_id"]) == (
        "Mail relay drops messages",
        problem_["id"],
    )
    # The form may edit every value before saving (AC3): here the subject.
    change = await new_change(
        world, a, a.admin, subject="Replace the mail relay", from_record_id=problem_["id"]
    )
    assert change.status_code == 201, change.text
    links = await world.sql(
        "SELECT kind FROM work_item_links WHERE tenant_id = $1 AND source_id = $2"
        " AND target_id = $3 AND deleted_at IS NULL",
        a.tenant,
        uuid.UUID(change.json()["id"]),
        uuid.UUID(problem_["id"]),
    )
    assert [r["kind"] for r in links] == ["change_for"]
    for record, path in ((change.json(), CHG), (problem_, "/problems")):  # on both records (AC1)
        history = (await world.call("GET", f"{path}/{record['id']}/history", a, a.admin)).json()
        assert any(c["field"] == "link" for e in history["items"] for c in e["changes"])
    # Another tenant's record is not found, and only changes take from_record_id.
    assert (
        await world.call("GET", f"{CHG}/prefill?record_id={problem_['id']}", b, b.admin)
    ).status_code == 404
    incident = await world.call(
        "POST",
        "/incidents",
        a,
        a.admin,
        json={
            "subject": "VPN down",
            "requester_id": str(a.requester),
            "from_record_id": problem_["id"],
        },
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert field_codes(incident) == {("from_record_id", "not_allowed")}


async def test_req_chg_004_a_retrospective_change_enters_at_its_review(world: World) -> None:
    from tests.db.test_release_templates_api import field_codes  # noqa: PLC0415 - shared helper

    a = world.a
    missing = await new_change(world, a, a.admin, retrospective=True)
    assert field_codes(missing) == {("actual_start", "required"), ("actual_end", "required")}
    future = await new_change(
        world,
        a,
        a.admin,
        retrospective=True,
        actual_start="2026-11-01T22:00:00Z",
        actual_end="2099-01-01T00:00:00Z",
    )
    assert field_codes(future) == {("actual_end", "not_in_past")}
    made = await new_change(
        world,
        a,
        a.admin,
        change_type="emergency",
        retrospective=True,
        actual_start="2026-11-01T22:00:00Z",
        actual_end="2026-11-01T23:30:00Z",
    )
    assert made.status_code == 201, made.text
    item = made.json()
    assert (item["stage"], item["status"]) == ("review", "review_in_review")  # AC2
    shown = (await world.call("GET", f"{CHG}/{item['id']}/details", a, a.admin)).json()
    assert shown["retrospective"] is True  # the marker (AC2), for reports too (AC3)
    schedule = (await world.call("GET", f"{CHG}/{item['id']}/schedule", a, a.admin)).json()
    implementation = next(s for s in schedule if s["stage"] == "implementation")
    assert implementation["actual_start"].startswith("2026-11-01T22:00")
    assert implementation["actual_end"].startswith("2026-11-01T23:30")
    # It still passes review and closure: the past approval stages are skipped, not done.
    stages = (await world.call("GET", f"{CHG}/{item['id']}/stages", a, a.admin)).json()
    rail = {s["stage"]: s["state"] for s in stages["rail"]}
    assert rail["review"] == "current"
    assert rail["closure"] == "future"


async def test_req_chg_003_a_copy_brings_what_is_chosen_and_never_approvals(
    world: World,
) -> None:
    a = world.a
    item = (await new_change(world, a, a.admin, change_type="minor")).json()
    wrote = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/plan/backout",
        a,
        a.admin,
        json={"content": "<p>Restore the old firmware</p>"},
        headers={"If-Match": '"0"', **CONSOLE},
    )
    assert wrote.status_code == 200, wrote.text
    fresh = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    assert (await move(world, a, fresh, "submission_awaiting_acceptance")).status_code == 200

    async def copy(**body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
        made = await world.call(
            "POST",
            f"{CHG}/{item['id']}/copy",
            a,
            a.admin,
            json=body,
            headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
        )
        assert made.status_code == 201, made.text
        return dict(made.json())

    plain = await copy()
    # Its first stage, no approvals (AC1), its own type.
    assert (plain["stage"], plain["status"], plain["stage_path"]) == (
        "submission",
        "submission_submitted",
        "minor",
    )
    approvals = await world.call("GET", f"{CHG}/{plain['id']}/approvals", a, a.admin)
    assert approvals.json()["items"] == []
    history = (await world.call("GET", f"{CHG}/{plain['id']}/history", a, a.admin)).json()
    lines = {c["field"]: c["new"] for e in history["items"] for c in e["changes"]}
    assert lines["copied_from"] == item["display_id"]  # AC2
    plan = (await world.call("GET", f"{CHG}/{plain['id']}/plan", a, a.admin)).json()
    assert all(not s["content"] for s in plan)  # plans only when chosen
    with_plans = await copy(parts=["plans"])
    plan = (await world.call("GET", f"{CHG}/{with_plans['id']}/plan", a, a.admin)).json()
    backout = next(s for s in plan if s["section"] == "backout")
    assert "old firmware" in backout["content"]  # AC3: as editable text


async def test_req_chg_093_the_plan_goes_for_approval_only_with_a_backout_plan(
    world: World,
) -> None:
    from tests.db.test_release_templates_api import field_codes  # noqa: PLC0415 - shared helper

    a = world.a
    item = await a_change(world, a)
    raised = (await move(world, a, item, "submission_awaiting_acceptance")).json()
    [entry] = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    await world.call(
        "POST",
        f"{CHG}/{item['id']}/approvals/{entry['id']}/decision",
        a,
        a.admin,
        json={"decision": "approve"},
        headers={"If-Match": f'"{entry["version"]}"', **CONSOLE},
    )
    planning = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    assert planning["status"] == "planning_planning"
    refused = await move(world, a, planning, "planning_awaiting_approval")
    assert field_codes(refused) == {("plan.backout", "required")}
    wrote = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/plan/backout",
        a,
        a.admin,
        json={"content": "<p>Roll back the firmware</p>"},
        headers={"If-Match": '"0"', **CONSOLE},
    )
    assert wrote.status_code == 200, wrote.text
    planning = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    sent = await move(world, a, planning, "planning_awaiting_approval")
    assert sent.status_code == 200, sent.text
    del raised


async def test_req_chg_017_an_implementation_past_its_window_shows_overdue(world: World) -> None:
    a = world.a
    item = (await new_change(world, a, a.admin, change_type="standard")).json()
    shown = (await world.call("GET", f"{CHG}/{item['id']}/schedule", a, a.admin)).json()
    row = next(s for s in shown if s["stage"] == "implementation")
    assert row["overdue"] is False
    set_ = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/schedule/implementation",
        a,
        a.admin,
        json={"scheduled_start": "2026-11-01T20:00:00Z", "scheduled_end": "2026-11-01T22:00:00Z"},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert set_.status_code == 200, set_.text
    shown = (await world.call("GET", f"{CHG}/{item['id']}/schedule", a, a.admin)).json()
    assert next(s for s in shown if s["stage"] == "implementation")["overdue"] is True


NINE = {
    "affected": "organisation",
    "done_before": "once_or_twice",
    "backout_plan": "untested",
    "outage": "none",
    "critical": "no",
    "cis_changed": "more_than_five",
}


async def test_req_chg_057_060_assess_the_risk_then_override_it_with_a_reason(
    world: World,
) -> None:
    from tests.db.test_release_templates_api import field_codes  # noqa: PLC0415 - shared helper

    a = world.a
    item = await a_change(world, a)
    asked = (await world.call("GET", f"{CHG}/{item['id']}/risk/questionnaire", a, a.admin)).json()
    assert (asked["version"], len(asked["questions"])) == (1, 6)  # Appendix A's

    async def assess(answers: dict[str, str], version: int) -> httpx.Response:
        return await world.call(
            "PUT",
            f"{CHG}/{item['id']}/risk/assessment",
            a,
            a.admin,
            json={"answers": answers},
            headers={"If-Match": f'"{version}"', **CONSOLE},
        )

    wrong = await assess({**NINE, "critical": "maybe"}, item["version"])
    assert field_codes(wrong) == {("risk_answers.critical", "invalid_choice")}
    scored = await assess(NINE, item["version"])
    assert scored.status_code == 200, scored.text
    shown = scored.json()
    assert (shown["risk"], shown["risk_score"], shown["risk_version"]) == ("high", 9, 1)  # AC1
    history = (await world.call("GET", f"{CHG}/{item['id']}/history", a, a.admin)).json()
    lines = {c["field"]: c["new"] for e in history["items"] for c in e["changes"]}
    assert lines["risk"] == "high"
    # An override without a reason is refused; with one, both levels are kept (REQ-CHG-060).
    bare = await details(world, a, item, shown["version"], risk_chosen="low")
    assert field_codes(bare) == {("risk_reason", "reason_required")}
    chosen = await details(
        world, a, item, shown["version"], risk_chosen="low", risk_reason="Done weekly, no issue"
    )
    assert chosen.status_code == 200, chosen.text
    assert (chosen.json()["risk"], chosen.json()["risk_chosen"]) == ("high", "low")


async def test_the_change_list_s_pending_approval_view_holds_changes_at_a_stage_approval(
    world: World,
) -> None:
    """The change screens' "Pending approval" view: changes waiting at a stage's approval.

    Stage approvals never set the record's approval status, so the view also matches the
    stages' raising statuses; the list's DSL equivalent (for export) says the same.
    """
    a = world.a
    waiting = await a_change(world, a)
    other = await a_change(world, a)
    raised = await move(world, a, waiting, "submission_awaiting_acceptance")
    assert raised.status_code == 200, raised.text
    views = await world.call("GET", f"{CHG}/views", a, a.admin)
    assert views.status_code == 200, views.text
    assert "pending_approval" in [v["view"] for v in views.json()]
    listed = await world.call(
        "GET", CHG, a, a.admin, params={"view": "pending_approval", "include_total": "true"}
    )
    assert listed.status_code == 200, listed.text
    ids = {i["id"] for i in listed.json()["items"]}
    assert waiting["id"] in ids
    assert other["id"] not in ids
    filters = (await world.call("GET", f"{CHG}/view-filters", a, a.admin)).json()
    as_filter = next(f for f in filters if f["view"] == "pending_approval")
    found = await world.call(
        "GET",
        CHG,
        a,
        a.admin,
        params={"filter": __import__("json").dumps(as_filter["filter"])},
    )
    assert found.status_code == 200, found.text
    assert {i["id"] for i in found.json()["items"]} == ids


async def _approve_pending(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    rows = (await world.call("GET", f"{CHG}/{item['id']}/approvals", org, org.admin)).json()
    [entry] = [r for r in rows["items"] if r["state"] == "pending"]
    decided = await world.call(
        "POST",
        f"{CHG}/{item['id']}/approvals/{entry['id']}/decision",
        org,
        org.admin,
        json={"decision": "approve"},
        headers={"If-Match": f'"{entry["version"]}"', **CONSOLE},
    )
    assert decided.status_code == 200, decided.text
    return dict((await world.call("GET", f"{CHG}/{item['id']}", org, org.admin)).json())


async def test_qa_flow_4_a_normal_change_end_to_end(world: World) -> None:
    """The change screens' journey (QA flow 4), as the console drives it, move by move.

    Raise, accept, plan with a backout plan, the CAB, implement with an outcome, review, close.
    A completing status moves on by itself (ADR-041), so the plan's approval lands in the CAB's
    raising status and the CAB's in implementation; the e2e follows exactly these steps.
    """
    a = world.a
    item = await a_change(world, a)
    assert (item["stage"], item["status"]) == ("submission", "submission_submitted")
    item = (await move(world, a, item, "submission_awaiting_acceptance")).json()
    item = await _approve_pending(world, a, item)
    assert (item["stage"], item["status"]) == ("planning", "planning_planning")
    wrote = await world.call(
        "PUT",
        f"{CHG}/{item['id']}/plan/backout",
        a,
        a.admin,
        json={"content": "<p>Restore the saved switch configuration</p>"},
        headers={"If-Match": '"0"', **CONSOLE},
    )
    assert wrote.status_code == 200, wrote.text
    item = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    item = (await move(world, a, item, "planning_awaiting_approval")).json()
    item = await _approve_pending(world, a, item)
    assert (item["stage"], item["status"]) == ("cab_review", "cab_awaiting")
    item = await _approve_pending(world, a, item)
    assert (item["stage"], item["status"]) == ("implementation", "implementation_scheduled")
    item = (await move(world, a, item, "implementation_in_progress")).json()
    shown = (await world.call("GET", f"{CHG}/{item['id']}/schedule", a, a.admin)).json()
    row = next(s for s in shown if s["stage"] == "implementation")
    set_ = await world.call(
        "PATCH",
        f"{CHG}/{item['id']}/schedule/implementation",
        a,
        a.admin,
        json={"outcome": "successful"},
        headers={"If-Match": f'"{row["version"]}"', **CONSOLE},
    )
    assert set_.status_code == 200, set_.text
    item = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    done = await move(world, a, item, "implementation_implemented")
    assert done.status_code == 200, done.text
    item = done.json()
    assert (item["stage"], item["status"]) == ("review", "review_in_review")
    panel = (await world.call("GET", f"{CHG}/{item['id']}/stages", a, a.admin)).json()
    complete = next(m for m in panel["moves"] if m["to_status"] == "review_complete")
    # The review completes and closes the change in one move: the dialog asks for the code.
    assert (complete["allowed"], complete["lands_in"]) == (True, "closure_closed")
    codes = (await world.call("GET", f"{CHG}/settings", a, a.admin)).json()["closure_codes"]
    closed = await world.call(
        "POST",
        f"{CHG}/{item['id']}/moves",
        a,
        a.admin,
        json={"to_status": "review_complete", "closure_code": codes[0]["code"]},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert closed.status_code == 200, closed.text
    assert (closed.json()["stage"], closed.json()["status"]) == ("closure", "closure_closed")
