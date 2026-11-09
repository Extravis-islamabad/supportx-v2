"""Changes on the stage engine over HTTP (WP-045a S1; file 05 Appendix A; REQ-CHG-023..027, -033).

Real PostgreSQL with RLS. A change starts in submission on the normal path with its own CHG
counter; only listed moves are offered; approval outcomes are the approvals code's only; cancel
needs a reason; the technician's identity grants (view, create) still hold once changes.* left
identity's reserved list (lane C's check).
"""

import uuid
from typing import Any

import httpx

from tests.db.test_incidents_api import CONSOLE, Org, World, problem, world

__all__ = ["world"]  # the fixture, re-used

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
        json={"outcome": "completed"},
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
    assert (shown.json()["change_type"], shown.json()["change_reason"]) == (None, None)
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
    assert changes["change_type"] == (None, "minor")
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
