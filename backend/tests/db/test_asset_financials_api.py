"""Asset financials, notes and history filters over HTTP (WP-049b s2; 0131).

REQ-AST-036 (cost lines, TCO), 037 (depreciation, book value), 038 (cost centre, GL code),
049 (history with filters), 050 (notes and attachments). The incident world: org A's admin holds
everything; technicians only view assets; tech C is made an asset manager where a test needs
one; org B is there for isolation.
"""

import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text

from app.core.errors import NotFound, PermissionDenied
from app.core.tenancy import TenantContext
from app.modules.assets.infra.models import AssetCost, AssetValuation
from app.modules.assets.service import valuations
from app.modules.assets.service.file_access import FILE_ACCESS
from app.modules.assets.service.realtime import ASSET_CHANGED, RECORD_KIND, ROUTES
from app.modules.identity_access import subject_for
from app.shared.events import EventEnvelope
from app.shared.files.ports import Action, OwnerType
from app.shared.realtime import record
from app.shared.reporting import provider_for
from tests.db import test_incidents_api
from tests.db.test_assets_api import _add, _product, _types, asset_manager
from tests.db.test_incidents_api import Org, World, field_codes, problem, role
from tests.db.test_knowledge_api import _match, _new

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/assets"
NEW_TABLES = ("asset_costs", "asset_notes", "asset_valuations")
D = Decimal


def _today() -> date:
    return valuations.today()  # the UTC day the figures are worked out for


