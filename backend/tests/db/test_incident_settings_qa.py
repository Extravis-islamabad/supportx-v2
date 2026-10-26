"""WP-020c QA findings and review answers (WP-020c-FIX; D-086). Each test failed before its fix.

Findings: ~/Desktop/qa-wp020c/QA-REPORT.md. Same world as the incidents tests.
"""

from typing import Any

from tests.db.test_incident_settings_api import (
    SETTINGS,
    admin_write,
    catalogue,
    new_template,
    patch_template,
    templates,
)
from tests.db.test_incidents_api import World, field_codes, world

__all__ = ["world"]  # the fixture, re-used


async def test_bug_01_numbering_save_is_all_or_nothing(world: World) -> None:
    a = world.a
    await world.create(a, a.admin)
    await world.create(a, a.admin)
    # A valid prefix and a next number already used, in one save: nothing is saved.
    refused = await admin_write(world, a, "PATCH", SETTINGS, {"prefix": "QAT", "next_number": 1})
    assert field_codes(refused) == {"next_number": "number_already_used"}
    after = await catalogue(world, a)
    assert (after["prefix"], after["next_number"]) == ("INC", 3)
    # Both valid: both saved, one version step.
    saved = await admin_write(world, a, "PATCH", SETTINGS, {"prefix": "QAT", "next_number": 50})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["prefix"], body["next_number"], body["version"]) == (
        "QAT",
        50,
        after["version"] + 1,
    )
    assert (await world.create(a, a.admin))["display_id"] == "QAT-50"
    # Every problem at once, each at its field.
    both = await admin_write(world, a, "PATCH", SETTINGS, {"prefix": "q1", "next_number": 2})
    assert field_codes(both) == {"prefix": "invalid_prefix", "next_number": "number_already_used"}


async def test_bug_04_transitions_come_in_life_cycle_order(world: World) -> None:
    cat = await catalogue(world, world.a)
    order = [s["code"] for s in cat["statuses"]]
    actions = cat["actions"]
    keys = [(order.index(t["from_status"]), actions.index(t["action"])) for t in cat["transitions"]]
    assert keys == sorted(keys)
    assert cat["transitions"][0]["from_status"] == "new"


async def _required_template(world: World) -> dict[str, Any]:
    made = await new_template(
        world,
        world.a,
        labels={"en": "Needs details"},
        fields={"impact_details": {"shown": True, "required": True}},
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_d086_template_required_field_cannot_be_emptied_later(world: World) -> None:
    a = world.a
    template = await _required_template(world)
    item = await world.create(a, a.admin, template_id=template["id"], impact_details="Floor 2")
    emptied = await world.patch(a, a.admin, item, impact_details="")
    assert field_codes(emptied) == {"impact_details": "required"}
    # Other edits are fine.
    edited = await world.patch(a, a.admin, item, subject="Floor 2 printers")
    assert edited.status_code == 200, edited.text


async def test_d086_field_made_required_later_blocks_only_emptying(world: World) -> None:
    a = world.a
    standard = (await templates(world, a))[0]
    old = await world.create(a, a.admin, tags=["vip"])  # no impact details, no category
    made = await patch_template(
        world,
        a,
        standard,
        fields={"impact_details": {"required": True}, "tags": {"required": True}},
    )
    assert made.status_code == 200, made.text
    # The old incident misses impact details: other edits still work.
    edited = await world.patch(a, a.admin, old, subject="Still editable")
    assert edited.status_code == 200, edited.text
    # Emptying a now-required field that was filled is refused.
    emptied = await world.patch(a, a.admin, edited.json(), tags=[])
    assert field_codes(emptied) == {"tags": "required"}


async def test_d086_subject_and_requester_stay_visible_and_fillable_by_requesters(
    world: World,
) -> None:
    a = world.a
    for field, flag in (("subject", "requester_can_fill"), ("requester_id", "requester_can_see")):
        refused = await new_template(
            world, a, labels={"en": f"Hidden {field}"}, fields={field: {flag: False}}
        )
        assert field_codes(refused) == {f"fields.{field}": "requester_always_needed"}, field
    standard = (await templates(world, a))[0]
    assert standard["fields"]["subject"]["requester_can_fill"] is True
    assert standard["fields"]["requester_id"]["requester_can_see"] is True
