"""Assets' money in reports (WP-048b S4 bundle; WP-049b S2's fields; REQ-AST-036..038).

- "Book value by cost centre" and "Total cost of ownership" sum each asset's valuation, the
  same numbers the asset's Financials tab shows.
- Only for those who may see money (assets.view_financials): for anyone else the library leaves
  them out and a run of their definition is refused, because the money fields do not exist in
  that person's reporting source.
"""

import uuid
from decimal import Decimal

import httpx
import pytest

from app.modules.analytics.domain.builtin import BUILTIN
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_asset_financials_api import _asset
from tests.db.test_incidents_api import CONSOLE, World

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixture, used by name

MONEY = ("assets_book_value_by_cost_centre", "assets_total_cost_of_ownership")


async def _run(world: World, user: uuid.UUID, code: str) -> httpx.Response:
    return await world.call(
        "POST",
        "/reports/run",
        world.a,
        user,
        json={"definition": BUILTIN[code].definition.model_dump(mode="json"), "language": "en"},
        headers=CONSOLE,
    )


async def test_book_value_by_cost_centre_adds_up_each_centre(world: World) -> None:
    a = world.a
    centre = "CC-REPORT-7"
    for name in ("Money A", "Money B"):
        await _asset(world, a, name, purchase_price="1000.00", cost_centre=centre)
    ran = await _run(world, a.admin, "assets_book_value_by_cost_centre")
    assert ran.status_code == 200, ran.text
    rows = {tuple(r["keys"]): r["values"] for r in ran.json()["rows"]}
    book, count = rows[(centre,)]
    assert count == 2
    assert Decimal(str(book)) == Decimal(2000)  # nothing depreciated yet: worth what it cost


async def test_the_money_reports_are_only_for_those_who_see_money(world: World) -> None:
    a = world.a
    admin = await world.call("GET", "/reports/library", a, a.admin)
    assert set(MONEY) <= {r["code"] for r in admin.json()["builtin"]}
    tech = await world.call("GET", "/reports/library", a, a.tech_a)
    assert tech.status_code == 200, tech.text
    listed = {r["code"] for r in tech.json()["builtin"]}
    assert "assets_by_state" in listed  # assets, yes
    assert not set(MONEY) & listed  # their money, no
    for code in MONEY:
        assert (await _run(world, a.tech_a, code)).status_code == 422