async def _asset(world: World, org: Org, name: str, **values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    product = values.pop("product_id", None) or await _product(world, org, "laptop", f"P {name}")
    made = await _add(world, org, {"name": name, "product_id": product, **values})
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _fresh(world: World, org: Org, asset: dict[str, Any]) -> dict[str, Any]:
    found = await world.call("GET", f"{BASE}/{asset['id']}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def _money(
    world: World,
    org: Org,
    asset: dict[str, Any],
    user: uuid.UUID | None = None,
    **params: str,
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "GET", f"{BASE}/{asset['id']}/financials", org, user or org.admin, params=params
    )


async def _cost(
    world: World,
    org: Org,
    asset: dict[str, Any],
    amount: str,
    kind: str = "service",
    user: uuid.UUID | None = None,
    **extra: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - httpx response
    body = {"kind": kind, "incurred_on": _today().isoformat(), "amount": amount, **extra}
    return await world.call(
        "POST", f"{BASE}/{asset['id']}/costs", org, user or org.admin, json=body, headers=_new()
    )


async def _events(world: World, org: Org, kind: str) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = $2"
        " ORDER BY created_at",
        org.tenant,
        kind,
    )
    return [json.loads(r["envelope"]) for r in rows]


# --- REQ-AST-036 ---------------------------------------------------------------------------------


async def test_036_ac1_a_service_cost_adds_to_the_total_cost_of_ownership(world: World) -> None:
    """Adding a service cost of 200 to an asset bought for 1,200: operational 200, TCO 1,400."""
    a = world.a
    laptop = await _asset(world, a, "TCO laptop", purchase_price="1000.00", purchase_tax="200.00")
    added = await _cost(world, a, laptop, "200", description="  New   battery ")
    assert added.status_code == 201, added.text
    line = added.json()
    assert (line["kind"], D(line["amount"]), line["description"]) == (
        "service",
        D(200),
        "New battery",
    )
    money = (await _money(world, a, laptop)).json()
    assert (D(money["purchase"]), D(money["operational"]), D(money["total_cost"])) == (
        D(1200),
        D(200),
        D(1400),
    )
    assert (money["currency"], money["currency_differs"]) == ("USD", False)
    assert [c["id"] for c in money["costs"]] == [line["id"]]
    # A disposal cost line counts as disposal; changing and removing need the version read.
    disposal = (await _cost(world, a, laptop, "50", kind="disposal")).json()
    stale = await world.call(
        "PATCH", f"{BASE}/{laptop['id']}/costs/{line['id']}", a, a.admin,
        json={"amount": "250"}, headers=_match(line["version"] + 5),
    )  # fmt: skip
    assert problem(stale) == (409, "version_conflict")
    changed = await world.call(
        "PATCH", f"{BASE}/{laptop['id']}/costs/{line['id']}", a, a.admin,
        json={"amount": "250"}, headers=_match(line["version"]),
    )  # fmt: skip
    assert changed.status_code == 200, changed.text
    gone = await world.call(
        "DELETE", f"{BASE}/{laptop['id']}/costs/{disposal['id']}", a, a.admin,
        headers=_match(disposal["version"]),
    )  # fmt: skip
    assert gone.status_code == 204, gone.text
    money = (await _money(world, a, laptop)).json()
    assert (D(money["operational"]), D(money["disposal"]), D(money["total_cost"])) == (
        D(250),
        D(0),
        D(1450),
    )
    # Checked like every amount: never negative, cents only, a known kind.
    assert field_codes(await _cost(world, a, laptop, "-1")) == {"amount": "below_minimum"}
    bad_kind = await _cost(world, a, laptop, "1", kind="lunch")
    assert bad_kind.status_code == 422
    # The asset's history names the line (its ID only, never the amount).
    history = (await world.call("GET", f"{BASE}/{laptop['id']}/history", a, a.tech_a)).json()
    costs = [c for e in history["items"] for c in e["changes"] if c["field"] == "cost"]
    assert {c["new"] for c in costs} == {line["id"], disposal["id"]}
    events = await _events(world, a, "assets.cost.changed")
    assert {e["payload"]["action"] for e in events} >= {"created", "updated", "deleted"}
    assert all("amount" not in e["payload"] for e in events)  # §8.2: IDs only


async def test_036_ac3_a_thousand_lines_add_up_to_the_cent(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Many lines", purchase_price="0.10")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant, a.admin)) as session:
        session.add_all(
            AssetCost(
                tenant_id=a.tenant,
                asset_id=uuid.UUID(asset["id"]),
                kind="other",
                incurred_on=_today(),
                amount=D("0.20"),
            )
            for _ in range(1000)
        )
    money = (await _money(world, a, asset)).json()
    assert money["operational"] == "200.00"
    assert money["total_cost"] == "200.10"  # 0.1 + 1,000 x 0.2: no float drift


# --- REQ-AST-037 ---------------------------------------------------------------------------------


async def test_037_ac1_a_1200_asset_over_three_years_is_worth_800_after_one(world: World) -> None:
    a = world.a
    bought = _today() - timedelta(days=366)
    asset = await _asset(world, a, "Depreciating", purchase_price="1200", acquired_on=str(bought))
    set_up = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.admin,
        json={"depreciation_method": "straight_line", "useful_life_years": 3},
        headers=_match(asset["version"]),
    )  # fmt: skip
    assert set_up.status_code == 200, set_up.text
    money = (await _money(world, a, asset)).json()
    assert D(money["book_value"]) == 800
    terms = money["depreciation"]
    assert (terms["method"], terms["method_from"], terms["useful_life_years"]) == (
        "straight_line",
        "asset",
        3,
    )
    assert [D(y["closing"]) for y in terms["schedule"]] == [800, 400, 0]
    # On any day asked for: three months later, 100 more is gone.
    later = (await _money(world, a, asset, on=str(bought + timedelta(days=365 + 92)))).json()
    assert D(later["book_value"]) == 700
    # A salvage value above the cost is refused.
    fresh = await _fresh(world, a, asset)
    too_much = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.admin,
        json={"salvage_value": "5000"}, headers=_match(fresh["version"]),
    )  # fmt: skip
    assert field_codes(too_much) == {"salvage_value": "asset_salvage_above_cost"}
    # The valuation (what reports read) followed the save.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        valued = await session.get(AssetValuation, (a.tenant, uuid.UUID(asset["id"])))
    assert valued is not None
    assert (valued.book_value, valued.total_cost) == (D(800), D(1200))


