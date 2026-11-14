"""Editing a closed incident, and the reason for an edit (WP-046b S1; REQ-INC-101, REQ-INC-124;
lane B's conditions).

`incidents.edit_closed` opens a closed incident's fields, with a reason, each edit audited
(field names, never values); the tenant's full lock outranks it, administrators included; other
types stay read-only once closed; the fields an admin names need a reason on any record.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world  # noqa: F401 - fixture


async def _closed(world: World, org: Org) -> dict[str, Any]:  # noqa: F811 - the fixture's name
    item = await world.create(org, org.admin, group_id=str(org.ga), technician_id=str(org.tech_a))
    resolved = await world.act(org, org.admin, item, "resolve")
    assert resolved.status_code == 200, resolved.text
    closed = await world.act(org, org.admin, resolved.json(), "close")
    assert closed.status_code == 200, closed.text
    body: dict[str, Any] = closed.json()
    assert body["status_category"] == "closed"
    return body


async def _edit(
    world: World,  # noqa: F811
    org: Org,
    user: uuid.UUID,
    item: dict[str, Any],
    **values: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - an httpx response
    return await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        org,
        user,
        json=values,
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )


async def test_a_closed_incident_needs_the_right_and_a_reason(world: World) -> None:  # noqa: F811
    """AC1: without the right, refused; AC2: with it, a reason is required and it is audited."""
    a = world.a
    item = await _closed(world, a)
    refused = await _edit(world, a, a.tech_a, item, impact_details="More people affected")
    assert refused.status_code == 403, refused.text  # technicians do not hold it by default
    no_reason = await _edit(world, a, a.admin, item, impact_details="More people affected")
    assert no_reason.status_code == 422, no_reason.text
    assert [e["field"] for e in no_reason.json()["errors"]] == ["body.reason"]
    edited = await _edit(
        world,
        a,
        a.admin,
        item,
        impact_details="More people affected",
        edit_reason="The customer sent the final count after closing.",
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["status_category"] == "closed"  # still closed: never a reopen
    entries = await world.history(a, item)
    reasons = [e.get("reason") for e in entries if any(
        c["field"] == "impact_details" for c in e["changes"]
    )]  # fmt: skip
    assert reasons == ["The customer sent the final count after closing."]
    (audit,) = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'incident.closed_edited' AND object_id = $2",
        a.tenant,
        item["id"],
    )
    assert "impact_details" in str(audit["details"])
    assert "More people affected" not in str(audit["details"])  # names, never values
    # The reason's text is kept with the entry's personal data (sealed), never in its details.


async def test_the_full_lock_refuses_everyone_administrators_included(world: World) -> None:  # noqa: F811
    """Lane B: the tenant's lock outranks the right, the tenant administrator's included."""
    a = world.a
    item = await _closed(world, a)
    await world.sql(
        "UPDATE work_item_type_settings SET closed_edit_locked = true"
        " WHERE tenant_id = $1 AND type = 'incident'",
        a.tenant,
    )
    refused = await _edit(
        world, a, a.admin, item, impact_details="Changed", edit_reason="A late correction"
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "record_closed"
    assert refused.json()["params"]["locked"] is True


async def test_a_named_field_needs_a_reason_on_any_incident(world: World) -> None:  # noqa: F811
    """REQ-INC-124 AC1-AC2: refused without it, kept in history with it."""
    a = world.a
    settings = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    named = await world.call(
        "PATCH",
        f"{BASE}/settings/closure",
        a,
        a.admin,
        json={"edit_reason_fields": ["urgency"]},
        headers={"If-Match": f'"{settings["version"]}"', **CONSOLE},
    )
    assert named.status_code == 200, named.text
    assert named.json()["closure"]["edit_reason_fields"] == ["urgency"]
    item = await world.create(a, a.admin, group_id=str(a.ga))
    refused = await _edit(world, a, a.admin, item, urgency="low")
    assert refused.status_code == 422, refused.text
    fine = await _edit(world, a, a.admin, item, subject="A clearer subject")  # not named: free
    assert fine.status_code == 200, fine.text
    edited = await _edit(world, a, a.admin, fine.json(), urgency="low", edit_reason="Whole floor")
    assert edited.status_code == 200, edited.text
    entries = await world.history(a, item)
    assert "Whole floor" in [e.get("reason") for e in entries]


async def test_the_api_key_path_is_refused_too(world: World) -> None:  # noqa: F811
    """Lane B: the right is checked in the service, so every path meets it (the API as here)."""
    a = world.a
    item = await _closed(world, a)
    by_api = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.tech_a,
        json={"impact_details": "Changed", "edit_reason": "Through the API"},
        headers={"If-Match": f'"{item["version"]}"'},  # no console header: the public API
    )
    assert by_api.status_code == 403, by_api.text


async def test_first_contact_resolution_is_suggested_then_the_technician_decides(
    world: World,  # noqa: F811
) -> None:
    """REQ-INC-102 AC1-AC3: its creator resolving it at once is suggested, a reassigned one never
    is, and the technician's change is recorded."""
    a = world.a
    quick = await world.create(a, a.admin, group_id=str(a.ga))
    resolved = await world.act(a, a.admin, quick, "resolve")
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["first_contact_resolution"] is True  # AC1
    moved = await world.create(a, a.admin, group_id=str(a.ga), technician_id=str(a.tech_a))
    handed = await world.assign(
        a, a.admin, moved, group=a.gb, technician=a.tech_b, reason_code="wrong_group"
    )
    assert handed.status_code == 200, handed.text
    again = await world.act(a, a.admin, handed.json(), "resolve")
    assert again.json()["first_contact_resolution"] is False  # AC2: reassigned, never suggested
    changed = await _edit(world, a, a.admin, resolved.json(), first_contact_resolution=False)
    assert changed.status_code == 200, changed.text
    assert changed.json()["first_contact_resolution"] is False
    entries = await world.history(a, quick)
    assert any(
        c["field"] == "first_contact_resolution" and c["new"] is False
        for e in entries
        for c in e["changes"]
    )  # AC3: the change is recorded
