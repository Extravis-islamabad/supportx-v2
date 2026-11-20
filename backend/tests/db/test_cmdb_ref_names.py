"""A CI's references by name, through the reader's current rights (CMDB polish, after #550).

The record, "as of" and compare carry `names` for the site, owner, groups, asset and person custom
values: a label for a reader who may see the thing, `restricted` for one who may not, never an ID
(rule d). A business view carries its base CI.

Real PostgreSQL and Valkey on the incident world; every organisation is new (rule 5h).
"""

import uuid
from typing import Any

import pytest

from app.modules.cmdb.service import ref_names
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_assets_api import _add as add_asset
from tests.db.test_assets_api import _product
from tests.db.test_cmdb_custom_fields import _field
from tests.db.test_cmdb_relationships import BASE, _given, _made, _view
from tests.db.test_incidents_api import World
from tests.db.test_knowledge_api import _match

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used


def _no_ids_as_labels(names: dict[str, Any]) -> None:
    for name in names.values():
        label = name.get("label")
        if label is None:
            continue
        try:
            uuid.UUID(label)
        except ValueError:
            continue
        pytest.fail(f"an ID was given as a label: {label}")


async def _referring(world: World) -> tuple[dict[str, Any], str, str]:
    """A CI that refers to a site, two groups, a person, an asset and a person custom field."""
    a = world.a
    tag = uuid.uuid4().hex[:6]  # every call makes its own product and field
    product = await _product(world, a, "laptop", f"Polish laptop {tag}")
    asset = await add_asset(world, a, {"name": "Polish laptop 1", "product_id": product})
    assert asset.status_code == 201, asset.text
    person = await _field(world, a, f"Contact {tag}", None, "person")
    ci = await _made(
        world,
        a,
        "Referring server",
        site_id=str(a.s1),
        owner_group_id=str(a.ga),
        managed_by_group_id=str(a.gb),
        owner_user_id=str(a.tech_a),
        custom={person["key"]: str(a.tech_b)},
    )
    # Only a CI made from an asset carries one (the create API takes none): linked here directly,
    # on this test's own rows.
    await world.sql(
        "UPDATE cmdb_cis SET asset_id = $3 WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(ci["id"]),
        uuid.UUID(asset.json()["id"]),
    )
    return ci, asset.json()["id"], person["key"]


async def test_the_record_names_its_references_for_someone_who_may_see_them(world: World) -> None:
    a = world.a
    ci, asset_id, _key = await _referring(world)
    found = await world.call("GET", f"{BASE}/cis/{ci['id']}", a, a.admin)
    assert found.status_code == 200, found.text
    names = found.json()["names"]
    for ref in (a.s1, a.ga, a.gb, a.tech_a, a.tech_b, asset_id):
        name = names[str(ref)]
        assert name["restricted"] is False
        assert name["gone"] is False
        assert name["label"]
    assert "Polish laptop 1" in names[asset_id]["label"]
    _no_ids_as_labels(names)


async def test_a_reader_without_rights_gets_restricted_never_the_name(world: World) -> None:
    a = world.a
    ci, asset_id, _key = await _referring(world)
    # Views CIs, nothing else: no sites, groups or assets.
    await _given(world, a, a.requester2, "CMDB-only reader", [("cmdb.view", "all")])
    found = await world.call("GET", f"{BASE}/cis/{ci['id']}", a, a.requester2)
    assert found.status_code == 200, found.text
    names = found.json()["names"]
    for ref in (str(a.s1), str(a.ga), str(a.gb), asset_id):
        assert names[ref] == {"label": None, "restricted": True, "gone": False}
    # People are named as every history line names them.
    assert names[str(a.tech_a)]["label"]
    assert "Polish laptop 1" not in found.text
    _no_ids_as_labels(names)


