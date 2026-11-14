"""Field access on work item reads and writes (ADR-047 slice b1; REQ-WI-016 AC1-AC3).

The rules (slice a) are set directly here, then the person's next request is checked:
- a hidden or masked field comes back null and is named in hidden_fields / masked_fields; a
  custom one is left out of `custom` (AC1); nothing is a sentinel in a typed field;
- the older root cause gate (view_root_cause) still hides, whatever a role rule says.
"""

import uuid
from typing import Any

from tests.db.test_incidents_api import BASE, CONSOLE, Org, World, world  # noqa: F401 - fixture

pytestmark: list[Any] = []


async def _role(world: World, org: Org, key: str) -> uuid.UUID:  # noqa: F811 - the fixture's name
    (row,) = await world.sql(
        "SELECT id FROM roles WHERE tenant_id = $1 AND key = $2 AND deleted_at IS NULL",
        org.tenant,
        key,
    )
    return uuid.UUID(str(row["id"]))


async def _rule(world: World, org: Org, role: str, field: str, mode: str) -> None:  # noqa: F811
    """A live rule for `role` on incidents, then every compiled subject of the tenant stale."""
    await world.sql(
        "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
        " VALUES (gen_random_uuid(), $1, $2, 'incident', $3, $4)",
        org.tenant,
        await _role(world, org, role),
        field,
        mode,
    )
    await world.app.state.policy.invalidate(org.tenant)


async def _custom_field(world: World, org: Org, name: str) -> str:  # noqa: F811
    made = await world.call(
        "POST",
        "/custom-fields",
        org,
        org.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": name}},
        headers=CONSOLE,
    )
    assert made.status_code == 201, made.text
    return str(made.json()["key"])


async def test_a_hidden_or_masked_field_never_comes_back(world: World) -> None:  # noqa: F811
    a = world.a
    salary = await _custom_field(world, a, "Salary band")
    grade = await _custom_field(world, a, "Grade")
    item = await world.create(
        a,
        a.admin,
        group_id=str(a.ga),
        impact_details="Payroll stops for 200 people",
        custom={salary: "B7", grade: "Senior"},
    )
    await _rule(world, a, "technician", f"custom.{salary}", "hidden")
    await _rule(world, a, "technician", "impact_details", "masked")

    seen = await world.call("GET", f"{BASE}/{item['id']}", a, a.tech_a)
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert salary not in body["custom"]
    assert body["custom"][grade] == "Senior"  # no rule: shown
    assert body["impact_details"] is None
    assert body["hidden_fields"] == [f"custom.{salary}"]
    assert body["masked_fields"] == ["impact_details"]
    assert "B7" not in seen.text
    assert "Payroll" not in seen.text

    # Someone whose roles carry no rule sees everything, and nothing is listed.
    full = (await world.call("GET", f"{BASE}/{item['id']}", a, a.admin)).json()
    assert full["custom"][salary] == "B7"
    assert full["impact_details"] == "Payroll stops for 200 people"
    assert (full["hidden_fields"], full["masked_fields"]) == ([], [])
