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


async def test_lists_leave_out_withheld_custom_values(world: World) -> None:  # noqa: F811
    a = world.a
    salary = await _custom_field(world, a, "Salary band")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={salary: "B7"})
    await _rule(world, a, "technician", f"custom.{salary}", "masked")
    page = await world.call("GET", BASE, a, a.tech_a)
    assert page.status_code == 200, page.text
    row = next(r for r in page.json()["items"] if r["id"] == item["id"])
    assert salary not in row["custom"]
    assert row["masked_fields"] == [f"custom.{salary}"]
    assert "B7" not in page.text
    mine = next(r for r in (await world.call("GET", BASE, a, a.admin)).json()["items"]
                if r["id"] == item["id"])  # fmt: skip
    assert mine["custom"][salary] == "B7"


async def test_history_leaves_out_hidden_changes_and_masks_masked_ones(world: World) -> None:  # noqa: F811
    a = world.a
    salary = await _custom_field(world, a, "Salary band")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={salary: "B7"})
    changed = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"custom": {salary: "C9"}, "impact_details": "Whole floor down"},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert changed.status_code == 200, changed.text
    await _rule(world, a, "technician", f"custom.{salary}", "hidden")
    await _rule(world, a, "technician", "impact_details", "masked")
    seen = await world.call("GET", f"{BASE}/{item['id']}/history", a, a.tech_a)
    assert seen.status_code == 200, seen.text
    fields = [c for e in seen.json()["items"] for c in e["changes"]]
    assert not [c for c in fields if c["field"] == f"custom.{salary}"]
    (impact,) = [c for c in fields if c["field"] == "impact_details"]
    assert impact["hidden"] is True
    for value in ("B7", "C9", "Whole floor"):
        assert value not in seen.text
    full = await world.call("GET", f"{BASE}/{item['id']}/history", a, a.admin)
    assert "C9" in full.text


async def test_a_read_only_field_cannot_be_changed_by_that_person(world: World) -> None:  # noqa: F811
    """AC3: 403 `field_read_only`; sending the value back unchanged is fine; others may change."""
    a = world.a
    salary = await _custom_field(world, a, "Salary band")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={salary: "B7"})
    await _rule(world, a, "technician", f"custom.{salary}", "read_only")

    async def patch(user: uuid.UUID, version: int, **body: Any) -> Any:  # noqa: ANN401 - JSON
        return await world.call(
            "PATCH",
            f"{BASE}/{item['id']}",
            a,
            user,
            json=body,
            headers={"If-Match": f'"{version}"', **CONSOLE},
        )

    seen = (await world.call("GET", f"{BASE}/{item['id']}", a, a.tech_a)).json()
    assert seen["custom"][salary] == "B7"  # read-only: shown
    refused = await patch(a.tech_a, seen["version"], custom={salary: "C9"})
    assert (refused.status_code, refused.json()["code"]) == (403, "field_read_only"), refused.text
    assert refused.json()["params"] == {"field": f"custom.{salary}"}
    same = await patch(a.tech_a, seen["version"], custom={salary: "B7"}, subject="Printer down")
    assert same.status_code == 200, same.text  # the read-only value sent back unchanged
    done = await patch(a.admin, same.json()["version"], custom={salary: "C9"})
    assert done.status_code == 200, done.text