async def test_compare_names_the_references_of_both_versions(world: World) -> None:
    a = world.a
    ci = await _made(world, a, "Moving server", site_id=str(a.s1))
    current = await world.call("GET", f"{BASE}/cis/{ci['id']}", a, a.admin)
    moved = await world.call(
        "PATCH",
        f"{BASE}/cis/{ci['id']}",
        a,
        a.admin,
        json={"site_id": str(a.s2)},
        headers=_match(current.json()["version"]),
    )
    assert moved.status_code == 200, moved.text
    compared = await world.call(
        "GET", f"{BASE}/cis/{ci['id']}/compare", a, a.admin, params={"from": 1, "to": 2}
    )
    assert compared.status_code == 200, compared.text
    body = compared.json()
    assert [c["field"] for c in body["attributes"]] == ["site_id"]
    for side in ("from_version", "to_version"):
        names = body[side]["names"]
        assert names[str(a.s1)]["label"]
        assert names[str(a.s2)]["label"]
        assert names[str(a.s1)]["label"] != names[str(a.s2)]["label"]
        _no_ids_as_labels(names)
    # The same answer for a reader without sites: restricted on both sides.
    await _given(world, a, a.requester2, "CMDB compare reader", [("cmdb.view", "all")])
    limited = await world.call(
        "GET", f"{BASE}/cis/{ci['id']}/compare", a, a.requester2, params={"from": 1, "to": 2}
    )
    assert limited.status_code == 200, limited.text
    for side in ("from_version", "to_version"):
        assert limited.json()[side]["names"][str(a.s2)]["restricted"] is True


async def test_a_business_view_carries_its_base_ci(world: World) -> None:
    a = world.a
    base = await _made(world, a, "View base service", "application")
    made = await _view(world, a, base, "Base CI view")
    assert made.status_code == 201, made.text
    expected = {"id": base["id"], "display_id": base["display_id"], "name": base["name"]}
    assert made.json()["base_ci"] == expected
    listed = await world.call(
        "GET", f"{BASE}/business-views", a, a.admin, params={"base_ci_id": base["id"]}
    )
    assert listed.status_code == 200, listed.text
    (item,) = listed.json()["items"]
    # A view is listed only while its base CI is visible, so the base is always there.
    assert item["base_ci"] == expected


async def test_a_deleted_asset_reads_restricted_never_gone(world: World) -> None:
    """Lane C: "gone" would confirm a deleted asset existed to a reader who might never have seen
    it, and a deleted asset can't be judged by rights any more, so it reads restricted."""
    a = world.a
    ci, asset_id, _key = await _referring(world)
    await world.sql(
        "UPDATE assets SET deleted_at = now() WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(asset_id),
    )
    found = await world.call("GET", f"{BASE}/cis/{ci['id']}", a, a.admin)
    assert found.status_code == 200, found.text
    assert found.json()["names"][asset_id] == {"label": None, "restricted": True, "gone": False}
    assert "Polish laptop 1" not in found.text


async def test_a_person_is_named_as_they_are_now(world: World) -> None:
    """Lane C: a person reads with today's name (an erased one anonymised), never an old one."""
    a = world.a
    ci, _asset_id, _key = await _referring(world)
    before = await world.sql(
        "SELECT display_name FROM users WHERE tenant_id = $1 AND id = $2", a.tenant, a.tech_a
    )
    old = before[0]["display_name"]
    try:
        await world.sql(
            "UPDATE users SET display_name = 'Former user' WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            a.tech_a,
        )
        found = await world.call("GET", f"{BASE}/cis/{ci['id']}", a, a.admin)
        assert found.status_code == 200, found.text
        assert found.json()["names"][str(a.tech_a)]["label"] == "Former user"
    finally:
        await world.sql(
            "UPDATE users SET display_name = $3 WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            a.tech_a,
            old,
        )


async def test_a_failing_group_lookup_leaves_groups_restricted(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lane C: another module's port failing fails closed: restricted, never the ID as text."""

    async def broken(*_args: object) -> dict[str, str]:
        raise RuntimeError

    monkeypatch.setattr(ref_names, "names_resolver", lambda _kind: broken)
    a = world.a
    ci, _asset_id, _key = await _referring(world)
    found = await world.call("GET", f"{BASE}/cis/{ci['id']}", a, a.admin)
    assert found.status_code == 200, found.text
    names = found.json()["names"]
    for group in (a.ga, a.gb):
        assert names[str(group)] == {"label": None, "restricted": True, "gone": False}
    _no_ids_as_labels(names)