async def test_037_ac2_the_products_settings_apply_to_assets_without_their_own(
    world: World,
) -> None:
    a = world.a
    types = await _types(world, a)
    made = await world.call(
        "POST", f"{BASE}/products", a, a.admin,
        json={
            "product_type_id": types["laptop"]["id"], "name": "Depreciated model",
            "depreciation_method": "double_declining_balance", "useful_life_years": 5,
            "salvage_value": "1000", "gl_code": "GL-6100",
        },
        headers=_new(),
    )  # fmt: skip
    assert made.status_code == 201, made.text
    bought = _today() - timedelta(days=366)
    asset = await _asset(
        world, a, "Inherits", product_id=made.json()["id"], purchase_price="10000",
        acquired_on=str(bought),
    )  # fmt: skip
    money = (await _money(world, a, asset)).json()
    terms = money["depreciation"]
    assert (terms["method"], terms["method_from"], terms["life_from"]) == (
        "double_declining_balance",
        "product",
        "product",
    )
    assert D(money["book_value"]) == 6000  # 40 % of 10,000 in the first year
    assert asset["gl_code"] == "GL-6100"  # REQ-AST-038: from the product
    # "No depreciation" on the asset itself wins over the product's.
    off = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.admin,
        json={"depreciation_method": "none"}, headers=_match(asset["version"]),
    )  # fmt: skip
    assert off.status_code == 200, off.text
    money = (await _money(world, a, asset)).json()
    assert (money["depreciation"]["method"], D(money["book_value"])) == ("none", D(10000))
    assert money["depreciation"]["schedule"] == []


# --- REQ-AST-038 and the permission ---------------------------------------------------------------


async def test_038_cost_centres_and_a_report_of_book_value_by_cost_centre(world: World) -> None:
    """AC2: book value by cost centre (the reporting source) matches the assets' book values."""
    a = world.a
    bought = str(_today() - timedelta(days=366))
    terms = {"depreciation_method": "straight_line", "useful_life_years": 4}
    one = await _asset(world, a, "CC one", purchase_price="1200", acquired_on=bought,
                       cost_centre=" CC-10 ", **terms)  # fmt: skip
    two = await _asset(world, a, "CC two", purchase_price="400", acquired_on=bought,
                       cost_centre="CC-10", **terms)  # fmt: skip
    other = await _asset(world, a, "CC other", purchase_price="100", cost_centre="CC-20")
    assert one["cost_centre"] == "CC-10"
    listed = await world.call("GET", f"{BASE}?cost_centre=CC-10", a, a.admin)
    assert {x["id"] for x in listed.json()["items"]} == {one["id"], two["id"]}
    values = {}
    for asset in (one, two, other):
        values[asset["id"]] = D((await _money(world, a, asset)).json()["book_value"])
    assert values[one["id"]] == 900  # 1,200 less a quarter
    async with world.app.state.db.tenant_session(TenantContext(a.tenant, a.admin)) as session:
        subject = await subject_for(session, a.tenant, a.admin)
        source = await provider_for("asset").source(session, subject)
        fields = source.fields.fields
        assert {"cost_centre", "book_value", "total_cost"} <= set(source.dimensions)
        grouped = await session.execute(
            source.rows.with_only_columns(
                fields["cost_centre"].column,
                func.sum(fields["book_value"].column),
                func.sum(fields["total_cost"].column),
                maintain_column_froms=True,
            ).group_by(fields["cost_centre"].column)
        )
        by_centre = {row[0]: (row[1], row[2]) for row in grouped}
    assert by_centre["CC-10"] == (values[one["id"]] + values[two["id"]], D(1600))
    assert by_centre["CC-20"] == (D(100), D(100))


