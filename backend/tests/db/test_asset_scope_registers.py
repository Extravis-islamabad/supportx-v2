"""A site-scoped asset viewer sees only their sites' records in the asset registers (#423 scope).

The loan register, bookings, consumable stock and its ledger, asset groups and audits name assets
or stock by site. A person whose `assets.view` is limited to their sites must see only what they
may see, never another site's: each read goes through the assets scope, never a site argument.
Each test has its controls: the admin sees both records, the viewer sees their own site's.
Real PostgreSQL and Valkey on the incident world; every record is new (rule 5h).
"""

import uuid
from typing import Any

import pytest

from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_asset_audits_api import _plan, _start
from tests.db.test_asset_bookings_api import _book, _day
from tests.db.test_asset_groups_api import GROUPS, _group
from tests.db.test_asset_loans_api import _loan, _loanable
from tests.db.test_asset_stock_api import _allocate, _consumable, _detail, _receive, _stock
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


async def _viewer(world: World, tag: str, *, manage: bool = False) -> uuid.UUID:
    """requester: a member of site S1 only (the incident world); asset rights at site scope."""
    a = world.a
    grants = [("assets.view", "site")] + ([("assets.manage", "site")] if manage else [])
    await _given(
        world, a, a.requester, f"Site asset {'manager' if manage else 'viewer'} {tag}", grants
    )
    return a.requester


async def test_a_mixed_loan_names_only_the_visible_assets_and_counts_the_rest(
    world: World,
) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    near = await _asset_at(world, f"Mixed near {tag}", a.s1)
    far = await _asset_at(world, f"Mixed far {tag}", a.s2)
    await _loanable(world, near, far)
    lent = await _loan(world, [near, far], a.tech_a)
    assert lent.status_code == 201, lent.text
    viewer = await _viewer(world, tag)
    seen = await world.call("GET", "/assets/loans", a, viewer)
    assert seen.status_code == 200, seen.text
    (loan,) = [x for x in seen.json() if x["id"] == lent.json()["id"]]
    assert [x["name"] for x in loan["assets"]] == [f"Mixed near {tag}"]
    assert loan["hidden_items"] == 1
    assert far["id"] not in seen.text
    assert far["id"] not in loan["outstanding"]
    everyone = await world.call("GET", "/assets/loans", a, a.admin)
    (whole,) = [x for x in everyone.json() if x["id"] == lent.json()["id"]]
    assert whole["hidden_items"] == 0
    assert len(whole["assets"]) == 2