async def test_a_read_only_field_cannot_be_filled_in_on_create(world: World) -> None:  # noqa: F811
    a = world.a
    salary = await _custom_field(world, a, "Salary band")
    await _rule(world, a, "technician", f"custom.{salary}", "read_only")
    refused = await world.call(
        "POST",
        BASE,
        a,
        a.tech_a,
        json={
            "subject": "New starter",
            "requester_id": str(a.requester),
            "group_id": str(a.ga),
            "custom": {salary: "B7"},
        },
        headers={**CONSOLE, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert (refused.status_code, refused.json()["code"]) == (403, "field_read_only"), refused.text
    empty = await world.call(
        "POST",
        BASE,
        a,
        a.tech_a,
        json={
            "subject": "New starter",
            "requester_id": str(a.requester),
            "group_id": str(a.ga),
            "custom": {salary: None},
        },
        headers={**CONSOLE, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert empty.status_code == 201, empty.text  # left empty: fine


async def test_a_withheld_field_cannot_be_filtered_or_sorted(world: World) -> None:  # noqa: F811
    """AC2: a masked field is neither searchable nor sortable for that person."""
    import json  # noqa: PLC0415 - one test

    a = world.a
    salary = await _custom_field(world, a, "Salary band")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={salary: "B7"})
    await _rule(world, a, "technician", f"custom.{salary}", "masked")
    probe = json.dumps({"field": f"custom.{salary}", "op": "eq", "value": "B7"})
    filtered = await world.call("GET", BASE, a, a.tech_a, params={"filter": probe})
    assert filtered.status_code == 422, filtered.text
    sorted_ = await world.call("GET", BASE, a, a.tech_a, params={"sort": f"custom.{salary}"})
    assert sorted_.status_code == 422, sorted_.text
    fields = (await world.call("GET", f"{BASE}/list-fields", a, a.tech_a)).json()
    assert f"custom.{salary}" not in {f["name"] for f in fields}
    # Without the rule (the admin): the filter finds the record.
    found = await world.call("GET", BASE, a, a.admin, params={"filter": probe})
    assert found.status_code == 200, found.text
    assert [r["id"] for r in found.json()["items"]] == [item["id"]]


async def test_a_report_cannot_name_a_withheld_field(world: World) -> None:  # noqa: F811
    """ADR-047 §5: a report, dashboard or export filtering on a masked field is refused."""
    a = world.a
    salary = await _custom_field(world, a, "Salary band")
    await world.create(a, a.admin, group_id=str(a.ga), custom={salary: "B7"})
    await _rule(world, a, "technician", f"custom.{salary}", "masked")
    definition = {
        "entity": "incident",
        "filter": {"field": f"custom.{salary}", "op": "eq", "value": "B7"},
        "measures": ["count"],
    }

    async def run(user: uuid.UUID) -> Any:  # noqa: ANN401 - the response
        return await world.call(
            "POST",
            "/reports/run",
            a,
            user,
            json={"definition": definition, "language": "en"},
            headers=CONSOLE,
        )

    refused = await run(a.tech_a)
    assert refused.status_code in {403, 422}, refused.text
    assert "B7" not in refused.text
    ran = await run(a.admin)
    assert ran.status_code == 200, ran.text


async def test_an_api_key_gets_the_same_redaction_as_its_owner(world: World) -> None:  # noqa: F811
    """Lane B's condition: a key acts as its owner narrowed to its scopes, so what the owner's
    roles withhold, the key never reads (the real compile, through subject_for and for_key)."""
    from fastapi import Request  # noqa: PLC0415 - one test

    from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext  # noqa: PLC0415
    from tests.db.test_access_api import fake_session  # noqa: PLC0415

    async def key_session(request: Request) -> TenantContext | None:
        tenant, user = request.headers.get("x-test-tenant"), request.headers.get("x-test-user")
        if tenant is None or user is None:
            return None
        return TenantContext(
            uuid.UUID(tenant), uuid.UUID(user), api_scopes=frozenset({"incidents:read"})
        )

    a = world.a
    salary = await _custom_field(world, a, "Salary band")
    item = await world.create(a, a.admin, group_id=str(a.ga), custom={salary: "B7"})
    await _rule(world, a, "technician", f"custom.{salary}", "hidden")
    setattr(world.app.state, SESSION_RESOLVER_STATE, key_session)
    try:
        seen = await world.call("GET", f"{BASE}/{item['id']}", a, a.tech_a)
    finally:
        setattr(world.app.state, SESSION_RESOLVER_STATE, fake_session)
    assert seen.status_code == 200, seen.text
    assert salary not in seen.json()["custom"]
    assert seen.json()["hidden_fields"] == [f"custom.{salary}"]
    assert "B7" not in seen.text
