"""Custom fields over HTTP (WP-026, REQ-INC-014; D-087). Same world as the incidents tests.

Definitions live in the metadata module (`/custom-fields`); values on the incident (`custom`),
checked, filtered with the shared DSL as `custom.<key>`, recorded in history and searchable.
"""

import json
import uuid
from typing import Any

import httpx
from sqlalchemy import text

from app.core.tenancy import TenantContext
from tests.db.test_incident_settings_api import new_template, patch_template
from tests.db.test_incidents_api import (
    BASE,
    CONSOLE,
    Org,
    World,
    envelopes,
    field_codes,
    ids,
    world,
)
from tooling import custom_field_indexes

FIELDS = "/custom-fields"
__all__ = ["world"]  # the fixture, re-used


async def add_field(world: World, org: Org, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    made = await add(world, org, **body)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def add(world: World, org: Org, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    return await world.call(
        "POST", FIELDS, org, org.admin, json={"entity": "incident", **body}, headers=CONSOLE
    )


async def change(
    world: World,
    org: Org,
    found: dict[str, Any],
    **body: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "PATCH",
        f"{FIELDS}/{found['id']}",
        org,
        org.admin,
        json=body,
        headers={"If-Match": f'"{found["version"]}"', **CONSOLE},
    )


async def listed(
    world: World, org: Org, user: uuid.UUID | None = None, query: str = ""
) -> list[dict[str, Any]]:
    response = await world.call("GET", f"{FIELDS}?entity=incident{query}", org, user or org.admin)
    assert response.status_code == 200, response.text
    return list(response.json())


def dsl(node: dict[str, Any]) -> str:
    return "?" + str(httpx.QueryParams({"filter": json.dumps(node)}))


def choices(*names: str) -> list[dict[str, Any]]:
    return [{"labels": {"en": n}} for n in names]


async def test_req_inc_014_ac1_pick_list_on_template_filled_and_filtered(world: World) -> None:
    a = world.a
    field = await add_field(
        world,
        a,
        field_type="choice",
        labels={"en": "Affected floor", "ar": "الطابق"},
        choices=choices("Ground", "First"),
    )
    assert field["key"] == "affected_floor"
    assert [c["code"] for c in field["choices"]] == ["ground", "first"]
    template = await new_template(
        world,
        a,
        labels={"en": "Floor issue"},
        fields={"custom.affected_floor": {"shown": True, "required": True}},
    )
    assert template.status_code == 201, template.text
    tid = template.json()["id"]
    missing = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"subject": "Lights", "requester_id": str(a.requester), "template_id": tid},
        headers=CONSOLE,
    )
    assert field_codes(missing) == {"custom.affected_floor": "required"}
    item = await world.create(a, a.admin, template_id=tid, custom={"affected_floor": "first"})
    assert item["custom"] == {"affected_floor": "first"}
    other = await world.create(a, a.admin, custom={"affected_floor": "ground"})
    found = await ids(
        world, a, a.admin, dsl({"field": "custom.affected_floor", "op": "eq", "value": "first"})
    )
    assert item["id"] in found
    assert other["id"] not in found
    bad = await world.call(
        "GET",
        BASE + dsl({"field": "custom.affected_floor", "op": "eq", "value": "nowhere"}),
        a,
        a.admin,
    )
    assert bad.status_code == 422, bad.text
    # A template rule for a field the tenant does not have is refused.
    unknown = await new_template(
        world, a, labels={"en": "Ghost"}, fields={"custom.ghost": {"shown": True}}
    )
    assert field_codes(unknown) == {"fields.custom.ghost": "unknown_field"}


