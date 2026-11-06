"""Who holds an asset and its holding history (WP-049a s4; REQ-AST-018, 019, 020; 0111).

The incident world: org A's admin holds everything; technicians hold assets.manage at group
scope. Org A has sites s1 and s2.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.assets.service.ownership import move_with_owner
from tests.db import test_incidents_api
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import World, field_codes, problem
from tests.db.test_knowledge_api import _match

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"


async def _asset(world: World, name: str) -> dict[str, Any]:
    a = world.a
    product = await _product(world, a, "laptop", f"Holder {name}")
    made = await _add(world, a, {"name": name, "product_id": product})
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _hold(world: World, asset: dict[str, Any], kind: str, holder: uuid.UUID | str) -> Any:  # noqa: ANN401 - httpx response
    a = world.a
    return await world.call(
        "PUT",
        f"{BASE}/{asset['id']}/holder",
        a,
        a.admin,
        json={"kind": kind, "id": str(holder)},
        headers=_match(asset["version"]),
    )


async def test_holdings_are_kept_from_person_to_person(world: World) -> None:
    """019 AC1/AC2: assigned to A, then B, then back: every holding with its dates."""
    a = world.a
    asset = await _asset(world, "Shared laptop")
    first = await _hold(world, asset, "user", a.tech_a)
    assert first.status_code == 200, first.text
    assert first.json()["owner_user_id"] == str(a.tech_a)
    second = await _hold(world, first.json(), "user", a.requester)
    assert second.json()["owner_user_id"] == str(a.requester)
    back = await world.call(
        "DELETE",
        f"{BASE}/{asset['id']}/holder",
        a,
        a.admin,
        headers=_match(second.json()["version"]),
    )
    assert back.status_code == 200, back.text
    assert back.json()["owner_user_id"] is None
    held = (await world.call("GET", f"{BASE}/{asset['id']}/holdings", a, a.admin)).json()
    assert [(h["holder_id"], h["ended_at"] is None) for h in held] == [
        (str(a.requester), False),
        (str(a.tech_a), False),
    ]
    # The person's page: what they held, and only now-held with `current`.
    past = await world.call(
        "GET", f"{BASE}/held-by", a, a.admin, params={"kind": "user", "id": str(a.tech_a)}
    )
    assert [h["asset"]["id"] for h in past.json()] == [asset["id"]]
    now = await world.call(
        "GET", f"{BASE}/held-by", a, a.admin,
        params={"kind": "user", "id": str(a.tech_a), "current": "true"},
    )  # fmt: skip
    assert now.json() == []
    audit = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1"
        " AND action IN ('asset.assigned', 'asset.unassigned') AND outcome = 'done'",
        a.tenant,
    )
    assert audit[0]["n"] == 3
    stale = await _hold(world, asset, "user", a.tech_b)  # the first version read, long gone
    assert problem(stale) == (409, "version_conflict")


async def test_an_asset_is_never_fitted_inside_itself(world: World) -> None:
    """018 AC1/AC3: a monitor on a workstation; never the workstation on its own monitor."""
    workstation = await _asset(world, "Workstation")
    monitor = await _asset(world, "Monitor")
    fitted = await _hold(world, monitor, "asset", workstation["id"])
    assert fitted.status_code == 200, fitted.text
    assert fitted.json()["parent_asset_id"] == workstation["id"]
    inside = await _hold(world, workstation, "asset", monitor["id"])
    assert field_codes(inside) == {"holder_id": "asset_nested_in_itself"}
    itself = await _hold(world, workstation, "asset", workstation["id"])
    assert field_codes(itself) == {"holder_id": "asset_nested_in_itself"}


async def test_holders_must_exist_in_this_organisation(world: World) -> None:
    a, b = world.a, world.b
    asset = await _asset(world, "Checked holder")
    assert field_codes(await _hold(world, asset, "user", uuid.uuid4())) == {
        "holder_id": "asset_holder_not_found"
    }
    # Another tenant's person is no one here.
    assert field_codes(await _hold(world, asset, "user", b.tech_a)) == {
        "holder_id": "asset_holder_not_found"
    }
    assert field_codes(await _hold(world, asset, "department", uuid.uuid4())) == {
        "holder_id": "asset_holder_not_found"
    }
    assert (await world.call("GET", f"{BASE}/{asset['id']}", a, a.admin)).json()["version"] == (
        asset["version"]
    )


async def test_assets_follow_their_owner_to_another_site(world: World) -> None:
    """018 AC2: with "follow owner's site" on, a person's move moves their assets, with history."""
    a = world.a
    settings = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    on = await world.call(
        "PATCH", f"{BASE}/settings", a, a.admin, json={"site_follows_owner": True},
        headers=_match(settings["version"]),
    )  # fmt: skip
    assert on.status_code == 200, on.text
    asset = await _asset(world, "Follows Rana")
    # The person's own site (their profile's), not the sites they have access to.
    await world.sql(
        "UPDATE users SET site_id = $1 WHERE tenant_id = $2 AND id = $3",
        a.s1,
        a.tenant,
        a.requester,
    )
    held = await _hold(world, asset, "user", a.requester)
    assert held.json()["site_id"] == str(a.s1)  # the person's own site, taken on assignment
    await world.sql(
        "UPDATE users SET site_id = $1 WHERE tenant_id = $2 AND id = $3",
        a.s2,
        a.tenant,
        a.requester,
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await move_with_owner(session, a.requester) == 1
        assert await move_with_owner(session, a.requester) == 0  # a second delivery: nothing left
    now = (await world.call("GET", f"{BASE}/{asset['id']}", a, a.admin)).json()
    assert now["site_id"] == str(a.s2)
    history = (await world.call("GET", f"{BASE}/{asset['id']}/history", a, a.admin)).json()
    latest = history["items"][0]
    assert [c["field"] for c in latest["changes"]] == ["site_id"]


async def test_holdings_and_relationships_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    asset = await _asset(world, "Only A holds")
    assert (await _hold(world, asset, "user", a.tech_a)).status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in ("asset_assignments", "asset_relationships"):
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608 - fixed names
        assert (
            await session.execute(text("UPDATE asset_assignments SET source = 'x'"))
        ).rowcount == 0
    assert problem(await world.call("GET", f"{BASE}/{asset['id']}/holdings", b, b.admin)) == (
        404,
        "asset_not_found",
    )


async def test_a_link_shows_from_both_ends_and_in_both_histories(world: World) -> None:
    """027 AC1: a workstation "connected to" a switch, on both pages and in both histories."""
    a = world.a
    workstation = await _asset(world, "Desk PC")
    switch = await _asset(world, "Floor switch")
    made = await world.call(
        "POST", f"{BASE}/{workstation['id']}/links", a, a.admin,
        json={"to_asset_id": switch["id"], "kind": "connected_to"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip
    assert made.status_code == 201, made.text
    link = made.json()
    assert (link["outgoing"], link["other"]["id"]) == (True, switch["id"])
    seen = (await world.call("GET", f"{BASE}/{switch['id']}/links", a, a.tech_a)).json()
    assert [(x["kind"], x["outgoing"], x["other"]["id"]) for x in seen] == [
        ("connected_to", False, workstation["id"])
    ]
    for asset, far in ((workstation, switch), (switch, workstation)):
        history = (await world.call("GET", f"{BASE}/{asset['id']}/history", a, a.admin)).json()
        assert history["items"][0]["changes"][0]["new"] == f"connected_to:{far['id']}"
    again = await world.call(
        "POST", f"{BASE}/{workstation['id']}/links", a, a.admin,
        json={"to_asset_id": switch["id"], "kind": "connected_to"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip
    assert problem(again) == (409, "asset_link_exists")
    itself = await world.call(
        "POST", f"{BASE}/{switch['id']}/links", a, a.admin,
        json={"to_asset_id": switch["id"], "kind": "depends_on"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip
    assert field_codes(itself) == {"to_asset_id": "asset_link_to_itself"}
    # Only under one of its own assets.
    stranger = await _asset(world, "Unrelated")
    wrong = await world.call("DELETE", f"{BASE}/{stranger['id']}/links/{link['id']}", a, a.admin)
    assert problem(wrong) == (404, "asset_link_not_found")
    gone = await world.call("DELETE", f"{BASE}/{switch['id']}/links/{link['id']}", a, a.admin)
    assert gone.status_code == 204
    assert (await world.call("GET", f"{BASE}/{workstation['id']}/links", a, a.admin)).json() == []


async def test_a_person_acknowledges_an_asset_given_to_them(world: World) -> None:
    """023 AC1-AC3: pending when given, the person accepts or disputes; a dispute keeps history."""
    a = world.a
    laptop = await _asset(world, "Acknowledged laptop")
    # The catalogue is seeded on first use: the type exists only now.
    await world.sql(
        "UPDATE asset_product_types SET ack_required = true WHERE tenant_id = $1"
        " AND api_name = 'laptop'",
        a.tenant,
    )
    given = await _hold(world, laptop, "user", a.requester)
    assert given.status_code == 200, given.text
    mine = await world.call("GET", f"{BASE}/mine", a, a.requester)
    assert mine.status_code == 200, mine.text
    row = next(m for m in mine.json() if m["id"] == laptop["id"])
    ack = row["acknowledgement"]
    assert ack["status"] == "pending"
    assert row["through_department"] is False
    # Only the holder answers, and a dispute says what is wrong.
    by_other = await world.call(
        "POST", f"{BASE}/acknowledgements/{ack['id']}/answer", a, a.tech_a, json={"accept": True}
    )
    assert problem(by_other) == (404, "asset_acknowledgement_not_found")
    silent = await world.call(
        "POST", f"{BASE}/acknowledgements/{ack['id']}/answer", a, a.requester,
        json={"accept": False},
    )  # fmt: skip
    assert field_codes(silent) == {"comment": "required"}
    disputed = await world.call(
        "POST", f"{BASE}/acknowledgements/{ack['id']}/answer", a, a.requester,
        json={"accept": False, "comment": "The screen is cracked"},
    )  # fmt: skip
    assert disputed.status_code == 200, disputed.text
    assert (disputed.json()["status"], disputed.json()["channel"]) == ("disputed", "portal")
    again = await world.call(
        "POST", f"{BASE}/acknowledgements/{ack['id']}/answer", a, a.requester,
        json={"accept": True},
    )  # fmt: skip
    assert problem(again) == (409, "asset_acknowledgement_answered")
    # AC3 / condition 3: the holding and its history stay as they were.
    held = (await world.call("GET", f"{BASE}/{laptop['id']}/holdings", a, a.admin)).json()
    assert [(h["holder_id"], h["ended_at"]) for h in held] == [(str(a.requester), None)]
    events = await world.sql(
        "SELECT envelope->>'event_type' AS kind, envelope->'payload'->>'status' AS status"
        " FROM outbox_events WHERE tenant_id = $1 AND envelope->>'event_type' IN"
        " ('assets.acknowledgement.changed', 'assets.holder.changed') ORDER BY id",
        a.tenant,
    )
    kinds = [(e["kind"], e["status"]) for e in events]
    assert ("assets.acknowledgement.changed", "pending") in kinds
    assert ("assets.acknowledgement.changed", "disputed") in kinds
    assert any(k == "assets.holder.changed" for k, _ in kinds)


async def test_my_assets_shows_only_mine_and_needs_no_asset_permission(world: World) -> None:
    """024 AC1: a requester sees what they hold, nothing else, with no asset permission."""
    a = world.a
    theirs = await _asset(world, "Rana's phone")
    other = await _asset(world, "Someone else's")
    assert (await _hold(world, theirs, "user", a.requester)).status_code == 200
    assert (await _hold(world, other, "user", a.tech_a)).status_code == 200
    mine = (await world.call("GET", f"{BASE}/mine", a, a.requester)).json()
    ids = {m["id"] for m in mine}
    assert theirs["id"] in ids
    assert other["id"] not in ids
    # Still no way into the staff list.
    assert problem(await world.call("GET", BASE, a, a.requester))[0] == 403


async def test_acknowledgements_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    laptop = await _asset(world, "RLS laptop")
    # The catalogue is seeded on first use: the type exists only now.
    await world.sql(
        "UPDATE asset_product_types SET ack_required = true WHERE tenant_id = $1"
        " AND api_name = 'laptop'",
        a.tenant,
    )
    assert (await _hold(world, laptop, "user", a.requester)).status_code == 200
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM asset_acknowledgements")) == 0
        assert (
            await session.execute(text("UPDATE asset_acknowledgements SET comment = 'x'"))
        ).rowcount == 0


async def test_the_picker_offers_a_persons_own_assets_first(world: World) -> None:
    """025: a requester sees what they hold; staff may also search; others' are never offered."""
    a = world.a
    theirs = await _asset(world, "Picker laptop")
    await _asset(world, "Picker printer")  # nobody's
    assert (await _hold(world, theirs, "user", a.requester)).status_code == 200
    own = (await world.call("GET", f"{BASE}/picker", a, a.requester)).json()
    assert [(r["id"], r["mine"]) for r in own] == [(theirs["id"], True)]
    # A requester may not search the organisation's assets or pick for someone else.
    searched = (
        await world.call("GET", f"{BASE}/picker", a, a.requester, params={"q": "printer"})
    ).json()
    assert {r["id"] for r in searched} == {theirs["id"]}
    other = await world.call(
        "GET", f"{BASE}/picker", a, a.requester, params={"for_user": str(a.tech_a)}
    )
    assert other.json() == []
    by_staff = (
        await world.call(
            "GET", f"{BASE}/picker", a, a.admin,
            params={"for_user": str(a.requester), "q": "printer"},
        )
    ).json()  # fmt: skip
    assert by_staff[0]["id"] == theirs["id"]
    assert any(r["name"] == "Picker printer" and not r["mine"] for r in by_staff)


async def test_refs_mark_gone_and_hidden_assets_never_naming_them(world: World) -> None:
    from app.modules.assets import asset_refs, assets_of, can_see  # noqa: PLC0415 - the public interface under test
    from app.modules.identity_access import subject_for  # noqa: PLC0415 - as other modules call it

    a = world.a
    theirs = await _asset(world, "Ref mine")
    hidden = await _asset(world, "Ref hidden")
    trashed = await _asset(world, "Ref trashed")
    assert (await _hold(world, theirs, "user", a.requester)).status_code == 200
    gone = await world.call(
        "DELETE", f"{BASE}/{trashed['id']}", a, a.admin, headers=_match(trashed["version"])
    )
    assert gone.status_code == 204, gone.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        requester = await subject_for(session, a.tenant, a.requester)
        ids = [uuid.UUID(theirs["id"]), uuid.UUID(hidden["id"]), uuid.UUID(trashed["id"])]
        refs = await asset_refs(session, requester, ids)
        assert refs[ids[0]].name == "Ref mine"
        assert (refs[ids[1]].hidden, refs[ids[1]].name) == (True, None)
        assert (refs[ids[2]].gone, refs[ids[2]].name) == (True, None)
        assert await can_see(session, requester, ids[0])
        assert not await can_see(session, requester, ids[1])
        assert [r.id for r in await assets_of(session, a.requester)] == [ids[0]]
