"""A pasted ID or name with directional marks still matches (isolation rule, 2026-10-29).

Screens wrap filled values in Unicode isolates (FSI…PDI); a person copying "INC-12" or a name
from a screen pastes the marks too. Search, the display-ID lookup and the pickers ignore them.
"""

import pytest

from tests.db.test_incidents_api import BASE, World, world

__all__ = ["world"]  # fixture, re-used

pytestmark = [pytest.mark.db]

FSI, PDI = "\u2068", "\u2069"


async def test_a_pasted_display_id_with_marks_finds_its_record(world: World) -> None:
    a = world.a
    made = await world.create(a, a.admin, subject="Pasted marks printer")
    marked = f"{FSI}{made['display_id']}{PDI}"
    found = await world.call("GET", f"{BASE}/search", a, a.admin, params={"q": marked})
    assert found.status_code == 200, found.text
    assert made["id"] in [item["id"] for item in found.json()["items"]]
    looked = await world.call("GET", f"{BASE}/lookup/{marked}", a, a.admin)
    assert looked.status_code == 200, looked.text


async def test_a_pasted_name_with_marks_finds_the_person(world: World) -> None:
    a = world.a
    people = await world.call("GET", "/users", a, a.admin, params={"limit": 1})
    person = people.json()["items"][0]
    marked = f"{FSI}{person['display_name']}{PDI}"
    found = await world.call("GET", "/users", a, a.admin, params={"q": marked})
    assert found.status_code == 200, found.text
    assert person["id"] in [item["id"] for item in found.json()["items"]]