async def test_returns_on_a_loan_with_no_visible_asset_answer_not_found(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    far = await _asset_at(world, f"Return far {tag}", a.s2)
    await _loanable(world, far)
    lent = await _loan(world, [far], a.tech_a)
    assert lent.status_code == 201, lent.text
    manager = await _viewer(world, tag, manage=True)
    body = {"asset_ids": [far["id"]], "outcome": "in_stock"}
    answer = await world.call(
        "POST", f"/assets/loans/{lent.json()['id']}/returns", a, manager, json=body
    )
    assert answer.status_code == 404, answer.text
    assert f"Return far {tag}" not in answer.text


async def test_bookings_show_only_the_viewers_sites(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    near = await _asset_at(world, f"Book near {tag}", a.s1)
    far = await _asset_at(world, f"Book far {tag}", a.s2)
    await _loanable(world, near, far)
    for asset in (near, far):
        booked = await _book(world, asset, _day(30), _day(31))
        assert booked.status_code == 201, booked.text
    everyone = await world.call(
        "GET", "/assets/bookings", a, a.admin, params={"site_id": str(a.s2)}
    )
    assert everyone.status_code == 200, everyone.text
    assert far["id"] in everyone.text  # the control: the admin sees the far booking
    viewer = await _viewer(world, tag)
    for params in ({"site_id": str(a.s2)}, {"asset_id": far["id"]}, {"site_id": str(a.s1)}):
        seen = await world.call("GET", "/assets/bookings", a, viewer, params=params)
        assert seen.status_code == 200, seen.text
        assert far["id"] not in seen.text, params
    own = await world.call("GET", "/assets/bookings", a, viewer, params={"site_id": str(a.s1)})
    assert near["id"] in own.text  # the control: their own site's booking is there


async def test_consumable_stock_and_its_ledger_show_only_the_viewers_sites(
    world: World,
) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    item = await _consumable(world, f"Scoped toner {tag}")
    for site in (a.s1, a.s2):
        received = await _receive(world, item, "5", site)
        assert received.status_code in (200, 201), received.text
    whole = await _detail(world, item)
    near_stock, far_stock = _stock(whole, a.s1)["id"], _stock(whole, a.s2)["id"]
    ledger_all = await world.call("GET", f"/assets/consumables/{item['id']}/ledger", a, a.admin)
    assert far_stock in ledger_all.text  # the control: the admin sees both sites' movements
    viewer = await _viewer(world, tag)
    detail = await world.call("GET", f"/assets/consumables/{item['id']}", a, viewer)
    assert detail.status_code == 200, detail.text
    assert str(a.s2) not in detail.text
    assert near_stock in detail.text
    listed = await world.call("GET", "/assets/consumables", a, viewer, params={"search": tag})
    assert listed.status_code == 200, listed.text
    assert str(a.s2) not in listed.text
    assert near_stock in listed.text
    by_site = await world.call(
        "GET", "/assets/consumables", a, viewer, params={"site_id": str(a.s2)}
    )
    assert item["id"] not in by_site.text  # no visible stock there: not listed by that site
    ledger = await world.call("GET", f"/assets/consumables/{item['id']}/ledger", a, viewer)
    assert ledger.status_code == 200, ledger.text
    assert far_stock not in ledger.text
    assert near_stock in ledger.text


async def test_an_asset_group_lists_only_the_viewers_sites(world: World) -> None:
    """Regression: members go through the assets scope (lane C checked main)."""
    a = world.a
    tag = uuid.uuid4().hex[:6]
    near = await _asset_at(world, f"Group near {tag}", a.s1)
    far = await _asset_at(world, f"Group far {tag}", a.s2)
    group = (await _group(world, {"name": f"Scope group {tag}", "kind": "static"})).json()
    added = await world.call(
        "POST", f"{GROUPS}/{group['id']}/members", a, a.admin,
        json={"asset_ids": [near["id"], far["id"]]},
    )  # fmt: skip
    assert added.status_code == 200, added.text
    everyone = await world.call("GET", f"{GROUPS}/{group['id']}/assets", a, a.admin)
    assert far["id"] in everyone.text  # the control
    viewer = await _viewer(world, tag)
    seen = await world.call("GET", f"{GROUPS}/{group['id']}/assets", a, viewer)
    assert seen.status_code == 200, seen.text
    assert near["id"] in seen.text  # the control
    assert far["id"] not in seen.text
    assert f"Group far {tag}" not in seen.text


async def test_an_audit_names_only_the_site_scoped_managers_assets(world: World) -> None:
    """A probe: a manager whose asset rights are site-scoped, reading an audit of two sites."""
    a = world.a
    tag = uuid.uuid4().hex[:6]
    near = await _asset_at(world, f"Audit near {tag}", a.s1)
    far = await _asset_at(world, f"Audit far {tag}", a.s2)
    audit = await _start(
        world, a, await _plan(world, a, site_ids=[str(a.s1), str(a.s2)], name=f"Two sites {tag}")
    )
    everyone = await world.call("GET", f"/assets/audits/{audit['id']}/items", a, a.admin)
    assert far["id"] in everyone.text or f"Audit far {tag}" in everyone.text  # the control
    manager = await _viewer(world, tag, manage=True)
    seen = await world.call("GET", f"/assets/audits/{audit['id']}/items", a, manager)
    if seen.status_code == 200:
        assert f"Audit near {tag}" in seen.text or near["id"] in seen.text  # the control
        assert f"Audit far {tag}" not in seen.text
        assert far["id"] not in seen.text
    else:
        assert seen.status_code in (403, 404), seen.text


async def test_an_auditor_of_a_mixed_audit_sees_and_counts_only_their_sites(
    world: World,
) -> None:
    """Lane C: items and progress follow the assets scope, an auditor's too."""
    a = world.a
    tag = uuid.uuid4().hex[:6]
    near = await _asset_at(world, f"Counted near {tag}", a.s1)
    far = await _asset_at(world, f"Counted far {tag}", a.s2)
    # requester (a member of S1; the built-in requester role holds no asset right) audits a
    # two-site audit with asset rights at site scope only. tech_a's built-in technician role
    # sees every asset, so it can't stand for a site-scoped auditor.
    auditor = a.requester
    await _given(
        world,
        a,
        auditor,
        f"Site auditor {tag}",
        [("assets.view", "site"), ("assets.manage", "site")],
    )
    audit = await _start(
        world,
        a,
        await _plan(
            world,
            a,
            site_ids=[str(a.s1), str(a.s2)],
            name=f"Mixed {tag}",
            auditor_ids=[str(auditor)],
        ),
    )
    url = f"/assets/audits/{audit['id']}"
    everyone = (await world.call("GET", f"{url}/items", a, a.admin)).json()
    theirs = await world.call("GET", f"{url}/items", a, auditor)
    assert theirs.status_code == 200, theirs.text
    assert near["id"] in theirs.text  # the control: their own site's item is listed
    assert far["id"] not in theirs.text
    assert f"Counted far {tag}" not in theirs.text
    expected = [i for i in theirs.json() if i["kind"] == "expected"]
    whole = [i for i in everyone if i["kind"] == "expected"]
    assert len(expected) < len(whole)
    # The counts match the list each person sees.
    mine = (await world.call("GET", url, a, auditor)).json()["progress"]
    admins = (await world.call("GET", url, a, a.admin)).json()["progress"]
    assert mine["expected"] == len(expected)
    assert admins["expected"] == len(whole)


async def test_allocations_name_only_work_items_the_reader_may_see(world: World) -> None:
    """A ledger line from a hidden record carries no ID; asking by a hidden record is 404."""
    a = world.a
    tag = uuid.uuid4().hex[:6]
    item = await _consumable(world, f"Request toner {tag}")
    received = await _receive(world, item, "9", a.s1)
    assert received.status_code in (200, 201), received.text
    stock = _stock(await _detail(world, item), a.s1)["id"]
    # tech_a: a technician in group GA (not GB), asset rights at site scope (S1).
    seen = await world.create(a, a.admin, group_id=str(a.ga), subject=f"Seen request {tag}")
    hidden = await world.create(a, a.admin, group_id=str(a.gb), subject=f"Hidden request {tag}")
    for record in (seen, hidden):
        given = await _allocate(world, item, stock, "1", work_item_id=record["id"])
        assert given.status_code in (200, 201), given.text
    await _given(world, a, a.tech_a, f"Stock viewer {tag}", [("assets.view", "site")])
    ledger = await world.call("GET", f"/assets/consumables/{item['id']}/ledger", a, a.tech_a)
    assert ledger.status_code == 200, ledger.text
    lines = [x for x in ledger.json() if x["kind"] == "allocate"]
    assert {(x["work_item_id"], x["work_item_hidden"]) for x in lines} == {
        (seen["id"], False),
        (None, True),
    }
    assert hidden["id"] not in ledger.text
    # The control: the admin sees both records.
    admin_ledger = await world.call("GET", f"/assets/consumables/{item['id']}/ledger", a, a.admin)
    assert hidden["id"] in admin_ledger.text
    by_seen = await world.call(
        "GET", "/assets/consumable-allocations", a, a.tech_a, params={"work_item_id": seen["id"]}
    )
    assert by_seen.status_code == 200, by_seen.text
    by_hidden = await world.call(
        "GET", "/assets/consumable-allocations", a, a.tech_a, params={"work_item_id": hidden["id"]}
    )
    by_unknown = await world.call(
        "GET",
        "/assets/consumable-allocations",
        a,
        a.tech_a,
        params={"work_item_id": str(uuid.uuid4())},
    )
    assert by_hidden.status_code == by_unknown.status_code == 404

    def _same(response: Any) -> dict[str, Any]:  # noqa: ANN401 - httpx response
        return {k: v for k, v in response.json().items() if k not in ("instance", "request_id")}

    assert _same(by_hidden) == _same(by_unknown)  # no existence oracle


async def test_the_shared_pool_names_only_the_product_the_site_and_busy_times(
    world: World,
) -> None:
    """The coordinator, 2026-11-20: a shared pool by design, so nothing names the asset."""
    a = world.a
    tag = uuid.uuid4().hex[:6]
    asset = await _asset_at(world, f"Pool laptop {tag}", a.s2)
    await _loanable(world, asset)
    pool = await world.call(
        "GET", "/assets/availability", a, a.admin, params={"product_id": asset["product_id"]}
    )
    assert pool.status_code == 200, pool.text
    slots = pool.json()
    assert slots
    assert {frozenset(s) for s in slots} == {
        frozenset({"product_id", "product_name", "site_name", "busy"})
    }
    # The product's name is allowed (and here contains the asset's); the asset is never named.
    assert asset["id"] not in pool.text
    if asset.get("tag"):
        assert asset["tag"] not in pool.text