async def test_view_financials_guards_costs_depreciation_and_book_value(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Guarded", purchase_price="500")
    # A technician sees the asset, never its money.
    assert (await world.call("GET", f"{BASE}/{asset['id']}", a, a.tech_a)).status_code == 200
    assert problem(await _money(world, a, asset, a.tech_a)) == (403, "permission_denied")
    # A custom role managing assets without money: changes the asset, never its depreciation.
    manager = await role(world, a, "Assets, no money", [("assets.view", "all"),
                                                        ("assets.manage", "all")])  # fmt: skip
    given = await world.call("PUT", f"/users/{a.tech_b}/roles/{manager}", a, a.admin)
    assert given.status_code == 204, given.text
    renamed = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.tech_b,
        json={"name": "Renamed", "cost_centre": "CC-1"}, headers=_match(asset["version"]),
    )  # fmt: skip
    assert renamed.status_code == 200, renamed.text
    refused = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.tech_b,
        json={"useful_life_years": 3}, headers=_match(renamed.json()["version"]),
    )  # fmt: skip
    assert problem(refused) == (403, "permission_denied")
    assert refused.json()["params"]["permission"] == "assets.view_financials"
    assert problem(await _cost(world, a, asset, "1", user=a.tech_b)) == (403, "permission_denied")
    async with world.app.state.db.tenant_session(TenantContext(a.tenant, a.tech_b)) as session:
        source = await provider_for("asset").source(
            session, await subject_for(session, a.tenant, a.tech_b)
        )
    assert "book_value" not in source.fields.fields
    assert "cost_centre" in source.dimensions
    # The built-in asset manager sees and changes the money.
    await asset_manager(world, a, a.tech_c)
    assert (await _money(world, a, asset, a.tech_c)).status_code == 200
    assert (await _cost(world, a, asset, "3", user=a.tech_c)).status_code == 201


# --- REQ-AST-050 ---------------------------------------------------------------------------------


async def _note(
    world: World, org: Org, asset: dict[str, Any], body: str, user: uuid.UUID | None = None
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "POST", f"{BASE}/{asset['id']}/notes", org, user or org.admin,
        json={"body": body}, headers=_new(),
    )  # fmt: skip


def _mention(user: uuid.UUID) -> str:
    return f'<span data-type="mention" data-id="{user}">@someone</span>'


