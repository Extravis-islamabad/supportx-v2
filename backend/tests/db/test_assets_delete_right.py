"""D-185 (product owner, 2026-11-24): moving an asset to the trash is its own right.

`assets.delete` alone opens `DELETE /assets/{asset_id}`: assets.manage no longer stands in, so a
role with manage but not delete is refused, and one with delete succeeds. Vendor support never
holds it (tests/db/test_support_never_through_manage.py); the asset manager holds it by default
(identity_access/tests/role_matrix.json). Real PostgreSQL, the incidents world.
"""

import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_assets_api import _add as add_asset
from tests.db.test_assets_api import _product
from tests.db.test_cmdb_relationships import _given
from tests.db.test_incidents_api import Org, World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, used by name


async def _laptop(world: World, org: Org) -> dict[str, Any]:
    await world.sql(
        "UPDATE tenant_subscriptions SET edition = 'enterprise' WHERE tenant_id = $1", org.tenant
    )
    product = await _product(world, org, "laptop", f"D-185 laptop {uuid.uuid4().hex[:6]}")
    made = await add_asset(
        world, org, {"name": f"Laptop {uuid.uuid4().hex[:6]}", "product_id": product}
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _delete(world: World, org: Org, user: uuid.UUID, asset: dict[str, Any]) -> Any:  # noqa: ANN401 - the response
    return await world.call(
        "DELETE",
        f"/assets/{asset['id']}",
        org,
        user,
        headers={"If-Match": f'"{asset["version"]}"'},
    )


async def test_manage_without_delete_cannot_trash_an_asset(world: World) -> None:
    a = world.a
    asset = await _laptop(world, a)
    await _given(
        world, a, a.requester, "Asset keeper", [("assets.view", "all"), ("assets.manage", "all")]
    )
    refused = await _delete(world, a, a.requester, asset)
    assert refused.status_code == 403, refused.text
    assert refused.json()["params"]["permission"] == "assets.delete"


async def test_delete_alone_trashes_an_asset(world: World) -> None:
    a = world.a
    asset = await _laptop(world, a)
    await _given(
        world, a, a.requester2, "Asset remover", [("assets.view", "all"), ("assets.delete", "all")]
    )
    gone = await _delete(world, a, a.requester2, asset)
    assert gone.status_code == 204, gone.text


# --- lane C's #623 review: no other path trashes an asset without assets.delete -------------


async def test_a_merge_needs_delete_on_the_asset_it_trashes(world: World) -> None:
    a = world.a
    keep, dupe = await _laptop(world, a), await _laptop(world, a)
    await _given(world, a, a.tech_c, "Merger", [("assets.view", "all"), ("assets.manage", "all")])
    preview = await world.call(
        "GET",
        "/assets/merge-preview",
        a,
        a.tech_c,
        params={"first": keep["id"], "second": dupe["id"]},
    )
    assert preview.status_code == 403, preview.text
    merge = await world.call(
        "POST",
        "/assets/merges",
        a,
        a.tech_c,
        json={
            "survivor_id": keep["id"],
            "survivor_version": keep["version"],
            "merged_id": dupe["id"],
            "merged_version": dupe["version"],
            "choices": {},
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert merge.status_code == 403, merge.text
    assert merge.json()["params"]["permission"] == "assets.delete"


async def test_an_overdue_rule_that_trashes_needs_delete(world: World) -> None:
    a = world.a
    await _laptop(world, a)  # the enterprise plan
    await _given(world, a, a.tech_b, "Asset configurer", [("config.assets", "all")])
    preview = await world.call(
        "POST", "/assets/overdue-rule/preview", a, a.tech_b, json={"action": "trash"}
    )
    assert preview.status_code == 403, preview.text
    rule = (await world.call("GET", "/assets/overdue-rule", a, a.admin)).json()
    saved = await world.call(
        "PATCH",
        "/assets/overdue-rule",
        a,
        a.tech_b,
        json={"action": "trash"},
        headers={"If-Match": f'"{rule["version"]}"'},
    )
    assert saved.status_code == 403, saved.text
    assert saved.json()["params"]["permission"] == "assets.delete"


async def test_a_bulk_delete_is_refused_at_start_without_delete(world: World) -> None:
    a = world.a
    asset = await _laptop(world, a)
    await _given(
        world, a, a.lead, "Bulk keeper", [("assets.view", "all"), ("assets.manage", "all")]
    )
    started = await world.call(
        "POST",
        "/assets/bulk-jobs",
        a,
        a.lead,
        json={"action": "delete", "asset_ids": [asset["id"]]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert started.status_code == 403, started.text
    assert started.json()["params"]["permission"] == "assets.delete"
