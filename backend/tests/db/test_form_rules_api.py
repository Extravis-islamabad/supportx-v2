"""Form layouts and form rules over HTTP (WP-046a S5b; REQ-INC-036, REQ-INC-037).

The server enforces a template's form rules on every save, the same way the browser applies
them, so the API cannot get around them: a rule's "required" is the same field error, a hidden
field is cleared on save (and the clear is in the history) unless the rule keeps it, a locked
field cannot be changed by hand, and a rule's value fills an empty field. Real PostgreSQL; the
cast is test_incidents_api's.
"""

import uuid
from typing import Any

import httpx

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, field_codes

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def new_template(world: World, org: Org, **values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    made = await world.call(
        "POST",
        f"{BASE}/templates",
        org,
        org.admin,
        json={"labels": {"en": f"Form {uuid.uuid4().hex[:8]}"}, **values},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def category(world: World, org: Org, code: str) -> str:
    tree = (await world.call("GET", f"{BASE}/categories", org, org.admin)).json()
    return str(next(n for n in tree if n["code"] == code)["id"])


async def edit(
    world: World,
    org: Org,
    item: dict[str, Any],
    **values: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    fresh = await world.fresh(org, item)
    return await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        org,
        org.admin,
        json=values,
        headers={"If-Match": f'"{fresh["version"]}"', **CONSOLE},
    )


async def test_req_inc_037_ac1_a_rule_s_required_field_is_the_same_field_error(
    world: World,
) -> None:
    a = world.a
    network = await category(world, a, "network")
    rule = {
        "id": "net_site",
        "when": {"field": "category_id", "op": "eq", "value": network},
        "then": [{"do": "require", "field": "site_id"}],
    }
    template = await new_template(world, a, form_rules=[rule])
    saved = template["form_rules"][0]
    assert (saved["id"], saved["when"]) == (rule["id"], rule["when"])
    assert [(a["do"], a["field"]) for a in saved["then"]] == [("require", "site_id")]
    refused = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={
            "subject": "VPN down",
            "requester_id": str(a.requester),
            "template_id": template["id"],
            "category_id": network,
        },
        headers=CONSOLE,
    )
    assert field_codes(refused) == {"site_id": "required"}
    made = await world.create(
        a, a.admin, template_id=template["id"], category_id=network, site_id=str(a.s1)
    )
    assert made["site_id"] == str(a.s1)
    # Another category: no rule, no requirement.
    printer = await category(world, a, "printer")
    await world.create(a, a.admin, template_id=template["id"], category_id=printer)
    # An edit into the rule's condition needs the field too (newly required). The record took
    # the requester's site when it was made, so this edit also empties it.
    other = await world.create(a, a.admin, template_id=template["id"], category_id=printer)
    moved = await edit(world, a, other, category_id=network, site_id=None)
    assert field_codes(moved) == {"site_id": "required"}
    assert (await edit(world, a, other, category_id=network)).status_code == 200


async def test_req_inc_037_ac2_hidden_fields_clear_unless_kept_and_the_clear_is_recorded(
    world: World,
) -> None:
    a = world.a
    rules = [
        {
            "id": "person",
            "when": {"field": "impact", "op": "eq", "value": "one_person"},
            "then": [
                {"do": "hide", "field": "impact_details"},
                {"do": "hide", "field": "site_id", "keep_value": True},
            ],
        }
    ]
    template = await new_template(world, a, form_rules=rules)
    item = await world.create(
        a,
        a.admin,
        template_id=template["id"],
        impact="team",
        impact_details="Whole floor",
        site_id=str(a.s1),
    )
    assert item["impact_details"] == "Whole floor"
    changed = await edit(world, a, item, impact="one_person")
    assert changed.status_code == 200, changed.text
    after = changed.json()
    assert after["impact_details"] is None  # cleared on save
    assert after["site_id"] == str(a.s1)  # hidden, but the rule keeps its value
    history = (await world.call("GET", f"{BASE}/{item['id']}/history", a, a.admin)).json()
    entries = history["items"] if isinstance(history, dict) else history
    assert any(
        c.get("field") == "impact_details" and c.get("new") is None
        for e in entries
        for c in e.get("changes", [])
    ), entries
    # On a create, a value sent for a hidden field is dropped.
    made = await world.create(
        a, a.admin, template_id=template["id"], impact="one_person", impact_details="Only me"
    )
    assert made["impact_details"] is None


async def test_lock_and_set(world: World) -> None:
    a = world.a
    rules = [
        {
            "id": "org",
            "when": {"field": "impact", "op": "eq", "value": "organisation"},
            "then": [
                {"do": "set", "field": "urgency", "value": "high"},
                {"do": "lock", "field": "urgency"},
            ],
        }
    ]
    template = await new_template(world, a, form_rules=rules)
    made = await world.create(a, a.admin, template_id=template["id"], impact="organisation")
    assert made["urgency"] == "high"  # set, because it was empty
    locked = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={
            "subject": "Everything",
            "requester_id": str(a.requester),
            "template_id": template["id"],
            "impact": "organisation",
            "urgency": "low",
        },
        headers=CONSOLE,
    )
    assert field_codes(locked) == {"urgency": "field_locked"}
    assert field_codes(await edit(world, a, made, urgency="low")) == {"urgency": "field_locked"}