async def test_050_notes_mentions_edits_and_deletes(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Noted")
    stranger = uuid.uuid4()
    body = (
        f"<p>Replaced the fan {_mention(a.tech_a)} {_mention(a.requester)} {_mention(stranger)}"
        '<img data-file-id="0190f3a1-0000-7000-8000-000000000001" alt="x">'
        "<script>alert(1)</script></p>"
    )
    added = await _note(world, a, asset, body, a.tech_b)  # technicians may add notes
    assert added.status_code == 201, added.text
    note = added.json()
    # The requester cannot see the asset: not told, and the author hears who (REQ-INC-063 AC2).
    assert note["not_notified"] == [str(a.requester)]
    assert "<script" not in note["body"]
    assert "<img" not in note["body"]
    assert str(stranger) not in note["body"]  # not a user here: plain words
    assert set(note["mentioned_ids"]) == {str(a.tech_a), str(a.requester)}
    (event,) = [e for e in await _events(world, a, "assets.note.changed")
                if e["payload"]["note_id"] == note["id"]]  # fmt: skip
    assert event["payload"]["mentioned"] == [str(a.tech_a)]
    assert "body" not in event["payload"]
    # Someone else's note: not without assets.manage (REQ-INC-062 AC2).
    others = await world.call(
        "PATCH", f"{BASE}/{asset['id']}/notes/{note['id']}", a, a.tech_a,
        json={"body": "<p>Mine now</p>"}, headers=_match(note["version"]),
    )  # fmt: skip
    assert problem(others) == (403, "permission_denied")
    edited = await world.call(
        "PATCH", f"{BASE}/{asset['id']}/notes/{note['id']}", a, a.tech_b,
        json={"body": "<p>Replaced the fan and the PSU</p>"}, headers=_match(note["version"]),
    )  # fmt: skip
    assert edited.status_code == 200, edited.text
    assert edited.json()["edited_at"] is not None  # the "edited" marker (AC1)
    versions = (
        await world.call("GET", f"{BASE}/{asset['id']}/notes/{note['id']}/history", a, a.tech_a)
    ).json()
    assert versions[0]["body"] == "<p>Replaced the fan and the PSU</p>"
    assert versions[0]["previous"] == note["body"]  # the earlier text is kept
    # The admin (assets.manage) deletes it: a "note deleted" line with who and when stays.
    deleted = await world.call(
        "DELETE", f"{BASE}/{asset['id']}/notes/{note['id']}", a, a.admin,
        headers=_match(edited.json()["version"]),
    )  # fmt: skip
    assert deleted.status_code == 204, deleted.text
    (listed,) = (await world.call("GET", f"{BASE}/{asset['id']}/notes", a, a.tech_a)).json()
    assert (listed["body"], listed["deleted_by_name"]) == (None, "Alpha Admin")
    assert listed["deleted_at"] is not None
    assert listed["may_change"] is False
    assert field_codes(await _note(world, a, asset, "<p></p>")) == {"body": "required"}
    # Requesters see no asset notes.
    hidden = await world.call("GET", f"{BASE}/{asset['id']}/notes", a, a.requester)
    assert hidden.status_code == 403


async def test_050_a_note_appears_live_for_other_viewers(world: World) -> None:
    """AC1: the asset's channel hears of it (IDs and the part's name only)."""
    a = world.a
    asset = await _asset(world, a, "Live note")
    note = (await _note(world, a, asset, "<p>Hello</p>")).json()
    envelope = EventEnvelope.model_validate(
        next(
            e
            for e in await _events(world, a, "assets.note.changed")
            if e["payload"]["note_id"] == note["id"]
        )
    )
    route = next(r for r in ROUTES if envelope.event_type in r.event_types)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(envelope, session)
    (published,) = effects.publications
    assert published.channel == record(a.tenant, RECORD_KIND, uuid.UUID(asset["id"]))
    assert (published.type, published.ids, published.fields) == (
        ASSET_CHANGED,
        (asset["id"], note["id"]),
        ("notes",),
    )


async def test_050_attachments_are_the_assets_files_seen_by_viewers_added_by_managers(
    world: World,
) -> None:
    """The files service asks the assets module (scanning and refusing infected files is its own,
    as on incidents, REQ-INC-079)."""
    a, b = world.a, world.b
    asset = await _asset(world, a, "With files")
    asset_id = uuid.UUID(asset["id"])
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        tech = await subject_for(session, a.tenant, a.tech_a)
        admin = await subject_for(session, a.tenant, a.admin)
        owner = await FILE_ACCESS.check(session, tech, OwnerType.ASSET, asset_id, Action.VIEW)
        assert (owner.record_type, owner.record_id) == ("asset", asset_id)
        with pytest.raises(PermissionDenied):
            await FILE_ACCESS.check(session, tech, OwnerType.ASSET, asset_id, Action.ATTACH)
        await FILE_ACCESS.check(session, admin, OwnerType.ASSET, asset_id, Action.ATTACH)
        owners = await FILE_ACCESS.visible_owners(session, tech, "asset", asset_id)
        assert owners == {(OwnerType.ASSET, asset_id)}
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        stranger = await subject_for(session, b.tenant, b.admin)
        with pytest.raises(NotFound):
            await FILE_ACCESS.check(session, stranger, OwnerType.ASSET, asset_id, Action.VIEW)


# --- REQ-AST-049 ---------------------------------------------------------------------------------


async def test_049_history_filters_by_view_field_source_person_and_day(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Filtered")
    renamed = await world.call(
        "PATCH", f"{BASE}/{asset['id']}", a, a.admin,
        json={"name": "Filtered 2"}, headers=_match(asset["version"]),
    )  # fmt: skip
    held = await world.call(
        "PUT", f"{BASE}/{asset['id']}/holder", a, a.admin,
        json={"kind": "user", "id": str(a.tech_a)}, headers=_match(renamed.json()["version"]),
    )  # fmt: skip
    assert held.status_code == 200, held.text
    moves = (await world.call("GET", f"{BASE}/{asset['id']}/moves", a, a.admin)).json()
    target = next(m for m in moves if m["allowed"] and not m["reason_required"])
    moved = await world.call(
        "POST", f"{BASE}/{asset['id']}/move", a, a.admin,
        json={"to_state_id": target["to_state_id"]}, headers=_match(held.json()["version"]),
    )  # fmt: skip
    assert moved.status_code == 200, moved.text
    path = f"{BASE}/{asset['id']}/history"

    async def fields(**params: Any) -> list[set[str]]:  # noqa: ANN401 - query values
        found = await world.call("GET", path, a, a.tech_a, params=params)
        assert found.status_code == 200, found.text
        return [{c["field"] for c in e["changes"]} for e in found.json()["items"]]

    assert {"state_id"} in await fields()
    assert all(f == {"state_id"} for f in await fields(view="state"))
    assignment = await fields(view="assignment")  # AC2: owner changes (and loans) only
    assert assignment
    assert all(f <= {"owner_user_id", "department_id", "parent_asset_id"} for f in assignment)
    assert await fields(field="name") == [{"name"}, {"name"}]  # renamed, and when it was made
    assert await fields(source="email") == []
    assert len(await fields(actor_id=str(a.admin))) >= 3
    assert await fields(actor_id=str(a.tech_b)) == []
    today = _today()  # days are UTC days
    assert await fields(until=str(today - timedelta(days=1))) == []
    assert len(await fields(since=str(today), until=str(today))) >= 4


# --- isolation, the sweep ------------------------------------------------------------------------


async def test_new_tables_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    asset = await _asset(world, a, "Isolated", purchase_price="10")
    assert (await _cost(world, a, asset, "5")).status_code == 201
    assert (await _note(world, a, asset, "<p>Private</p>")).status_code == 201
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in NEW_TABLES:
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 0  # noqa: S608 - fixed names
        for statement in (
            "UPDATE asset_costs SET amount = 0",
            "UPDATE asset_notes SET body = 'x'",
            "UPDATE asset_valuations SET total_cost = 0, updated_at = now()",
        ):
            assert (await session.execute(text(statement))).rowcount == 0
    assert (await _money(world, b, asset)).status_code == 404
    assert (await world.call("GET", f"{BASE}/{asset['id']}/notes", b, b.admin)).status_code == 404
    assert (await _cost(world, b, asset, "1")).status_code == 404


async def test_the_daily_sweep_values_assets_not_valued_today(world: World) -> None:
    a = world.a
    asset = await _asset(world, a, "Swept", purchase_price="300")
    asset_id = uuid.UUID(asset["id"])
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await session.execute(
            text(
                "UPDATE asset_valuations SET valued_on = current_date - 3, total_cost = 0,"
                " updated_at = now() WHERE asset_id = :id"
            ),
            {"id": asset_id},
        )
    await valuations.valuation_sweep(world.app.state.db, world.app.state.settings)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        valued = await session.scalar(
            select(AssetValuation).where(AssetValuation.asset_id == asset_id)
        )
        assert valued is not None
        assert (valued.valued_on, valued.total_cost) == (valuations.today(), D(300))
        assert await valuations.refresh_stale(session) == 0  # nothing left for today
