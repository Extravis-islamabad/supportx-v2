"""Requester cancel and edit rules (WP-046b S5; REQ-INC-148), through the API.

Real PostgreSQL, the incidents test world. The rules are tenant settings per type, so every test
sets the ones it needs first (the world's tenant is shared by the module's tests).
"""

import json
import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incident_settings_api import admin_write
from tests.db.test_incidents_api import BASE, Org, World, field_codes

pytestmark = [pytest.mark.db, pytest.mark.valkey, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, used by name

PORTAL = "/portal/incidents"


async def _rules(world: World, org: Org, **values: Any) -> None:  # noqa: ANN401 - JSON
    set_ = await admin_write(world, org, "PATCH", "/incidents/settings", values)
    assert set_.status_code == 200, set_.text


async def _mine(world: World, org: Org, subject: str) -> dict[str, Any]:
    """An incident of the requester's, assigned to tech_a in GA."""
    return await world.create(
        org,
        org.admin,
        subject=subject,
        group_id=str(org.ga),
        technician_id=str(org.tech_a),
    )


async def _cancel(world: World, org: Org, user: uuid.UUID, item: dict[str, Any]) -> Any:  # noqa: ANN401
    return await world.call(
        "POST", f"{PORTAL}/{item['id']}/cancel", org, user, json={"reason": "Fixed itself."}
    )


async def test_off_by_default_changes_nothing_for_requesters(world: World) -> None:
    """The coordinator's Q3: off is what requesters can do today (nothing)."""
    a = world.a
    await _rules(world, a, requester_cancel="off", requester_edit_fields=[])
    item = await _mine(world, a, f"Off {uuid.uuid4().hex[:6]}")
    shown = (await world.call("GET", f"{PORTAL}/{item['id']}", a, a.requester)).json()
    assert shown["may_cancel"] == "off"
    assert shown["editable_fields"] == []
    assert shown["cancellation"] is None
    refused = await _cancel(world, a, a.requester, item)
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "requester_cancel_off"
    edit = await world.call(
        "PATCH",
        f"{PORTAL}/{item['id']}",
        a,
        a.requester,
        json={"changes": {"subject": "Changed"}},
        headers={"If-Match": f'"{item["version"]}"'},
    )
    assert field_codes(edit) == {"changes.subject": "field_not_editable_by_requester"} or (
        field_codes(edit) == {"subject": "field_not_editable_by_requester"}
    )


async def test_direct_cancel_closes_it_as_the_requester_with_their_reason(world: World) -> None:
    a = world.a
    await _rules(world, a, requester_cancel="direct")
    item = await _mine(world, a, f"Direct {uuid.uuid4().hex[:6]}")
    done = await _cancel(world, a, a.requester, item)
    assert done.status_code == 200, done.text
    assert done.json() == {"canceled": True, "request_id": None}
    staff = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    assert staff["status_category"] == "canceled"
    history = (await world.call("GET", f"{BASE}/{item['id']}/history", a, a.admin)).json()
    flat = [c for e in history["items"] for c in e["changes"]]
    assert {"field": "requester_action", "old": None, "new": "requester_canceled"} in [
        {k: c[k] for k in ("field", "old", "new")} for c in flat
    ]
    # Another requester's record: 404, never a sign that it exists.
    other = await _mine(world, a, f"Not yours {uuid.uuid4().hex[:6]}")
    assert (await _cancel(world, a, a.requester2, other)).status_code == 404


async def test_ask_waits_then_the_assignee_approves(world: World) -> None:
    """AC1: the ask leaves the record open until the assignee decides."""
    a = world.a
    await _rules(world, a, requester_cancel="ask")
    item = await _mine(world, a, f"Ask {uuid.uuid4().hex[:6]}")
    asked = await _cancel(world, a, a.requester, item)
    assert asked.status_code == 200, asked.text
    assert asked.json()["canceled"] is False
    shown = (await world.call("GET", f"{PORTAL}/{item['id']}", a, a.requester)).json()
    assert shown["cancellation"]["reason"] == "Fixed itself."
    assert shown["portal_status"] != "canceled"
    again = await _cancel(world, a, a.requester, item)
    assert again.status_code == 409
    assert again.json()["code"] == "cancellation_already_asked"
    # Someone else with no say (the record is assigned to tech_a): refused, nothing changes.
    path = f"{BASE}/{item['id']}/cancellation-request/decide"
    not_theirs = await world.call("POST", path, a, a.tech_c, json={"approve": True})
    assert not_theirs.status_code in {403, 404}, not_theirs.text
    # The decider gives what the cancel itself asks for (here a coded reason), as on the record.
    approved = await world.call(
        "POST", path, a, a.tech_a, json={"approve": True, "reason_code": "duplicate"}
    )
    assert approved.status_code == 204, approved.text
    staff = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    assert staff["status_category"] == "canceled"
    gone = await world.call("POST", path, a, a.tech_a, json={"approve": True})
    assert gone.status_code == 404


async def test_a_decline_needs_a_note_and_tells_the_requester(world: World) -> None:
    a = world.a
    await _rules(world, a, requester_cancel="ask")
    item = await _mine(world, a, f"Decline {uuid.uuid4().hex[:6]}")
    await _cancel(world, a, a.requester, item)
    path = f"{BASE}/{item['id']}/cancellation-request/decide"
    bare = await world.call("POST", path, a, a.tech_a, json={"approve": False})
    assert field_codes(bare) == {"note": "required"}
    declined = await world.call(
        "POST", path, a, a.tech_a, json={"approve": False, "note": "We still see the fault."}
    )
    assert declined.status_code == 204, declined.text
    staff = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    assert staff["status_category"] != "canceled"
    talk = (await world.call("GET", f"{PORTAL}/{item['id']}/conversation", a, a.requester)).json()
    assert any("We still see the fault." in e["body"] for e in talk["items"])
    shown = (await world.call("GET", f"{PORTAL}/{item['id']}", a, a.requester)).json()
    assert shown["cancellation"] is None


async def test_the_requester_withdraws_a_waiting_ask(world: World) -> None:
    a = world.a
    await _rules(world, a, requester_cancel="ask")
    item = await _mine(world, a, f"Withdraw {uuid.uuid4().hex[:6]}")
    await _cancel(world, a, a.requester, item)
    path = f"{PORTAL}/{item['id']}/cancel-request"
    assert (await world.call("DELETE", path, a, a.requester)).status_code == 204
    assert (await world.call("DELETE", path, a, a.requester)).status_code == 404
    # Withdrawn: a new ask is possible again.
    assert (await _cancel(world, a, a.requester, item)).status_code == 200


async def test_editing_follows_the_list_and_never_opens_a_staff_only_field(world: World) -> None:
    """AC2 and the coordinator's test: a staff-only field stays refused with editing on."""
    a = world.a
    # A staff-only field can't even be put in the list.
    bad = await admin_write(
        world, a, "PATCH", "/incidents/settings", {"requester_edit_fields": ["priority"]}
    )
    assert field_codes(bad) == {"requester_edit_fields": "invalid_choice"}
    await _rules(world, a, requester_edit_fields=["subject", "description"])
    item = await _mine(world, a, f"Edit {uuid.uuid4().hex[:6]}")
    shown = (await world.call("GET", f"{PORTAL}/{item['id']}", a, a.requester)).json()
    assert shown["editable_fields"] == ["description", "subject"]
    edited = await world.call(
        "PATCH",
        f"{PORTAL}/{item['id']}",
        a,
        a.requester,
        json={"changes": {"subject": "Now with the model number"}},
        headers={"If-Match": f'"{item["version"]}"'},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["subject"] == "Now with the model number"
    staff_only = await world.call(
        "PATCH",
        f"{PORTAL}/{item['id']}",
        a,
        a.requester,
        json={"changes": {"priority": "p1"}},
        headers={"If-Match": f'"{edited.json().get("version", item["version"] + 1)}"'},
    )
    assert staff_only.status_code == 422, staff_only.text
    assert "field_not_editable_by_requester" in staff_only.text
    assert "p1" not in staff_only.text


async def test_an_unassigned_ask_goes_to_the_managers_audited_and_the_requester_told(
    world: World,
) -> None:
    """The coordinator's condition 1: no assignee and no group, so the service desk managers.

    Audited, and the requester's notice comes from the incident source (IDs only in the event).
    """
    from app.modules.work_items.service.notifications import (  # noqa: PLC0415 - the source
        CANCELLATION_TO_MANAGERS,
        IncidentNotifications,
    )
    from app.shared.events import EventEnvelope  # noqa: PLC0415

    a = world.a
    await _rules(world, a, requester_cancel="ask")
    item = await world.create(a, a.admin, subject=f"Nobody on it {uuid.uuid4().hex[:6]}")
    assert item["technician_id"] is None
    assert item["group_id"] is None
    asked = await _cancel(world, a, a.requester, item)
    assert asked.status_code == 200, asked.text
    request_id = asked.json()["request_id"]
    staff = await world.call("GET", f"{BASE}/{item['id']}/cancellation-request", a, a.admin)
    assert staff.json()["deciders"] == "managers"
    assert staff.json()["may_decide"] is True  # the admin holds the service desk's settings
    (audit,) = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'incident.cancellation_to_managers' AND object_id = $2",
        a.tenant,
        item["id"],
    )
    assert json.loads(audit["details"])["request_id"] == request_id
    (event,) = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.cancellation_request.created'"
        " AND envelope->'payload'->>'work_item_id' = $2",
        a.tenant,
        item["id"],
    )
    envelope = EventEnvelope.model_validate(json.loads(event["envelope"]))
    assert set(envelope.payload) == {
        "work_item_id",
        "type",
        "requested_by",
        "request_id",
        "deciders",
    }  # IDs and the state only: never the reason
    assert IncidentNotifications().events_for(envelope) == (CANCELLATION_TO_MANAGERS,)
    # An assigned record's ask is the assignee's: no manager notice, no audit.
    mine = await _mine(world, a, f"Assigned {uuid.uuid4().hex[:6]}")
    await _cancel(world, a, a.requester, mine)
    assert not await world.sql(
        "SELECT 1 FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'incident.cancellation_to_managers' AND object_id = $2",
        a.tenant,
        mine["id"],
    )