async def test_template_layout_and_rules_are_checked_when_saved(world: World) -> None:
    a = world.a
    layout = {
        "technician": {
            "label_position": "start",
            "sections": [
                {
                    "id": "who",
                    "names": {"en": "Who", "ar": "من"},
                    "fields": ["requester_id", "subject"],
                },
                {"id": "more", "columns": 2, "collapsible": True, "fields": ["site_id"]},
            ],
        },
        "requester": None,
    }
    template = await new_template(world, a, layout=layout)
    saved = template["layout"]["technician"]
    assert [s["id"] for s in saved["sections"]] == ["who", "more"]
    assert saved["label_position"] == "start"
    bad = await world.call(
        "PATCH",
        f"{BASE}/templates/{template['id']}",
        a,
        a.admin,
        json={
            "layout": {"technician": {"sections": [{"id": "x", "fields": ["nope"]}]}},
            "form_rules": [
                {
                    "id": "r",
                    "when": {"field": "impact", "op": "is_null"},
                    "then": [{"do": "hide", "field": "subject"}],
                }
            ],
        },
        headers={"If-Match": f'"{template["version"]}"', **CONSOLE},
    )
    assert field_codes(bad) == {
        "layout.technician.sections.0.fields.0": "not_a_form_field",
        "form_rules.0.then.0.field": "field_always_required",
    }
    # A copy keeps the layout.
    copy = await world.call(
        "POST",
        f"{BASE}/templates/{template['id']}/copy",
        a,
        a.admin,
        json={"labels": {"en": f"Copy {uuid.uuid4().hex[:6]}"}},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert copy.status_code == 201, copy.text
    assert copy.json()["layout"] == template["layout"]


async def test_the_portal_gets_only_rules_and_sections_over_its_own_fields(world: World) -> None:
    """REQ-INC-036 AC2: a staff field's name or a value it tests never reaches the portal."""
    a = world.a
    rules = [
        {
            "id": "own",
            "when": {"field": "description", "op": "is_null"},
            "then": [{"do": "require", "field": "description"}],
        },
        {
            "id": "staff",
            "when": {"field": "group_id", "op": "eq", "value": str(a.ga)},
            "then": [{"do": "require", "field": "description"}],
        },
    ]
    layout = {
        "technician": {
            "sections": [{"id": "all", "names": {"en": "All"}, "fields": ["group_id", "subject"]}]
        },
        "requester": {
            "sections": [
                {
                    "id": "ask",
                    "names": {"en": "Your question"},
                    "fields": ["description", "subject"],
                }
            ]
        },
    }
    template = await new_template(world, a, form_rules=rules, layout=layout, for_requesters=True)
    offered = (await world.call("GET", "/portal/incidents/templates", a, a.requester)).json()
    mine = next(t for t in offered if t["id"] == template["id"])
    assert [r["id"] for r in mine["form_rules"]] == ["own"]
    assert str(a.ga) not in str(mine)
    assert "group_id" not in str(mine)
    assert [(s["id"], s["fields"]) for s in mine["sections"]] == [
        ("ask", ["description", "subject"])
    ]
