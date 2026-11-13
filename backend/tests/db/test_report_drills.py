"""A chart's bar opens its own type's list with the same count (WP-058b S5b; REQ-RPT-037).

The reports drawer sends each row's `drill` filter to that type's list (DrillDrawer, by the
report's `list_path`). For an asset report grouped by state and by the month it was acquired
(a DATE field bucketed by month), and a release report grouped by stage, the list answers with
the very records the bar counted (lane B's check: date bounds and the asset list's view).
"""

import json
from typing import Any

import httpx
import pytest

from tests.db.per_test_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import CONSOLE, Org, World
from tests.db.test_releases_api import REL, a_release

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def _rows(world: World, org: Org, entity: str, group_by: list[dict[str, Any]]) -> Any:  # noqa: ANN401 - JSON
    ran = await world.call(
        "POST",
        "/reports/run",
        org,
        org.admin,
        json={"definition": {"entity": entity, "group_by": group_by}},
        headers=CONSOLE,
    )
    assert ran.status_code == 200, ran.text
    found = ran.json()
    return found["list_path"], found["rows"]


async def _listed(world: World, org: Org, path: str, drill: Any, **params: str) -> int:  # noqa: ANN401 - JSON
    query = httpx.QueryParams({"filter": json.dumps(drill), "limit": "100", **params})
    listed = await world.call("GET", f"/{path}?{query}", org, org.admin)
    assert listed.status_code == 200, (path, drill, listed.text)
    return len(listed.json()["items"])


async def test_an_asset_bar_lists_the_assets_it_counted(world: World) -> None:
    a = world.a
    laptop = await _product(world, a, "laptop", "Drill laptop")
    for acquired in ("2026-01-10", "2026-01-20", "2026-03-05"):
        made = await _add(world, a, {"name": f"Laptop {acquired}", "product_id": laptop,
                                     "acquired_on": acquired})  # fmt: skip
        assert made.status_code == 201, made.text
    for group_by in (
        [{"field": "state_id"}],
        [{"field": "acquired_on", "bucket": "month"}],  # a DATE field: date bounds in the drill
    ):
        path, rows = await _rows(world, a, "asset", group_by)
        assert path == "assets"
        assert rows, group_by
        for row in rows:
            # Every asset, as the report counts them (the trash left out): the "all" view.
            assert await _listed(world, a, path, row["drill"], view="all") == row["values"][0], (
                group_by,
                row,
            )


async def test_a_release_bar_lists_the_releases_it_counted(world: World) -> None:
    a = world.a
    first = await a_release(world, a)
    await a_release(world, a)
    moved = await world.call(
        "POST",
        f"{REL}/{first['id']}/moves",
        a,
        a.admin,
        json={"to_status": "submission_accepted"},
        headers={"If-Match": f'"{first["version"]}"', **CONSOLE},
    )
    assert moved.status_code == 200, moved.text
    path, rows = await _rows(world, a, "release", [{"field": "stage"}])
    assert path == "releases"
    assert {row["keys"][0] for row in rows} >= {"submission", "planning"}
    for row in rows:
        assert await _listed(world, a, path, row["drill"]) == row["values"][0], row
