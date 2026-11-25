"""Vendor support never writes through `*.manage` what is `never` for it (D-173; REPRODUCED 11-24).

`cmdb.delete` is `never` for support (tenant_decision), but a `view_and_change` grant gives
`cmdb.manage`, and the CMDB lets manage stand in: the delete route takes DELETE or MANAGE, the
service's `cis.writer` falls back to MANAGE (delete, restore), and merge checks `holds(MANAGE)`.
Assets: `delete_asset` needs only `assets.manage`, which support holds on a change grant (lane C).

Reproduced on 2026-11-24 (CI delete 204, restore 200, merge 201, asset delete 204 for a real
`view_and_change` support account). Fixed for the CMDB: `cmdb.manage` is never for support, and
`cis.writer` never lets manage stand in for delete or restore. The negative control: the tenant
admin does each of them (2xx), so the routes do act. Asset delete waits on the product owner's
decision (an `assets.delete` right, or `assets.manage` never): a strict expected failure until then.
"""

import uuid
from typing import Any

import pytest

from tests.db.test_assets_api import _product
from tests.db.test_cmdb_api import _ci
from tests.db.test_identity_api import World, world  # noqa: F401 - the fixture, reused
from tests.db.test_knowledge_api import _match, _new
from tests.db.test_support_access_compile import _compiled, _support_user

pytestmark = pytest.mark.db


async def _made(world: World, name: str) -> dict[str, Any]:  # noqa: F811 - the reused fixture
    found = await _ci(world, world.a, name, "server")  # type: ignore[arg-type]
    assert found.status_code == 201, found.text
    return dict(found.json())


async def _trashed(world: World, name: str) -> dict[str, Any]:  # noqa: F811 - the reused fixture
    ci = await _made(world, name)
    gone = await world.call(
        "DELETE", f"/cmdb/cis/{ci['id']}", world.a, world.a.admin, headers=_match(ci["version"])
    )
    assert gone.status_code == 204, gone.text
    return {**ci, "version": ci["version"] + 1}  # the removal's version


async def _asset(world: World, name: str) -> dict[str, Any]:  # noqa: F811 - the reused fixture
    product = await _product(world, world.a, "laptop", f"Laptop {name}")  # type: ignore[arg-type]
    made = await world.call(
        "POST",
        "/assets",
        world.a,
        world.a.admin,
        json={"name": name, "product_id": product},
        headers=_new(),
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _tries(world: World, user: uuid.UUID, tag: str) -> dict[str, int]:  # noqa: F811
    """Each of the four writes, as `user`, on records made for this run; their statuses."""
    a = world.a
    target = await _made(world, f"Delete {tag}")
    binned = await _trashed(world, f"Restore {tag}")
    keep, dupe = await _made(world, f"Keep {tag}"), await _made(world, f"Dupe {tag}")
    asset = await _asset(world, f"Asset {tag}")
    deleted = await world.call(
        "DELETE", f"/cmdb/cis/{target['id']}", a, user, headers=_match(target["version"])
    )
    restored = await world.call(
        "POST",
        f"/cmdb/cis/{binned['id']}/restore",
        a,
        user,
        headers=_match(binned["version"]),
    )
    merged = await world.call(
        "POST",
        "/cmdb/merges",
        a,
        user,
        json={
            "survivor_id": keep["id"],
            "survivor_version": keep["version"],
            "merged_id": dupe["id"],
            "merged_version": dupe["version"],
            "choices": {},
        },
        headers=_new(),
    )
    asset_gone = await world.call(
        "DELETE", f"/assets/{asset['id']}", a, user, headers=_match(asset["version"])
    )
    return {
        "ci_delete": deleted.status_code,
        "ci_restore": restored.status_code,
        "ci_merge": merged.status_code,
        "asset_delete": asset_gone.status_code,
    }


async def test_reproduce_support_writing_through_manage(world: World) -> None:  # noqa: F811
    _, support = await _support_user(
        world, access="view_and_change", change_reason="Fix the CMDB sync rule on CI-7"
    )
    subject = await _compiled(world, support)
    assert subject.support_grant_id is not None
    held = {p for p in ("cmdb.manage", "cmdb.delete", "assets.manage") if p in subject.grants}
    tag = uuid.uuid4().hex[:6]
    control = await _tries(world, world.a.admin, f"admin {tag}")  # the negative control
    assert all(200 <= s < 300 for s in control.values()), control
    found = await _tries(world, support, f"support {tag}")
    assert "cmdb.manage" not in held, held
    cmdb_writes = {k: v for k, v in found.items() if k.startswith("ci_")}
    assert all(s in {403, 404} for s in cmdb_writes.values()), (sorted(held), found)


async def test_support_never_deletes_an_asset(world: World) -> None:  # noqa: F811
    """D-185: deleting an asset is its own right (`assets.delete`), never vendor support's."""
    _, support = await _support_user(
        world, access="view_and_change", change_reason="Fix the asset import on AST-3"
    )
    asset = await _asset(world, f"Asset only {uuid.uuid4().hex[:6]}")
    gone = await world.call(
        "DELETE", f"/assets/{asset['id']}", world.a, support, headers=_match(asset["version"])
    )
    assert gone.status_code in {403, 404}, gone.text