async def test_with_nobody_to_decide_the_ask_stays_open_and_says_so(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coordinator's condition 1: nobody at all, so it waits, labelled and in the system log."""
    from app.modules.work_items.domain.requester_rules import (  # noqa: PLC0415
        CancellationDeciders,
    )
    from app.modules.work_items.service import requester_requests  # noqa: PLC0415

    async def nobody(*_args: object) -> tuple[CancellationDeciders, frozenset[uuid.UUID]]:
        return CancellationDeciders.NONE, frozenset()

    monkeypatch.setattr(requester_requests, "deciders", nobody)
    a = world.a
    await _rules(world, a, requester_cancel="ask")
    item = await world.create(a, a.admin, subject=f"No decider {uuid.uuid4().hex[:6]}")
    asked = await _cancel(world, a, a.requester, item)
    assert asked.status_code == 200, asked.text
    entries = await world.sql(
        "SELECT severity, module, params, object_type FROM system_log_entries"
        " WHERE tenant_id = $1 AND code = 'work_items.cancellation.no_decider'"
        " AND params->>'display_id' = $2",
        a.tenant,
        item["display_id"],
    )
    assert len(entries) == 1
    [entry] = entries
    params = entry["params"] if isinstance(entry["params"], dict) else json.loads(entry["params"])
    # Lane C's (c): the display ID only, never a name, the subject or the reason.
    assert (entry["severity"], entry["module"], params, entry["object_type"]) == (
        "warning",
        "work_items",
        {"display_id": item["display_id"]},
        None,
    )
    staff = (
        await world.call("GET", f"{BASE}/{item['id']}/cancellation-request", a, a.admin)
    ).json()
    assert staff["deciders"] == "none"
    assert staff["may_decide"] is False
    shown = (await world.call("GET", f"{PORTAL}/{item['id']}", a, a.requester)).json()
    assert shown["cancellation"]["reason"] == "Fixed itself."  # still open, never lost
    refused = await world.call(
        "POST",
        f"{BASE}/{item['id']}/cancellation-request/decide",
        a,
        a.admin,
        json={"approve": True, "reason_code": "duplicate"},
    )
    assert refused.status_code == 403, refused.text


async def test_a_finished_record_is_never_edited_or_asked_about(world: World) -> None:
    """Lane C's B1: resolved, closed or cancelled: the API refuses, not only the portal's offer."""
    a = world.a
    await _rules(world, a, requester_cancel="ask", requester_edit_fields=["subject"])
    item = await _mine(world, a, f"Finished {uuid.uuid4().hex[:6]}")
    moved = await world.act(a, a.admin, item, "resolve")
    assert moved.status_code == 200, moved.text
    resolved = moved.json()
    edit = await world.call(
        "PATCH",
        f"{PORTAL}/{item['id']}",
        a,
        a.requester,
        json={"changes": {"subject": "Rewritten after the fact"}},
        headers={"If-Match": f'"{resolved["version"]}"'},
    )
    assert edit.status_code == 409, edit.text
    assert edit.json()["code"] == "requester_action_closed"
    asked = await _cancel(world, a, a.requester, item)
    assert asked.status_code == 409, asked.text
    assert asked.json()["code"] == "requester_action_closed"
    assert not await world.sql(
        "SELECT 1 FROM work_item_cancellation_requests WHERE tenant_id = $1 AND work_item_id = $2",
        a.tenant,
        item["id"],
    )
    staff = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    assert staff["subject"] == item["subject"]


async def test_a_custom_field_is_never_requester_editable(world: World) -> None:
    """Lane C's B2: refused when the admin lists one, and when a requester sends one."""
    a = world.a
    listed = await admin_write(
        world, a, "PATCH", "/incidents/settings", {"requester_edit_fields": ["custom.cost_code"]}
    )
    assert listed.status_code == 422, listed.text
    assert field_codes(listed) == {"requester_edit_fields": "invalid_choice"}
    await _rules(world, a, requester_edit_fields=["subject"])
    item = await _mine(world, a, f"Custom {uuid.uuid4().hex[:6]}")
    sent = await world.call(
        "PATCH",
        f"{PORTAL}/{item['id']}",
        a,
        a.requester,
        json={"changes": {"custom.cost_code": "CC-1"}},
        headers={"If-Match": f'"{item["version"]}"'},
    )
    assert sent.status_code == 422, sent.text
    assert set(field_codes(sent).values()) == {"field_not_editable_by_requester"}