async def test_values_are_checked_and_stored_by_type(world: World) -> None:
    a = world.a
    await add_field(
        world,
        a,
        field_type="decimal",
        labels={"en": "Cost"},
        validation={"min": "0", "max": "1000.50"},
    )
    await add_field(world, a, field_type="date", labels={"en": "Due"})
    await add_field(world, a, field_type="datetime", labels={"en": "Seen at"})
    await add_field(
        world,
        a,
        field_type="multi_choice",
        labels={"en": "Systems"},
        choices=choices("Mail", "VPN", "Wifi"),
    )
    await add_field(world, a, field_type="yes_no", labels={"en": "Urgent call"})
    await add_field(world, a, field_type="email", labels={"en": "Contact mail"})
    await add_field(world, a, field_type="person", labels={"en": "Manager"})
    item = await world.create(
        a,
        a.admin,
        custom={
            "cost": "12.5",
            "due": "2026-11-02",
            "seen_at": "2026-10-26T10:00:00+03:00",
            "systems": ["vpn", "mail", "vpn"],
            "urgent_call": True,
            "contact_mail": " ops@example.com ",
            "manager": str(a.tech_a),
        },
    )
    assert item["custom"] == {
        "cost": 12.5,
        "due": "2026-11-02",
        "seen_at": "2026-10-26T07:00:00+00:00",
        "systems": ["vpn", "mail"],
        "urgent_call": True,
        "contact_mail": "ops@example.com",
        "manager": str(a.tech_a),
    }
    wrong = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={
            "subject": "x",
            "requester_id": str(a.requester),
            "custom": {
                "cost": "2000",
                "due": "tomorrow",
                "seen_at": "2026-10-26T10:00:00",
                "systems": ["fax"],
                "urgent_call": "yes",
                "contact_mail": "not mail",
                "manager": str(uuid.uuid4()),
                "nope": 1,
            },
        },
        headers=CONSOLE,
    )
    assert field_codes(wrong) == {
        "custom.cost": "above_maximum",
        "custom.due": "invalid_value",
        "custom.seen_at": "timezone_required",
        "custom.systems": "invalid_choice",
        "custom.urgent_call": "invalid_value",
        "custom.contact_mail": "email_not_valid",
        "custom.manager": "user_not_found",
        "custom.nope": "unknown_field",
    }
    named = (await world.fresh(a, item))["people"]
    assert str(a.tech_a) in named
    # Another tenant's person is not a person here.
    foreign = await world.call(
        "PATCH",
        f"{BASE}/{item['id']}",
        a,
        a.admin,
        json={"custom": {"manager": str(world.b.tech_a)}},
        headers={"If-Match": f'"{item["version"]}"', **CONSOLE},
    )
    assert field_codes(foreign) == {"custom.manager": "user_not_found"}


async def test_filters_on_numbers_dates_and_multi_choice(world: World) -> None:
    a = world.a
    await add_field(world, a, field_type="integer", labels={"en": "Seats"})
    await add_field(world, a, field_type="date", labels={"en": "Due"})
    await add_field(
        world,
        a,
        field_type="multi_choice",
        labels={"en": "Systems"},
        choices=choices("Mail", "VPN"),
    )
    await add_field(world, a, field_type="yes_no", labels={"en": "Urgent call"})
    small = await world.create(
        a,
        a.admin,
        custom={"seats": 2, "due": "2026-11-01", "systems": ["mail"], "urgent_call": False},
    )
    big = await world.create(
        a,
        a.admin,
        custom={"seats": 40, "due": "2026-12-01", "systems": ["mail", "vpn"], "urgent_call": True},
    )
    empty = await world.create(a, a.admin)

    async def match(node: dict[str, Any]) -> set[str]:
        return await ids(world, a, a.admin, dsl(node)) & {small["id"], big["id"], empty["id"]}

    assert await match({"field": "custom.seats", "op": "gt", "value": 10}) == {big["id"]}
    assert await match({"field": "custom.seats", "op": "between", "value": [1, 5]}) == {small["id"]}
    assert await match({"field": "custom.due", "op": "lt", "value": "2026-11-15"}) == {small["id"]}
    assert await match({"field": "custom.systems", "op": "eq", "value": "vpn"}) == {big["id"]}
    assert await match({"field": "custom.systems", "op": "in", "value": ["vpn", "mail"]}) == {
        small["id"],
        big["id"],
    }
    assert await match({"field": "custom.systems", "op": "ne", "value": "vpn"}) == {
        small["id"],
        empty["id"],
    }
    assert await match({"field": "custom.systems", "op": "is_null"}) == {empty["id"]}
    assert await match({"field": "custom.urgent_call", "op": "eq", "value": True}) == {big["id"]}
    assert await match(
        {
            "and": [
                {"field": "custom.seats", "op": "is_not_null"},
                {"field": "custom.urgent_call", "op": "eq", "value": False},
            ]
        }
    ) == {small["id"]}
    # Text search (WP-027 reads custom_text): the record keeps its custom free text.
    await add_field(world, a, field_type="text", labels={"en": "Asset tag"})
    tagged = await world.create(a, a.admin, custom={"asset_tag": "LAP-7781"})
    rows = await world.sql("SELECT custom_text FROM work_items WHERE id = $1", tagged["id"])
    assert "LAP-7781" in rows[0]["custom_text"]


