"""The asset page's linked records with lane A's port registered (WP-049b s4a; REQ-AST-044/045).

Real incidents of the incident world (tests/db/test_incidents_api.py): tech_a is a technician in
group GA (group scope), so an incident of group GB is not theirs to see. D-158: a record the
viewer may not see is neither counted nor listed. The counters follow a new link live (the
asset's channel), and an incident raised with an asset names itself in the asset's history.
"""

import json
import uuid
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.assets.service import linked
from app.modules.assets.service.realtime import ASSET_CHANGED, LINKED_FIELD, RECORD_KIND, ROUTES
from app.shared.events import EventEnvelope
from app.shared.realtime import record
from tests.db import test_incidents_api
from tests.db.test_asset_holders_api import _asset
from tests.db.test_incidents_api import BASE, World

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused


async def _link(world: World, item: dict[str, Any], asset: dict[str, Any]) -> None:
    added = await world.call(
        "POST", f"{BASE}/{item['id']}/assets", world.a, world.a.admin,
        json={"asset_ids": [asset["id"]]}, headers={"Idempotency-Key": str(uuid.uuid4())},
    )  # fmt: skip
    assert added.status_code == 201, added.text


async def _counts(world: World, asset: dict[str, Any], user: uuid.UUID) -> dict[str, Any]:
    found = await world.call("GET", f"/assets/{asset['id']}/linked", world.a, user)
    assert found.status_code == 200, found.text
    return dict(found.json())


def _incidents(summary: dict[str, Any]) -> tuple[int, int]:
    row = next(k for k in summary["kinds"] if k["kind"] == "incident")
    return row["still_worked"], row["total"]


async def _link_events(world: World, asset: dict[str, Any]) -> list[EventEnvelope]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.asset_link.changed' ORDER BY created_at",
        world.a.tenant,
    )
    found = [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]
    return [e for e in found if e.payload["asset_id"] == asset["id"]]


async def test_044_d158_visible_records_are_counted_and_listed_hidden_ones_never(
    world: World,
) -> None:
    a = world.a
    laptop = await _asset(world, "Panel laptop")
    mine = await world.create(a, a.admin, subject="Seen by tech A", group_id=str(a.ga))
    theirs = await world.create(a, a.admin, subject="Group B only", group_id=str(a.gb))
    before = await _counts(world, laptop, a.tech_a)
    assert before["available"] is True  # the port is registered now: the panel shows
    assert _incidents(before) == (0, 0)
    await _link(world, mine, laptop)
    await _link(world, theirs, laptop)
    # tech_a sees one incident; the admin, who sees both, two (the counters are the viewer's).
    assert _incidents(await _counts(world, laptop, a.tech_a)) == (1, 1)
    assert _incidents(await _counts(world, laptop, a.admin)) == (2, 2)
    page = await world.call("GET", f"/assets/{laptop['id']}/linked/incident", a, a.tech_a)
    assert page.status_code == 200, page.text
    listed = page.json()["items"]
    assert [r["id"] for r in listed] == [mine["id"]]
    assert listed[0]["display_id"] == mine["display_id"]
    assert listed[0]["still_worked"] is True
    assert theirs["display_id"] not in page.text  # never named
    # Pages by cursor, newest first, for the admin.
    first = await world.call(
        "GET", f"/assets/{laptop['id']}/linked/incident", a, a.admin, params={"limit": "1"}
    )
    body = first.json()
    assert [r["id"] for r in body["items"]] == [theirs["id"]]
    assert body["next_cursor"] is not None
    rest = await world.call(
        "GET", f"/assets/{laptop['id']}/linked/incident", a, a.admin,
        params={"limit": "1", "cursor": body["next_cursor"]},
    )  # fmt: skip
    assert [r["id"] for r in rest.json()["items"]] == [mine["id"]]
    # Another tenant sees nothing of the asset at all.
    assert (
        await world.call("GET", f"/assets/{laptop['id']}/linked", world.b, world.b.admin)
    ).status_code == 404


async def test_044_the_counters_follow_a_new_link_live(world: World) -> None:
    a = world.a
    monitor = await _asset(world, "Live monitor")
    item = await world.create(a, a.admin, subject="Live link", group_id=str(a.ga))
    await _link(world, item, monitor)
    (event,) = await _link_events(world, monitor)
    route = next(r for r in ROUTES if event.event_type in r.event_types)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(event, session)
    (published,) = effects.publications
    assert published.channel == record(a.tenant, RECORD_KIND, uuid.UUID(monitor["id"]))
    assert (published.type, published.fields) == (ASSET_CHANGED, (LINKED_FIELD,))
    assert _incidents(await _counts(world, monitor, a.tech_a)) == (1, 1)
    # A status change reaches the asset through the port's asset_ids_of.
    moved = event.model_copy(
        update={"event_type": "work_items.work_item.status_changed",
                "payload": {"work_item_id": item["id"]}}
    )  # fmt: skip
    status_route = next(r for r in ROUTES if moved.event_type in r.event_types)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        status_effects = await status_route.route(moved, session)
    assert [p.channel for p in status_effects.publications] == [
        record(a.tenant, RECORD_KIND, uuid.UUID(monitor["id"]))
    ]


async def test_045_an_incident_raised_with_an_asset_names_itself_in_the_asset_history(
    world: World,
) -> None:
    a = world.a
    phone = await _asset(world, "Raised phone")
    item = await world.create(a, a.admin, subject="Raised from the phone", asset_ids=[phone["id"]])
    (event,) = await _link_events(world, phone)
    assert event.payload["at_creation"] is True  # lane A's real event
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await linked.on_asset_link_changed(event, session)
    history = (await world.call("GET", f"/assets/{phone['id']}/history", a, a.admin)).json()
    lines = [
        c["new"]
        for e in history["items"]
        for c in e["changes"]
        if c["field"] == linked.RAISED_FIELD
    ]
    assert lines == [
        {"work_item_id": item["id"], "display_id": item["display_id"], "type": "incident"}
    ]
