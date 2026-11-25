"""The charge-back report (WP-047b S1; REQ-CAT-021 AC2; lane C's conditions 2-3).

Real PostgreSQL with RLS. A service request report groups by item and department and sums what
was charged, for those who may see costs; anyone else naming a money field, in a run or an
export request, is refused as `field_not_permitted` before any value is read (the source
withholds them: every path, interactive, saved, scheduled or exported, compiles from it).
"""

import uuid
from typing import Any

import pytest

from tests.db import test_reports_api
from tests.db.test_incidents_api import CONSOLE, Org, World

pytestmark = pytest.mark.db

world = test_reports_api.world
reports = test_reports_api.reports

MONEY = ("charged_amount", "estimated_cost")
BY_ITEM = {
    "entity": "service_request",
    "group_by": [{"field": "catalog_item_id"}, {"field": "charge_department_id"}],
    "measures": ["count"],
}


async def _run(world: World, org: Org, user: uuid.UUID, definition: dict[str, Any]) -> Any:  # noqa: ANN401 - the response
    return await world.call(
        "POST",
        "/reports/run",
        org,
        user,
        json={"definition": definition, "language": "en"},
        headers=CONSOLE,
    )


async def test_money_fields_need_the_cost_right_wherever_they_are_named(
    reports: World,
) -> None:
    world, a = reports, reports.a
    for field in MONEY:
        use = {"entity": "service_request", "columns": ["display_id", field], "measures": ["count"]}
        refused = await _run(world, a, a.tech_a, use)
        assert refused.status_code == 403, (field, refused.text)
        assert refused.json()["code"] == "field_not_permitted", field
        exported = await world.call(
            "POST",
            "/reports/exports",
            a,
            a.tech_a,
            json={"title": "Charge-back", "definition": use},
            headers=CONSOLE,
        )
        assert exported.status_code == 403, (field, exported.text)
        allowed = await _run(world, a, a.admin, use)
        assert allowed.status_code == 200, (field, allowed.text)


async def test_charge_back_groups_by_item_and_department(reports: World) -> None:
    """AC2's shape: by item and department (the month is the charged_at bucket)."""
    world, a = reports, reports.a
    ran = await _run(world, a, a.admin, BY_ITEM)
    assert ran.status_code == 200, ran.text
    monthly = await _run(
        world,
        a,
        a.admin,
        {**BY_ITEM, "group_by": [{"field": "charged_at", "bucket": "month"}, *BY_ITEM["group_by"]]},
    )
    assert monthly.status_code == 200, monthly.text