async def test_edits_history_and_template_required_stays_required(world: World) -> None:
    a = world.a
    await add_field(world, a, field_type="text", labels={"en": "Room"})
    template = await new_template(
        world,
        a,
        labels={"en": "Room issue"},
        fields={"custom.room": {"shown": True, "required": True}},
    )
    item = await world.create(a, a.admin, template_id=template.json()["id"], custom={"room": "B12"})
    edited = await world.patch(a, a.admin, item, custom={"room": "B14"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["custom"] == {"room": "B14"}
    entries = await world.history(a, item)
    changes = [c for e in entries for c in e.get("changes", []) if c["field"] == "custom.room"]
    assert any(c["old"] == "B12" and c["new"] == "B14" for c in changes), entries
    emptied = await world.patch(a, a.admin, edited.json(), custom={"room": None})
    assert field_codes(emptied) == {"custom.room": "required"}
    # Other custom values and fields still save; unsent custom values stay.
    await add_field(world, a, field_type="text", labels={"en": "Desk"})
    more = await world.patch(a, a.admin, edited.json(), custom={"desk": "4"})
    assert more.json()["custom"] == {"room": "B14", "desk": "4"}


async def test_admin_changes_retire_and_reorder(world: World) -> None:
    a = world.a
    floor = await add_field(
        world, a, field_type="choice", labels={"en": "Floor"}, choices=choices("Ground", "First")
    )
    same = await add(world, a, field_type="text", labels={"en": "floor"})
    assert field_codes(same) == {"labels": "duplicate_name"}
    # Only settings.manage may write; the incidents view permission may read.
    refused = await world.call(
        "POST",
        FIELDS,
        a,
        a.tech_a,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "X"}},
        headers=CONSOLE,
    )
    assert refused.status_code == 403
    assert [f["key"] for f in await listed(world, a, a.tech_a)] == ["floor"]
    # Removing a choice keeps it, retired: old values still read.
    item = await world.create(a, a.admin, custom={"floor": "ground"})
    changed = await change(world, a, floor, choices=[{"code": "first", "labels": {"en": "First"}}])
    assert changed.status_code == 200, changed.text
    assert {c["code"]: c["retired"] for c in changed.json()["choices"]} == {
        "first": False,
        "ground": True,
    }
    new = await world.call(
        "POST",
        BASE,
        a,
        a.admin,
        json={"subject": "x", "requester_id": str(a.requester), "custom": {"floor": "ground"}},
        headers=CONSOLE,
    )
    assert field_codes(new) == {"custom.floor": "invalid_choice"}
    kept = await world.patch(a, a.admin, item, subject="Still ground")
    assert kept.status_code == 200, kept.text
    assert kept.json()["custom"] == {"floor": "ground"}
    # Type and key never change; the API refuses unknown fields.
    typed = await world.call(
        "PATCH",
        f"{FIELDS}/{floor['id']}",
        a,
        a.admin,
        json={"field_type": "text"},
        headers={"If-Match": f'"{changed.json()["version"]}"', **CONSOLE},
    )
    assert typed.status_code == 422
    # Stale version.
    stale = await change(world, a, floor, labels={"en": "Level"})
    assert stale.status_code == 409
    # Retire: no new values; restore.
    retired = await change(world, a, changed.json(), retired=True)
    assert retired.json()["retired"] is True
    refused_value = await world.patch(a, a.admin, kept.json(), custom={"floor": "first"})
    assert field_codes(refused_value) == {"custom.floor": "field_retired"}
    restored = await change(world, a, retired.json(), retired=False)
    assert restored.json()["retired"] is False
    # Reorder.
    room = await add_field(world, a, field_type="text", labels={"en": "Room"})
    order = await world.call(
        "PUT",
        f"{FIELDS}/order",
        a,
        a.admin,
        json={"entity": "incident", "ids": [room["id"], floor["id"]]},
        headers=CONSOLE,
    )
    assert order.status_code == 200, order.text
    assert [f["key"] for f in await listed(world, a)] == ["room", "floor"]
    partial = await world.call(
        "PUT",
        f"{FIELDS}/order",
        a,
        a.admin,
        json={"entity": "incident", "ids": [room["id"]]},
        headers=CONSOLE,
    )
    assert field_codes(partial) == {"ids": "order_must_list_every_value"}


