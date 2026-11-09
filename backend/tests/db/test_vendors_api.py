"""Vendors over HTTP (WP-049a s2; REQ-PUR-001): the minimal procurement module.

The incident world: org A has an admin (every permission) and technicians (vendors.view only);
org B is there for isolation.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.procurement import register_vendor_usage, vendor_problem
from app.modules.procurement.service import vendors as vendor_service
from app.modules.procurement.service.realtime import ROUTES, VENDORS_CHANGED
from app.shared.events import EventEnvelope
from app.shared.realtime import broadcast
from tests.db import test_incidents_api
from tests.db.test_incidents_api import Org, World, field_codes, problem
from tests.db.test_knowledge_api import _match, _new

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

BASE = "/procurement/vendors"


async def _add(world: World, org: Org, body: dict[str, Any], user: uuid.UUID | None = None) -> Any:  # noqa: ANN401 - httpx response
    return await world.call("POST", BASE, org, user or org.admin, json=body, headers=_new())


async def _patch(world: World, org: Org, vendor: dict[str, Any], body: dict[str, Any]) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "PATCH",
        f"{BASE}/{vendor['id']}",
        org,
        org.admin,
        json=body,
        headers=_match(vendor["version"]),
    )


async def test_vendors_are_added_listed_changed_and_named_once(world: World) -> None:
    a = world.a
    made = await _add(
        world,
        a,
        {
            "name": "  Acme   Supplies ",
            "currency": "USD",
            "email": "sales@acme.test",
            "phone": "+92 (51) 111-222",
            "website": "https://acme.test",
        },
    )
    assert made.status_code == 201, made.text
    vendor = made.json()
    assert vendor["name"] == "Acme Supplies"
    assert vendor["is_active"] is True
    assert made.headers["ETag"] == '"1"'
    # Names are unique among live vendors, case aside.
    twin = await _add(world, a, {"name": "ACME supplies"})
    assert field_codes(twin) == {"name": "vendor_name_taken"}
    bad = await _add(
        world, a, {"name": "Bad", "email": "nope", "phone": "call me", "website": "acme.test"}
    )
    assert field_codes(bad) == {
        "email": "invalid_email",
        "phone": "invalid_phone",
        "website": "invalid_website",
    }
    # Technicians read vendors (the asset form picks one).
    listed = await world.call("GET", f"{BASE}?sort=name", a, a.tech_a)
    assert listed.status_code == 200, listed.text
    assert [v["name"] for v in listed.json()["items"]] == ["Acme Supplies"]
    changed = await _patch(world, a, vendor, {"contact_person": "Sara", "is_active": False})
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    stale = await _patch(world, a, vendor, {"fax": "123 456"})
    assert problem(stale) == (409, "version_conflict")
    inactive = await world.call("GET", f"{BASE}?filter=" + json.dumps(
        {"field": "is_active", "op": "eq", "value": False}), a, a.admin)  # fmt: skip
    assert [v["name"] for v in inactive.json()["items"]] == ["Acme Supplies"]


async def test_only_vendor_admins_add_and_change_vendors(world: World) -> None:
    a = world.a
    refused = await _add(world, a, {"name": "Sneaky"}, a.tech_a)
    assert problem(refused)[0] == 403
    vendor = (await _add(world, a, {"name": "Globex"})).json()
    edit = await world.call(
        "PATCH",
        f"{BASE}/{vendor['id']}",
        a,
        a.tech_a,
        json={"name": "Mine"},
        headers=_match(vendor["version"]),
    )
    assert problem(edit)[0] == 403
    gone = await world.call(
        "DELETE", f"{BASE}/{vendor['id']}", a, a.tech_a, headers=_match(vendor["version"])
    )
    assert problem(gone)[0] == 403


async def test_an_inactive_vendor_stays_on_old_records_only(world: World) -> None:
    a = world.a
    vendor = (await _add(world, a, {"name": "Initech"})).json()
    vendor = (await _patch(world, a, vendor, {"is_active": False})).json()
    vid = uuid.UUID(vendor["id"])
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await vendor_problem(session, vid) == "vendor_inactive"
        assert await vendor_problem(session, vid, current=vid) is None  # already its vendor
        assert await vendor_problem(session, uuid.uuid4()) == "vendor_not_found"


async def test_a_vendor_records_still_name_cannot_be_deleted(world: World) -> None:
    a = world.a
    vendor = (await _add(world, a, {"name": "Umbrella"})).json()
    used_by: set[str] = {vendor["id"]}

    async def count(session: object, vendor_id: uuid.UUID) -> int:
        del session
        return 3 if str(vendor_id) in used_by else 0

    register_vendor_usage(count)
    try:
        refused = await world.call(
            "DELETE", f"{BASE}/{vendor['id']}", a, a.admin, headers=_match(vendor["version"])
        )
        assert problem(refused) == (409, "vendor_in_use")
        assert refused.json()["params"] == {"used": 3}
        used_by.clear()
        deleted = await world.call(
            "DELETE", f"{BASE}/{vendor['id']}", a, a.admin, headers=_match(vendor["version"])
        )
        assert deleted.status_code == 204, deleted.text
    finally:
        vendor_service._USAGE.remove(count)  # noqa: SLF001 - the test's own counter
    missing = await world.call("GET", f"{BASE}/{vendor['id']}", a, a.admin)
    assert problem(missing) == (404, "vendor_not_found")
    # The name is free again once the vendor is in the trash.
    assert (await _add(world, a, {"name": "Umbrella"})).status_code == 201


async def test_vendor_saves_keep_history_events_audit_and_reach_screens(world: World) -> None:
    a = world.a
    vendor = (await _add(world, a, {"name": "Hooli", "email": "buy@hooli.test"})).json()
    await _patch(world, a, vendor, {"phone": "+1 555 0100"})
    history = await world.sql(
        "SELECT field FROM field_changes WHERE record_type = 'vendor' AND record_id = $1",
        uuid.UUID(vendor["id"]),
    )
    assert {"name", "email", "phone"} <= {r["field"] for r in history}
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'procurement.vendor.changed' ORDER BY created_at",
        a.tenant,
    )
    envelopes = [EventEnvelope.model_validate(json.loads(r["envelope"])) for r in rows]
    # IDs and field names only (§8.2): never the name, email or phone.
    assert all(set(e.payload) == {"vendor_id", "action", "changed_fields"} for e in envelopes)
    assert envelopes[-1].payload["changed_fields"] == ["phone"]
    audit = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1 AND outcome = 'done'"
        " AND action LIKE 'vendor.%'",
        a.tenant,
    )
    assert sorted(r["action"] for r in audit) == ["vendor.created", "vendor.updated"]
    route = next(r for r in ROUTES if envelopes[-1].event_type in r.event_types)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        effects = await route.route(envelopes[-1], session)
    [publication] = effects.publications
    assert publication.type == VENDORS_CHANGED
    assert publication.channel == broadcast(a.tenant)
    assert publication.ids == (vendor["id"],)
    assert publication.fields == ("phone",)


async def test_vendors_are_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    vendor = (await _add(world, a, {"name": "Only A"})).json()
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM vendors")) == 0
        assert (await session.execute(text("UPDATE vendors SET name = 'x'"))).rowcount == 0
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text("INSERT INTO vendors (id, tenant_id, name) VALUES (:id, :other, 'stolen')"),
                {"id": uuid.uuid4(), "other": a.tenant},
            )
    assert problem(await world.call("GET", f"{BASE}/{vendor['id']}", b, b.admin)) == (
        404,
        "vendor_not_found",
    )
    # B may use the same name: uniqueness is per tenant.
    assert (await _add(world, b, {"name": "Only A"})).status_code == 201
