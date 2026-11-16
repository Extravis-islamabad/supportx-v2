"""The service catalog's erasure port (ADR-052 §4; D-171; lane B's readiness check).

An erased person no longer appears in any item's set-up: owner, approvers and backup approver
pass to the successor; the default technician and planned task owners are cleared. A second full
run changes nothing and counts zero; another tenant is untouched.
"""

import json
import uuid
from typing import Any

from app.modules.service_catalog.service.person_data import PORT
from tests.db.test_erasure_ports_lane_a import _erase
from tests.db.test_incidents_api import Org, World, world  # noqa: F401 - the fixture


async def _item(world: World, org: Org, person: uuid.UUID) -> uuid.UUID:  # noqa: F811
    """An item naming the person everywhere its set-up can (written straight to the table)."""
    item_id = uuid.uuid4()
    await world.sql(
        "INSERT INTO catalog_items (id, tenant_id, names, approval, plan, technician_id, owner_id,"
        " group_id, created_by, updated_by) VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6,"
        " $6, $7, $6, $6)",
        item_id,
        org.tenant,
        json.dumps({"en": "New laptop"}),
        json.dumps(
            {
                "approvers": [
                    {"kind": "person", "person_id": str(person)},
                    {"kind": "requested_for_manager"},
                ],
                "backup_id": str(person),
            }
        ),
        json.dumps([{"title": {"en": "Order it"}, "owner_id": str(person), "group_id": None}]),
        person,
        org.ga,
    )
    return item_id


async def _row(world: World, org: Org, item_id: uuid.UUID) -> Any:  # noqa: F811, ANN401
    (row,) = await world.sql(
        "SELECT owner_id, technician_id, approval, plan, version FROM catalog_items"
        " WHERE tenant_id = $1 AND id = $2",
        org.tenant,
        item_id,
    )
    return row


async def test_an_item_s_set_up_no_longer_names_them(world: World) -> None:  # noqa: F811
    a = world.a
    item = await _item(world, a, a.tech_b)
    counts = await _erase(world, a.tenant, a.tech_b, PORT)
    assert counts == {
        "owners_handed_over": 1,
        "technicians_cleared": 1,
        "approvers_handed_over": 2,  # the named approver and the backup approver
        "task_owners_cleared": 1,
    }
    row = await _row(world, a, item)
    assert row["owner_id"] == a.admin  # the successor (the runner names the tenant admin)
    assert row["technician_id"] is None  # the group takes its requests
    approval = json.loads(row["approval"]) if isinstance(row["approval"], str) else row["approval"]
    plan = json.loads(row["plan"]) if isinstance(row["plan"], str) else row["plan"]
    assert str(a.tech_b) not in json.dumps(approval)
    assert approval["backup_id"] == str(a.admin)
    assert plan[0]["owner_id"] is None
    assert row["version"] == 2
    history = await world.sql(
        "SELECT reason FROM field_changes WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        item,
    )
    assert history
    assert {h["reason"] for h in history} == {"erased_on_request"}
    # Idempotent: a second full run changes nothing and counts zero.
    assert sum((await _erase(world, a.tenant, a.tech_b, PORT)).values()) == 0


async def test_another_tenant_and_other_people_are_untouched(world: World) -> None:  # noqa: F811
    a, b = world.a, world.b
    theirs = await _item(world, b, b.tech_b)
    someone_else = await _item(world, a, a.tech_a)
    await _erase(world, a.tenant, b.tech_b, PORT)  # tenant A's session cannot reach tenant B
    await _erase(world, a.tenant, a.tech_b, PORT)  # nobody named a.tech_b in tenant A
    assert (await _row(world, b, theirs))["owner_id"] == b.tech_b
    assert (await _row(world, a, someone_else))["owner_id"] == a.tech_a
