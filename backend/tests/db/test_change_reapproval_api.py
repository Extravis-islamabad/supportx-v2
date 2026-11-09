"""Re-approval of an approved change over HTTP and under RLS (WP-045b S4; REQ-CHG-053).

Approving a stage keeps the watched values; an edit afterwards is listed field by field with
what it does (AC3); a raised risk restarts, a lowered one notifies (AC2); the tenant's policy is
a change setting; tenant B never sees tenant A's snapshots (rule 5a).
"""

import uuid
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from tests.db.test_changes_api import CHG, a_change, details, move
from tests.db.test_incidents_api import CONSOLE, Org, World, world

__all__ = ["world"]  # the fixture, re-used


async def accepted(world: World, org: Org) -> dict[str, Any]:
    """A change whose submission stage was approved (by the administrators: no line manager)."""
    item = await a_change(world, org)
    assert (await move(world, org, item, "submission_awaiting_acceptance")).status_code == 200
    [entry] = (await world.call("GET", f"{CHG}/{item['id']}/approvals", org, org.admin)).json()[
        "items"
    ]
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


async def since(world: World, org: Org, item: dict[str, Any]) -> list[dict[str, Any]]:
    shown = await world.call("GET", f"{CHG}/{item['id']}/approvals/changes-since", org, org.admin)
    assert shown.status_code == 200, shown.text
    return list(shown.json())


async def test_req_chg_053_ac3_changes_since_approval_field_by_field(world: World) -> None:
    a = world.a
    item = await accepted(world, a)
    assert await since(world, a, item) == []  # nothing changed yet
    raised = await details(
        world, a, item, item["version"], risk_chosen="high", risk_reason="Core switch"
    )
    assert raised.status_code == 200, raised.text
    assert await since(world, a, item) == [
        {
            "stage": "submission",
            "changes": [{"field": "risk", "before": None, "after": "high", "effect": "restart"}],
        }
    ]


async def test_req_chg_053_the_policy_is_a_change_setting(world: World) -> None:
    a = world.a
    current = (await world.call("GET", f"{CHG}/settings", a, a.admin)).json()
    assert current["reapproval"] is None  # the shipped policy
    changed = await world.call(
        "PATCH",
        f"{CHG}/settings",
        a,
        a.admin,
        json={"reapproval": {"on_change": {"risk": "notify"}, "tolerance_minutes": 120}},
        headers={"If-Match": f'"{current["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    policy = changed.json()["reapproval"]
    assert policy["on_change"] == {"window": "restart", "risk": "notify", "plans": "notify"}
    assert policy["tolerance_minutes"] == 120
    item = await accepted(world, a)
    await details(world, a, item, item["version"], risk_chosen="high", risk_reason="Core switch")
    [stage] = await since(world, a, item)
    assert stage["changes"][0]["effect"] == "notify"


async def test_snapshots_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    await accepted(world, a)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        mine = await session.scalar(text("SELECT count(*) FROM change_approval_snapshots"))
    assert mine == 1
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.scalar(
            text("SELECT count(*) FROM change_approval_snapshots WHERE tenant_id = :a"),
            {"a": a.tenant},
        )
        assert seen == 0
    item_id = (await world.call("GET", CHG, a, a.admin)).json()["items"][0]["id"]
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO change_approval_snapshots "
                    "(id, tenant_id, work_item_id, record_stage, snapshot) "
                    "VALUES (:i, :t, :w, 'submission', '{}')"
                ),
                {"i": uuid.uuid4(), "t": a.tenant, "w": item_id},
            )


