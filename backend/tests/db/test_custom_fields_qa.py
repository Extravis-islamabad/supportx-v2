"""WP-026 QA findings (WP-026-FIX; D-091). Each test failed before its fix.

Findings: ~/Desktop/qa-wp026/QA-REPORT.md. Same world as the custom fields tests.
"""

from typing import Any

from tests.db.test_custom_fields_api import FIELDS, add, add_field, change, choices
from tests.db.test_incidents_api import BASE, CONSOLE, World, field_codes, world
from tests.db.test_search_api import found, search

__all__ = ["world"]  # the fixture, re-used


def errors_of(response: Any) -> dict[str, dict[str, Any]]:  # noqa: ANN401 - httpx response
    assert response.status_code == 422, response.text
    return {
        e["field"].removeprefix("body."): {"code": e["code"], "params": e.get("params") or {}}
        for e in response.json()["errors"]
    }


async def test_bug_01_a_stale_save_is_refused_and_says_who_changed_what(world: World) -> None:
    a = world.a
    field = await add_field(world, a, field_type="text", labels={"en": "Asset tag"})
    theirs = await change(world, a, field, labels={"en": "Asset tag (theirs)"})
    assert theirs.status_code == 200, theirs.text
    # The list says who saved last, so an open editor can say "changed by" at once.
    listed = (await world.call("GET", f"{FIELDS}?entity=incident", a, a.admin)).json()
    assert listed[0]["changed_by"] == "Alpha Admin"
    assert listed[0]["changed_at"] is not None
    # A save from the version the editor started with is refused, naming who and what.
    mine = await change(world, a, field, help={"en": "Mine"})
    assert mine.status_code == 409
    params = mine.json()["params"]
    assert params["changed_by"] == "Alpha Admin"
    assert params["changed_fields"] == "labels"
    for method, path in (
        ("DELETE", f"{FIELDS}/{field['id']}"),
        ("POST", f"{FIELDS}/{field['id']}/index"),
    ):
        stale = await world.call(
            method,
            path,
            a,
            a.admin,
            headers={"If-Match": f'"{field["version"]}"', **CONSOLE},
        )
        assert stale.status_code == 409, path
        assert stale.json()["params"]["changed_by"] == "Alpha Admin", path


async def test_bug_02_email_web_address_and_phone_values_are_searchable(world: World) -> None:
    a = world.a
    for kind, name in (("email", "Contact"), ("url", "Link"), ("phone", "Phone")):
        await add_field(world, a, field_type=kind, labels={"en": name})
    item = await world.create(
        a,
        a.admin,
        subject="Status page down",
        custom={
            "contact": "ops.team@example.com",
            "link": "https://status.example.com/incident/42",
            "phone": "+92 300 1234567",
        },
    )
    for words in ("ops.team@example.com", "status.example.com", "ops", "1234567"):
        assert item["id"] in found(await search(world, a, a.lead, words)), words


async def test_bug_03_out_of_range_values_are_refused_with_the_limit(world: World) -> None:
    a = world.a
    await add_field(
        world,
        a,
        field_type="decimal",
        labels={"en": "Cost"},
        validation={"min": "1", "max": "1000.5"},
    )
    await add_field(world, a, field_type="integer", labels={"en": "Seats"})
    await add_field(
        world,
        a,
        field_type="text",
        labels={"en": "Tag"},
        validation={"min_length": 8, "max_length": 10},
    )
    refused = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={
            "subject": "x",
            "requester_id": str(a.requester),
            "custom": {"cost": 5000, "seats": 4.5, "tag": "abc"},
        },
        headers=CONSOLE,
    )
    problems = errors_of(refused)
    assert problems["custom.cost"] == {"code": "above_maximum", "params": {"max": "1000.5"}}
    assert problems["custom.seats"]["code"] == "whole_number_required"
    # C3: too short names the minimum.
    assert problems["custom.tag"] == {"code": "value_too_short", "params": {"min": 8}}
    low = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "custom": {"cost": 0.5}},
        headers=CONSOLE,
    )
    assert errors_of(low)["custom.cost"] == {"code": "below_minimum", "params": {"min": "1"}}
    long = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "custom": {"tag": "x" * 11}},
        headers=CONSOLE,
    )
    assert errors_of(long)["custom.tag"] == {"code": "value_too_long", "params": {"max": 10}}


async def test_bug_05_a_name_needs_a_letter_or_digit(world: World) -> None:
    a = world.a
    refused = await add(world, a, field_type="text", labels={"en": "!!!"})
    assert field_codes(refused) == {"labels": "name_needs_letters"}
    choice = await add(world, a, field_type="choice", labels={"en": "Floor"}, choices=choices("--"))
    assert field_codes(choice) == {"choices[0].labels": "name_needs_letters"}
    assert (await add(world, a, field_type="text", labels={"en": "طابق"})).status_code == 201


async def test_bug_06_a_risky_pattern_says_why(world: World) -> None:
    a = world.a
    risky = await add(
        world, a, field_type="text", labels={"en": "Code"}, validation={"pattern": "(a+)+$"}
    )
    assert field_codes(risky) == {"validation.pattern": "pattern_too_complex"}
    broken = await add(
        world, a, field_type="text", labels={"en": "Code"}, validation={"pattern": "("}
    )
    assert field_codes(broken) == {"validation.pattern": "invalid_pattern"}


async def test_c7_no_starting_value_is_stored_as_none(world: World) -> None:
    a = world.a
    field = await add_field(world, a, field_type="decimal", labels={"en": "Cost"})
    rows = await world.sql(
        "SELECT default_value IS NULL AS empty FROM custom_fields WHERE id = $1", field["id"]
    )
    assert rows[0]["empty"] is True