async def test_req_inc_014_ac4_removing_a_field_in_use_needs_confirmation(world: World) -> None:
    a = world.a
    unused = await add_field(world, a, field_type="text", labels={"en": "Spare"})
    gone = await world.call(
        "DELETE",
        f"{FIELDS}/{unused['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{unused["version"]}"', **CONSOLE},
    )
    assert gone.status_code == 204, gone.text
    used = await add_field(world, a, field_type="text", labels={"en": "Room"})
    item = await world.create(a, a.admin, custom={"room": "B12"})
    fresh = next(f for f in await listed(world, a) if f["id"] == used["id"])
    assert fresh["in_use"] is True
    headers = {"If-Match": f'"{fresh["version"]}"', **CONSOLE}
    asked = await world.call("DELETE", f"{FIELDS}/{used['id']}", a, a.admin, headers=headers)
    assert asked.status_code == 409
    assert asked.json()["code"] == "custom_field_in_use"
    removed = await world.call(
        "DELETE", f"{FIELDS}/{used['id']}?confirm=true", a, a.admin, headers=headers
    )
    assert removed.status_code == 204, removed.text
    assert [f["key"] for f in await listed(world, a)] == []
    old = await listed(world, a, query="&include_removed=true")
    assert {f["key"]: f["removed"] for f in old} == {"spare": True, "room": True}
    # The record and its history keep the value; the key is never given out again.
    assert (await world.fresh(a, item))["custom"] == {"room": "B12"}
    again = await add_field(world, a, field_type="integer", labels={"en": "Room"})
    assert again["key"] != "room"
    edited = await world.patch(a, a.admin, await world.fresh(a, item), subject="Other edit")
    assert edited.status_code == 200, edited.text
    filtered = await world.call(
        "GET", BASE + dsl({"field": "custom.room", "op": "eq", "value": "B12"}), a, a.admin
    )
    assert filtered.status_code == 422


