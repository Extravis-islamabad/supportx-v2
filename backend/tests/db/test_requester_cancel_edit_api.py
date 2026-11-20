"""Requester cancel and edit rules (WP-046b S5; REQ-INC-148), through the API.

Real PostgreSQL, the incidents test world. The rules are tenant settings per type, so every test
sets the ones it needs first (the world's tenant is shared by the module's tests).
"""

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
