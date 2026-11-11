"""Asset audits over HTTP (WP-049b s3; 0134). REQ-AST-042 (plan), 043 (run and settle).

The incident world: org A's admin holds everything (assets.manage); technicians only view
assets (D-153); tech A and tech B audit, tech C does not; requesters hold no asset permission;
org B is there for isolation.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.assets.service.realtime import AUDIT_CHANGED, AUDIT_KIND, CHANNELS, ROUTES
from app.modules.identity_access import subject_for
from app.shared.events import EventEnvelope
from app.shared.realtime import ChannelRequest, record
from tests.db import test_incidents_api
from tests.db.test_asset_financials_api import _events
from tests.db.test_asset_moves_api import _states
from tests.db.test_assets_api import _add, _product
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _match, _new

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets/audits"
NEW_TABLES = ("asset_audits", "asset_audit_auditors", "asset_audit_items")


async def _asset(world: World, org: Org, name: str, **values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    product = values.pop("product_id", None) or await _product(world, org, "laptop", f"P {name}")
    made = await _add(world, org, {"name": name, "product_id": product, **values})
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _plan(world: World, org: Org, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    sent = {"name": "Q4 count", "kind": "technician", "auditor_ids": [str(org.tech_a)], **body}
    made = await world.call("POST", BASE, org, org.admin, json=sent, headers=_new())
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _start(world: World, org: Org, audit: dict[str, Any]) -> dict[str, Any]:
    started = await world.call(
        "POST", f"{BASE}/{audit['id']}/start", org, org.admin, headers=_match(audit["version"])
    )
    assert started.status_code == 200, started.text
    return dict(started.json())


async def _items(
    world: World, org: Org, audit: dict[str, Any], user: uuid.UUID | None = None, **params: str
) -> list[dict[str, Any]]:
    found = await world.call(
        "GET", f"{BASE}/{audit['id']}/items", org, user or org.admin, params=params
    )
    assert found.status_code == 200, found.text
    return list(found.json())


async def _scan(
    world: World, org: Org, audit: dict[str, Any], code: str, user: uuid.UUID, site: uuid.UUID
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "POST", f"{BASE}/{audit['id']}/scans", org, user,
        json={"code": code, "seen_site_id": str(site)}, headers=_new(),
    )  # fmt: skip


async def test_042_ac1_an_audit_of_site_a_expects_exactly_the_assets_at_site_a(
    world: World,
) -> None:
    a = world.a
    at_a = [await _asset(world, a, f"A{n}", site_id=str(a.s1)) for n in range(2)]
    await _asset(world, a, "B1", site_id=str(a.s2))
    await _asset(world, a, "Nowhere")
    audit = await _plan(world, a, site_ids=[str(a.s1)])
    assert (audit["state"], audit["display_id"].startswith("AUD-")) == ("draft", True)
    assert await _items(world, a, audit) == []  # nothing frozen while it is a draft
    running = await _start(world, a, audit)
    assert running["state"] == "running"
    items = await _items(world, a, audit)
    assert sorted(i["asset_id"] for i in items) == sorted(x["id"] for x in at_a)
    assert {i["kind"] for i in items} == {"expected"}
    assert {i["expected_site_id"] for i in items} == {str(a.s1)}
    assert running["progress"] == {
        "expected": 2, "marked": 0, "found": 0, "unexpected": 0, "discrepancies": 0,
    }  # fmt: skip
    # The scope is frozen once it runs; the name may still change.
    frozen = await world.call(
        "PATCH", f"{BASE}/{audit['id']}", a, a.admin,
        json={"site_ids": [str(a.s2)]}, headers=_match(running["version"]),
    )  # fmt: skip
    assert problem(frozen) == (409, "asset_audit_scope_frozen")
    stale = await world.call(
        "PATCH", f"{BASE}/{audit['id']}", a, a.admin,
        json={"name": "Renamed"}, headers=_match(running["version"] - 1),
    )  # fmt: skip
    assert problem(stale) == (409, "version_conflict")
    renamed = await world.call(
        "PATCH", f"{BASE}/{audit['id']}", a, a.admin,
        json={"name": "Renamed"}, headers=_match(running["version"]),
    )  # fmt: skip
    assert renamed.status_code == 200, renamed.text


async def test_043_ac1_an_asset_scanned_at_site_b_is_in_the_wrong_place(world: World) -> None:
    a = world.a
    here = await _asset(world, a, "Here", site_id=str(a.s1))
    moved = await _asset(world, a, "Moved", site_id=str(a.s1))
    stray = await _asset(world, a, "Stray", site_id=str(a.s2))
    audit = await _start(world, a, await _plan(world, a, site_ids=[str(a.s1)]))
    found = await _scan(world, a, audit, here["tag"], a.tech_a, a.s1)
    assert found.status_code == 201, found.text
    assert (found.json()["result"], found.json()["method"]) == ("found", "scanned")
    wrong = await _scan(world, a, audit, f"https://desk/assets/{moved['id']}", a.tech_a, a.s2)
    assert wrong.json()["result"] == "wrong_place"
    # An asset not expected here is added as unexpected (its recorded site differs: wrong place).
    extra = await _scan(world, a, audit, stray["serial_number"] or stray["tag"], a.tech_a, a.s1)
    assert (extra.json()["kind"], extra.json()["result"]) == ("unexpected", "wrong_place")
    view = (await world.call("GET", f"{BASE}/{audit['id']}", a, a.tech_a)).json()
    assert view["progress"] == {
        "expected": 2, "marked": 2, "found": 1, "unexpected": 1, "discrepancies": 2,
    }  # fmt: skip
    gaps = await _items(world, a, audit, discrepancies="true")
    assert sorted(i["name"] for i in gaps) == ["Moved", "Stray"]
    # By hand, with the version read; missing stays missing.
    item = next(i for i in await _items(world, a, audit) if i["name"] == "Here")
    marked = await world.call(
        "PATCH", f"{BASE}/{audit['id']}/items/{item['id']}", a, a.tech_a,
        json={"result": "damaged", "note": "Cracked lid"}, headers=_match(item["version"]),
    )  # fmt: skip
    assert marked.status_code == 200, marked.text
    assert (marked.json()["result"], marked.json()["note"]) == ("damaged", "Cracked lid")
    events = await _events(world, a, "assets.audit.item_changed")
    assert {e["payload"]["action"] for e in events} >= {"marked", "added"}
    assert all(set(e["payload"]) <= {"audit_id", "item_id", "asset_id", "action"} for e in events)


async def test_043_ac2_moving_to_site_b_updates_the_asset_and_its_history_names_the_audit(
    world: World,
) -> None:
    a = world.a
    moved = await _asset(world, a, "Wanderer", site_id=str(a.s1))
    audit = await _start(world, a, await _plan(world, a, site_ids=[str(a.s1)], name="North"))
    assert (await _scan(world, a, audit, moved["tag"], a.tech_a, a.s2)).status_code == 201
    (gap,) = await _items(world, a, audit, discrepancies="true")
    body = {"fix": "move_site", "item_ids": [gap["id"]], "site_id": str(a.s2)}
    # Fixes need assets.manage: an auditor who only views cannot apply them.
    refused = await world.call(
        "POST", f"{BASE}/{audit['id']}/fixes", a, a.tech_a, json=body, headers=_new()
    )
    assert problem(refused)[0] == 403
    fixed = await world.call(
        "POST", f"{BASE}/{audit['id']}/fixes", a, a.admin, json=body, headers=_new()
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["applied"] == 1
    asset = (await world.call("GET", f"/assets/{moved['id']}", a, a.admin)).json()
    assert asset["site_id"] == str(a.s2)
    history = (await world.call("GET", f"/assets/{moved['id']}/history", a, a.admin)).json()
    latest = history["items"][0]
    assert [c["field"] for c in latest["changes"]] == ["site_id"]
    assert latest["origin"] == {
        "kind": "asset_audit", "audit_id": audit["id"], "display_id": audit["display_id"],
        "name": "North",
    }  # fmt: skip
    (item,) = await _items(world, a, audit)
    assert item["fix"] == "move_site"
    # A state change that the life cycle refuses is reported per item, the rest go ahead.
    states = await _states(world, a)
    bad = await world.call(
        "POST", f"{BASE}/{audit['id']}/fixes", a, a.admin, headers=_new(),
        json={"fix": "change_state", "item_ids": [item["id"]], "state_id": states["disposed"]},
    )  # fmt: skip
    assert bad.json()["outcomes"] == [
        {"item_id": item["id"], "applied": False, "code": "asset_move_not_allowed"}
    ]


async def test_043_ac3_progress_goes_live_to_every_auditor_on_the_audits_channel(
    world: World,
) -> None:
    a = world.a
    asset = await _asset(world, a, "Live", site_id=str(a.s1))
    audit = await _plan(world, a, site_ids=[str(a.s1)], auditor_ids=[str(a.tech_a), str(a.tech_b)])
    audit = await _start(world, a, audit)
    await _scan(world, a, audit, asset["tag"], a.tech_b, a.s1)
    (event,) = await _events(world, a, "assets.audit.item_changed")
    route = next(r for r in ROUTES if "assets.audit.item_changed" in r.event_types)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(EventEnvelope.model_validate(event), session)
        channel = record(a.tenant, AUDIT_KIND, uuid.UUID(audit["id"]))
        published = next(p for p in effects.publications if p.channel == channel)
        assert (published.type, set(published.fields)) == (AUDIT_CHANGED, {"items", "progress"})
        assert set(published.data()) <= {"type", "ids", "fields", "version", "by"}
        spec = next(c for c in CHANNELS if c.kind == AUDIT_KIND)
        for user, allowed in ((a.tech_a, True), (a.tech_b, True), (a.tech_c, False)):
            request = ChannelRequest(
                channel=channel, tenant_id=a.tenant, user_id=user,
                subject=await subject_for(session, a.tenant, user), session=session,
            )  # fmt: skip
            assert (await spec.authorize(request) is not None) is allowed


async def test_refusals_a_non_auditor_another_tenant_and_a_closed_audit(world: World) -> None:
    a, b = world.a, world.b
    asset = await _asset(world, a, "Guarded", site_id=str(a.s1))
    audit = await _start(world, a, await _plan(world, a, site_ids=[str(a.s1)]))
    (item,) = await _items(world, a, audit)
    mark = {"result": "found"}
    # A technician who is not a named auditor: refused, with its labelled code.
    not_auditor = await world.call(
        "PATCH", f"{BASE}/{audit['id']}/items/{item['id']}", a, a.tech_c,
        json=mark, headers=_match(item["version"]),
    )  # fmt: skip
    assert problem(not_auditor) == (404, "asset_audit_not_found")  # not even shown to them
    assert (await world.call("GET", f"{BASE}/{audit['id']}", a, a.tech_c)).status_code == 404
    # A manager may open it but is no auditor: marking still needs to be named.
    manager_mark = await world.call(
        "PATCH", f"{BASE}/{audit['id']}/items/{item['id']}", a, a.admin,
        json=mark, headers=_match(item["version"]),
    )  # fmt: skip
    assert problem(manager_mark) == (403, "asset_audit_not_auditor")
    # Another tenant: nothing to see, nothing to mark.
    for user in (b.admin, b.tech_a):
        assert problem(await world.call("GET", f"{BASE}/{audit['id']}", b, user)) == (
            404,
            "asset_audit_not_found",
        )
    other = await world.call(
        "PATCH", f"{BASE}/{audit['id']}/items/{item['id']}", b, b.admin,
        json=mark, headers=_match(item["version"]),
    )  # fmt: skip
    assert problem(other) == (404, "asset_audit_not_found")
    # Closed: read-only, on the server.
    closed = await world.call(
        "POST", f"{BASE}/{audit['id']}/close", a, a.admin, headers=_match(audit["version"])
    )
    assert closed.status_code == 200, closed.text
    late = await world.call(
        "PATCH", f"{BASE}/{audit['id']}/items/{item['id']}", a, a.tech_a,
        json=mark, headers=_match(item["version"]),
    )  # fmt: skip
    assert problem(late) == (409, "asset_audit_closed")
    assert problem(await _scan(world, a, audit, asset["tag"], a.tech_a, a.s1)) == (
        409,
        "asset_audit_closed",
    )
    for call in (
        ("PATCH", f"{BASE}/{audit['id']}", {"name": "Again"}),
        ("POST", f"{BASE}/{audit['id']}/close", None),
    ):
        refused = await world.call(
            call[0], call[1], a, a.admin, json=call[2], headers=_match(closed.json()["version"])
        )
        assert problem(refused) == (409, "asset_audit_closed")
    fixes = await world.call(
        "POST", f"{BASE}/{audit['id']}/fixes", a, a.admin, headers=_new(),
        json={"fix": "move_site", "item_ids": [item["id"]], "site_id": str(a.s2)},
    )  # fmt: skip
    assert problem(fixes) == (409, "asset_audit_closed")
    # Unmarked expected items are discrepancies once closed.
    assert closed.json()["progress"]["discrepancies"] == 1


async def test_planning_needs_assets_manage_and_known_scope(world: World) -> None:
    a = world.a
    body = {"name": "Mine", "kind": "technician", "auditor_ids": [str(a.tech_a)]}
    assert problem(await world.call("POST", BASE, a, a.tech_a, json=body, headers=_new()))[0] == 403
    assert (
        problem(await world.call("POST", BASE, a, a.requester, json=body, headers=_new()))[0] == 403
    )
    bad = await world.call(
        "POST", BASE, a, a.admin, headers=_new(),
        json={**body, "site_ids": [str(uuid.uuid4())], "auditor_ids": [str(uuid.uuid4())],
              "planned_start": "2026-12-02", "planned_end": "2026-12-01"},
    )  # fmt: skip
    assert field_codes(bad) == {
        "site_ids": "site_not_found",
        "auditor_ids": "user_not_found",
        "planned_end": "end_before_start",
    }
    # Others with assets.view see only the audits they audit.
    await _plan(world, a, name="Theirs", auditor_ids=[str(a.tech_b)])
    mine = await _plan(world, a, name="Ours")
    listed = (await world.call("GET", BASE, a, a.tech_a)).json()
    assert [x["id"] for x in listed] == [mine["id"]]
    assert len((await world.call("GET", BASE, a, a.admin)).json()) == 2


async def _hold(world: World, org: Org, asset: dict[str, Any], person: uuid.UUID) -> None:
    given = await world.call(
        "PUT", f"/assets/{asset['id']}/holder", org, org.admin,
        json={"kind": "user", "id": str(person)}, headers=_match(asset["version"]),
    )  # fmt: skip
    assert given.status_code == 200, given.text


async def _mine(world: World, org: Org, user: uuid.UUID) -> list[dict[str, Any]]:
    found = await world.call(
        "GET", "/assets/mine", org, user, headers={"X-SupportX-Client": "portal"}
    )
    assert found.status_code == 200, found.text
    return list(found.json())


async def test_042_ac2_a_self_audit_asks_each_holder_to_confirm_only_their_own(
    world: World,
) -> None:
    a = world.a
    mine = await _asset(world, a, "Requester laptop", site_id=str(a.s1))
    theirs = await _asset(world, a, "Other laptop", site_id=str(a.s1))
    await _hold(world, a, mine, a.requester)
    await _hold(world, a, theirs, a.requester2)
    audit = await _start(
        world, a, await _plan(world, a, name="Self Q4", kind="self", site_ids=[str(a.s1)])
    )
    held = await _mine(world, a, a.requester)
    assert [h["id"] for h in held] == [mine["id"]]  # nothing of anyone else's
    ack = held[0]["acknowledgement"]
    assert (ack["status"], ack["audit_id"], ack["audit_name"]) == (
        "pending",
        audit["id"],
        "Self Q4",
    )
    their_ack = (await _mine(world, a, a.requester2))[0]["acknowledgement"]
    # Not theirs to confirm, and no audit data for a requester.
    stolen = await world.call(
        "POST", f"/assets/acknowledgements/{their_ack['id']}/answer", a, a.requester,
        json={"accept": True}, headers={"X-SupportX-Client": "portal"},
    )  # fmt: skip
    assert problem(stolen) == (404, "asset_acknowledgement_not_found")
    for path in (BASE, f"{BASE}/{audit['id']}", f"{BASE}/{audit['id']}/items"):
        assert problem(await world.call("GET", path, a, a.requester))[0] == 403
    confirmed = await world.call(
        "POST", f"/assets/acknowledgements/{ack['id']}/answer", a, a.requester,
        json={"accept": True}, headers={"X-SupportX-Client": "portal"},
    )  # fmt: skip
    assert confirmed.status_code == 200, confirmed.text
    disputed = await world.call(
        "POST", f"/assets/acknowledgements/{their_ack['id']}/answer", a, a.requester2,
        json={"accept": False, "comment": "Not mine"}, headers={"X-SupportX-Client": "portal"},
    )  # fmt: skip
    assert disputed.status_code == 200, disputed.text
    results = {i["name"]: i["result"] for i in await _items(world, a, audit)}
    assert results == {"Requester laptop": "found", "Other laptop": "missing"}
    # Missing because disputed, with the holder's words: told apart from "not found".
    (gap,) = await _items(world, a, audit, discrepancies="true")
    assert (gap["name"], gap["result"], gap["dispute_comment"]) == (
        "Other laptop",
        "missing",
        "Not mine",
    )
    assert (
        next(i for i in await _items(world, a, audit) if i["name"] == "Requester laptop")[
            "dispute_comment"
        ]
        is None
    )
    # Every audit asks again, through a new question for the same holding.
    again = await _start(
        world, a, await _plan(world, a, name="Self Q1", kind="self", site_ids=[str(a.s1)])
    )
    ack2 = (await _mine(world, a, a.requester))[0]["acknowledgement"]
    assert (ack2["status"], ack2["audit_id"]) == ("pending", again["id"])
    assert ack2["id"] != ack["id"]


async def test_new_audit_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    await _asset(world, a, "Counted", site_id=str(a.s1))
    await _start(world, a, await _plan(world, a, site_ids=[str(a.s1)]))
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in NEW_TABLES:
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608 - fixed names
        for statement in (
            "UPDATE asset_audits SET name = 'x'",
            "UPDATE asset_audit_items SET note = 'x'",
            "DELETE FROM asset_audit_auditors",
        ):
            assert (await session.execute(text(statement))).rowcount == 0
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        audit_id = await session.scalar(text("SELECT id FROM asset_audits LIMIT 1"))
    with pytest.raises(Exception, match="row-level security"):
        async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO asset_audit_auditors (tenant_id, audit_id, user_id)"
                    " VALUES (:t, :a, :u)"
                ),
                {"t": a.tenant, "a": audit_id, "u": a.tech_b},
            )