async def test_templates_stay_editable_after_a_field_they_use_is_removed(world: World) -> None:
    a = world.a
    room = await add_field(world, a, field_type="text", labels={"en": "Room"})
    made = await new_template(
        world,
        a,
        labels={"en": "Room issue"},
        fields={"custom.room": {"shown": True, "required": True}},
        defaults={"custom.room": "B1"},
    )
    assert made.status_code == 201, made.text
    assert made.json()["custom_fields"]["room"]["required"] is True
    gone = await world.call(
        "DELETE",
        f"{FIELDS}/{room['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{room["version"]}"', **CONSOLE},
    )
    assert gone.status_code == 204, gone.text
    # New incidents from the untouched template are not blocked by the removed field.
    early = await world.create(a, a.admin, template_id=made.json()["id"])
    assert early["custom"] == {}
    # Editing and copying work; the leftover rule and starting value go quietly.
    edited = await patch_template(world, a, made.json(), description="Still fine")
    assert edited.status_code == 200, edited.text
    renamed = await patch_template(
        world, a, edited.json(), fields={"impact_details": {"shown": True}}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["custom_fields"] == {}
    assert "custom.room" not in renamed.json()["defaults"]
    copied = await world.call(
        "POST",
        f"{BASE}/templates/{made.json()['id']}/copy",
        a,
        a.admin,
        json={"labels": {"en": "Room copy"}},
        headers=CONSOLE,
    )
    assert copied.status_code == 201, copied.text
    # A new incident from the template is not blocked by the removed required field.
    item = await world.create(a, a.admin, template_id=made.json()["id"])
    assert item["custom"] == {}


async def test_custom_fields_table_is_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    field = await add_field(world, a, field_type="text", labels={"en": "Only A"})
    assert await listed(world, b) == []
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        rows = (
            await session.execute(
                text("SELECT id FROM custom_fields WHERE id = :id"), {"id": uuid.UUID(field["id"])}
            )
        ).all()
        assert rows == []
        updated = await session.execute(
            text("UPDATE custom_fields SET sort_order = 9 WHERE id = :id"),
            {"id": uuid.UUID(field["id"])},
        )
        assert updated.rowcount == 0
    foreign = await world.call(
        "PATCH",
        f"{FIELDS}/{field['id']}",
        b,
        b.admin,
        json={"labels": {"en": "Mine"}},
        headers={"If-Match": '"1"', **CONSOLE},
    )
    assert foreign.status_code == 404
    # B's incidents know no such field.
    refused = await world.call(
        "POST",
        BASE,
        b,
        b.admin,
        json={"subject": "x", "requester_id": str(b.requester), "custom": {"only_a": "v"}},
        headers=CONSOLE,
    )
    assert field_codes(refused) == {"custom.only_a": "unknown_field"}


async def test_changes_go_through_the_outbox(world: World) -> None:
    a = world.a
    field = await add_field(world, a, field_type="text", labels={"en": "Room"})
    await change(world, a, field, help={"en": "Where it happens"})
    kinds = [(e.event_type, e.payload["change"]) for e in await envelopes(world, field["id"])]
    assert kinds == [
        ("metadata.custom_field.changed", "created"),
        ("metadata.custom_field.changed", "updated"),
    ]
    payload = (await envelopes(world, field["id"]))[-1].payload
    assert set(payload) >= {"custom_field_id", "entity", "key", "changed_fields"}


async def test_req_inc_014_ac2_index_requested_then_built_by_the_job(world: World) -> None:
    a, b = world.a, world.b
    field = await add_field(world, a, field_type="decimal", labels={"en": "Cost"})
    twin = await add_field(world, b, field_type="decimal", labels={"en": "Cost"})
    requested = await world.call(
        "POST",
        f"{FIELDS}/{field['id']}/index",
        a,
        a.admin,
        headers={"If-Match": f'"{field["version"]}"', **CONSOLE},
    )
    assert requested.status_code == 200, requested.text
    assert requested.json()["index_state"] == "requested"
    await world.call(
        "POST",
        f"{FIELDS}/{twin['id']}/index",
        b,
        b.admin,
        headers={"If-Match": f'"{twin["version"]}"', **CONSOLE},
    )
    outcome = await custom_field_indexes.run(world.db.migrator_url)
    assert outcome == {"active": 2, "failed": 0}
    assert [f["index_state"] for f in await listed(world, a)] == ["active"]
    assert [f["index_state"] for f in await listed(world, b)] == ["active"]
    rows = await world.sql(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_cf_incident_decimal_cost'"
    )
    assert len(rows) == 1
    # The planner can use it for the very filter lists send (same expression text).
    item = await world.create(a, a.admin, custom={"cost": 5})
    found = await ids(world, a, a.admin, dsl({"field": "custom.cost", "op": "gte", "value": 5}))
    assert item["id"] in found
    # Nothing left to do on the next run.
    assert await custom_field_indexes.run(world.db.migrator_url) == {"active": 0, "failed": 0}


async def test_defaults_fill_new_records_only(world: World) -> None:
    a = world.a
    await add_field(
        world,
        a,
        field_type="choice",
        labels={"en": "Source"},
        choices=choices("Phone", "Walk in"),
        default="phone",
    )
    made = await world.create(a, a.admin)
    assert made["custom"] == {"source": "phone"}
    chosen = await world.create(a, a.admin, custom={"source": "walk_in"})
    assert chosen["custom"] == {"source": "walk_in"}
    no_default = await add(
        world, a, field_type="person", labels={"en": "Boss"}, default=str(a.admin)
    )
    assert field_codes(no_default) == {"default": "no_default_allowed"}
    # A template's custom rules stay valid after the tenant's fields change.
    standard = (await world.call("GET", f"{BASE}/templates", a, a.admin)).json()
    assert standard
    updated = await patch_template(world, a, standard[0], fields={"custom.source": {"shown": True}})
    assert updated.status_code == 200, updated.text
