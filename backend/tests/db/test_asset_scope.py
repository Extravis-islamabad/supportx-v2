"""A site-scoped asset manager never adds an asset at, nor moves one to, a site outside it.

`assets.manage` held in *some* scope used to be enough for a create (lane B, 2026-11-12): a
manager of site S1 could add assets at S2, or with no site, and then move their own S1 asset to
S2. The saved asset must be one the person may manage, by the resource's own scope rules
(site: its site among theirs; group: their sites and unsited assets).
"""

import uuid
from typing import Any

import pytest

from tests.db import test_incidents_api
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import World, problem, role

pytestmark = pytest.mark.db

world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"


async def _site_manager(world: World) -> uuid.UUID:
    """Tech A sees every asset but manages those of their own site (S1) only."""
    a = world.a
    made = await role(
        world, a, "S1 asset keeper", [("assets.view", "all"), ("assets.manage", "site")]
    )
    granted = await world.call("PUT", f"/users/{a.tech_a}/roles/{made}", a, a.admin)
    assert granted.status_code == 204, granted.text
    return a.tech_a


async def _count(world: World, name: str) -> int:
    rows = await world.sql(
        "SELECT count(*) AS n FROM assets WHERE tenant_id = $1 AND name = $2", world.a.tenant, name
    )
    return int(rows[0]["n"])


async def test_a_site_manager_adds_assets_only_at_their_own_site(world: World) -> None:
    a = world.a
    tech = await _site_manager(world)
    product = await _product(world, a, "laptop", f"Scope laptop {uuid.uuid4().hex[:6]}")

    mine = await _add(
        world, a, {"name": "Scope S1", "product_id": product, "site_id": str(a.s1)}, user=tech
    )
    assert mine.status_code == 201, mine.text

    elsewhere = await _add(
        world, a, {"name": "Scope S2", "product_id": product, "site_id": str(a.s2)}, user=tech
    )
    assert problem(elsewhere) == (403, "asset_site_not_managed")
    assert await _count(world, "Scope S2") == 0  # nothing kept

    nowhere = await _add(world, a, {"name": "Scope none", "product_id": product}, user=tech)
    assert problem(nowhere) == (403, "asset_site_not_managed")  # unsited: beyond a site scope
    assert await _count(world, "Scope none") == 0


async def test_a_site_manager_never_moves_an_asset_to_another_site(world: World) -> None:
    a = world.a
    tech = await _site_manager(world)
    product = await _product(world, a, "laptop", f"Move laptop {uuid.uuid4().hex[:6]}")
    made = await _add(
        world, a, {"name": "Scope mover", "product_id": product, "site_id": str(a.s1)}, user=tech
    )
    assert made.status_code == 201, made.text
    asset: dict[str, Any] = made.json()
    moved = await world.call(
        "PATCH",
        f"{BASE}/{asset['id']}",
        a,
        tech,
        json={"site_id": str(a.s2)},
        headers={"If-Match": f'"{asset["version"]}"'},
    )
    assert problem(moved) == (403, "asset_site_not_managed")
    rows = await world.sql("SELECT site_id FROM assets WHERE id = $1", uuid.UUID(asset["id"]))
    assert rows[0]["site_id"] == a.s1  # unchanged
    # A change that keeps the site is still fine.
    renamed = await world.call(
        "PATCH",
        f"{BASE}/{asset['id']}",
        a,
        tech,
        json={"location": "Shelf 2"},
        headers={"If-Match": f'"{asset["version"]}"'},
    )
    assert renamed.status_code == 200, renamed.text


async def test_an_all_scope_manager_still_adds_anywhere(world: World) -> None:
    a = world.a
    product = await _product(world, a, "laptop", f"Admin laptop {uuid.uuid4().hex[:6]}")
    for name, site in (("Admin S2", str(a.s2)), ("Admin none", None)):
        made = await _add(world, a, {"name": name, "product_id": product, "site_id": site})
        assert made.status_code == 201, made.text
