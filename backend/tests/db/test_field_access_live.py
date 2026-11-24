"""A rule saved through the API reaches a person whose subject is already compiled (ADR-047 rule c).

The e2e journey field-access.spec failed alone on a fresh stack (Stack smoke run 45294459888):
the technician held exactly the one role carrying the rule, and still read the field for 10 s.
The slice b1 read tests set rules by SQL and invalidate the policy themselves, with a subject
never compiled before; this one does what the journey does: the technician reads the record
first (their subject is cached), the administrator saves the rule through
POST /field-access/rules, and the technician reads again.
"""

import uuid
from typing import Any

from tests.db.test_field_access_reads import _role
from tests.db.test_incidents_api import BASE, CONSOLE, World, world  # noqa: F401 - fixture

pytestmark: list[Any] = []

FIELD = "impact_details"


async def _save_rule(world: World, role_id: uuid.UUID) -> None:  # noqa: F811 - the fixture's name
    a = world.a
    saved = await world.call(
        "POST",
        "/field-access/rules",
        a,
        a.admin,
        json={"role_id": str(role_id), "record_type": "incident", "field": FIELD, "mode": "hidden"},
        headers=CONSOLE,
    )
    assert saved.status_code == 201, saved.text


async def _read(world: World, item: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    seen = await world.call("GET", f"{BASE}/{item['id']}", world.a, world.a.tech_a)
    assert seen.status_code == 200, seen.text
    return dict(seen.json())


async def test_a_rule_saved_through_the_api_hides_the_field_from_a_cached_subject(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    item = await world.create(
        a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga), impact_details="Payroll stops"
    )
    before = await _read(world, item)  # compiles and caches the technician's subject
    assert before["impact_details"] == "Payroll stops"
    await _save_rule(world, await _role(world, a, "technician"))
    after = await _read(world, item)
    assert after["impact_details"] is None, after["impact_details"]
    assert FIELD in after["hidden_fields"]


async def test_a_rule_saved_through_the_api_hides_the_field_from_a_fresh_subject(
    world: World,  # noqa: F811
) -> None:
    """The control: the same rule, with no read before it (nothing cached)."""
    a = world.a
    item = await world.create(
        a, a.admin, technician_id=str(a.tech_a), group_id=str(a.ga), impact_details="Payroll stops"
    )
    await _save_rule(world, await _role(world, a, "technician"))
    after = await _read(world, item)
    assert after["impact_details"] is None, after["impact_details"]
    assert FIELD in after["hidden_fields"]