async def test_req_chg_053_ac2_a_raised_risk_sends_the_change_back_for_approval(
    world: World,
) -> None:
    """Haider: the change goes back to the stage's raising status and its approval reopens."""
    a = world.a
    item = await accepted(world, a)
    assert item["stage"] == "planning"
    raised = await details(
        world, a, item, item["version"], risk_chosen="high", risk_reason="Core switch"
    )
    assert raised.status_code == 200, raised.text
    after = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    assert (after["stage"], after["status"]) == ("submission", "submission_awaiting_acceptance")
    rows = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    assert sorted(r["state"] for r in rows) == ["approved", "pending"]  # the earlier one kept
    history = (await world.call("GET", f"{CHG}/{item['id']}/history", a, a.admin)).json()
    fields = {c["field"] for entry in history["items"] for c in entry["changes"]}
    assert "reapproval_restarted" in fields
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        audited = await session.scalar(
            text(
                "SELECT details->>'stage' FROM audit_entries "
                "WHERE action = 'change.sent_back_for_approval' AND object_id = :r"
            ),
            {"r": item["id"]},
        )
    assert audited == "submission"
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        notices = [
            r["notice"]
            for r in await conn.fetch(
                "SELECT envelope->'payload'->>'notice' AS notice FROM outbox_events"
                " WHERE envelope->>'event_type' = 'work_items.change.approval_notice'"
                " AND envelope->'payload'->>'work_item_id' = $1",
                item["id"],
            )
        ]
    finally:
        await conn.close()
    assert "sent_back" in notices  # recorded for the change notifications (WP-056)
    # A lowered risk afterwards only notifies: nothing moves.
    current = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    lowered = await details(
        world, a, current, current["version"], risk_chosen="medium", risk_reason="Rechecked"
    )
    assert lowered.status_code == 200, lowered.text
    again = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    assert again["status"] == "submission_awaiting_acceptance"
    entries = (await world.call("GET", f"{CHG}/{item['id']}/stages", a, a.admin)).json()
    [submission] = [s for s in entries["rail"] if s["stage"] == "submission"]
    assert len(submission["entries"]) == 2  # sent back once, not again while it waits


async def test_the_save_warns_before_sending_the_change_back(world: World) -> None:
    """Haider: warn first; the preview names the stage and changes nothing."""
    a = world.a
    item = await accepted(world, a)
    url = f"{CHG}/{item['id']}/approvals/reapproval-preview"
    warned = await world.call("POST", url, a, a.admin, json={"risk": "very_high"}, headers=CONSOLE)
    assert warned.status_code == 200, warned.text
    assert [s["stage"] for s in warned.json()] == ["submission"]
    quiet = await world.call("POST", url, a, a.admin, json={}, headers=CONSOLE)
    assert quiet.json() == []
    after = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    assert after["stage"] == "planning"  # nothing moved


async def test_d144_the_emergency_override_keeps_the_change_going_and_needs_a_review(
    world: World,
) -> None:
    """Haider: the only way on after a send-back; a reason, audited, and the review required."""
    a = world.a
    item = await accepted(world, a)
    await details(world, a, item, item["version"], risk_chosen="high", risk_reason="Core switch")
    sent = (await world.call("GET", f"{CHG}/{item['id']}", a, a.admin)).json()
    assert sent["status"] == "submission_awaiting_acceptance"
    url = f"{CHG}/{item['id']}/emergency-override"
    headers = {"If-Match": f'"{sent["version"]}"', **CONSOLE}
    # A technician without the permission is refused.
    refused = await world.call("POST", url, a, a.tech_a, json={"reason": "Outage"}, headers=headers)
    assert refused.status_code in {403, 404}, refused.text
    done = await world.call(
        "POST", url, a, a.admin, json={"reason": "Half the switches are done"}, headers=headers
    )
    assert done.status_code == 200, done.text
    assert (done.json()["stage"], done.json()["status"]) == ("planning", "planning_planning")
    rows = (await world.call("GET", f"{CHG}/{item['id']}/approvals", a, a.admin)).json()["items"]
    assert "pending" not in {r["state"] for r in rows}  # the re-approval was withdrawn
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        logged = await session.scalar(
            text(
                "SELECT details->>'stage' FROM audit_entries "
                "WHERE action = 'change.emergency_override' AND object_id = :r"
            ),
            {"r": item["id"]},
        )
        pir = await session.scalar(
            text("SELECT pir_required FROM work_item_change_details WHERE work_item_id = :r"),
            {"r": item["id"]},
        )
    assert (logged, pir) == ("planning", True)  # the reason is kept as personal data
    # Nothing left to override.
    again = await world.call(
        "POST",
        url,
        a,
        a.admin,
        json={"reason": "Again"},
        headers={"If-Match": f'"{done.json()["version"]}"', **CONSOLE},
    )
    assert again.status_code == 409, again.text
