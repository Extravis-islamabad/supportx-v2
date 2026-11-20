"""A site-scoped asset viewer sees only their sites' records in the asset registers (#423 scope).

The loan register lists loans with each asset's tag and name. A person whose `assets.view` is
limited to their sites must see only the loans of assets they may see, never another site's.
Real PostgreSQL and Valkey on the incident world; every record is new (rule 5h).
"""

import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_asset_loans_api import _loan, _loanable
from tests.db.test_assets_api import _add, _product
from tests.db.test_cmdb_relationships import _given
from tests.db.test_incidents_api import World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


async def _asset_at(world: World, name: str, site: uuid.UUID) -> dict[str, Any]:
    a = world.a
    product = await _product(world, a, "laptop", f"Scope {name}")
    made = await _add(world, a, {"name": name, "product_id": product, "site_id": str(site)})
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_the_loan_register_shows_only_the_viewers_sites(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    near = await _asset_at(world, f"Near laptop {tag}", a.s1)
    far = await _asset_at(world, f"Far laptop {tag}", a.s2)
    await _loanable(world, near, far)
    for asset in (near, far):
        lent = await _loan(world, [asset], a.tech_a)
        assert lent.status_code == 201, lent.text
    # The control: the admin sees both loans.
    everyone = await world.call("GET", "/assets/loans", a, a.admin)
    assert everyone.status_code == 200, everyone.text
    assert f"Near laptop {tag}" in everyone.text
    assert f"Far laptop {tag}" in everyone.text
    # requester is a member of site S1 only (the incident world); their asset view is site-scoped.
    await _given(world, a, a.requester, f"Site asset viewer {tag}", [("assets.view", "site")])
    seen = await world.call("GET", "/assets/loans", a, a.requester)
    assert seen.status_code == 200, seen.text
    assert f"Near laptop {tag}" in seen.text  # the control: their own site's loan is there
    assert f"Far laptop {tag}" not in seen.text, "another site's loan reached a site-scoped viewer"
    assert far["id"] not in seen.text
