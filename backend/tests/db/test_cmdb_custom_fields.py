"""CI custom fields scoped to a CI type subtree, over HTTP (0175 part 2; WP-053).

The CMDB registers its type tree with metadata, so a CI custom field may belong to one CI type and
every type below it (plans/metadata-type-subtree-design-lane-b.md §4, lane A's §10 notes):

- a CI takes the fields of its type and the types above it; a sibling branch's field is unknown;
- moving a CI to another type previews the values it would drop, refuses without
  `confirm_dropped_fields`, and then writes history naming the fields only, never their values;
- moving a type under a new parent is refused (and rolled back) when CIs below it would lose
  values; metadata's `forget_lineage` makes the same transaction see the new tree;
- a type that custom fields belong to cannot be deleted;
- ADR-047: a hidden CI field never reaches the record, its history or its versions; a masked one
  is named apart; a read-only one cannot be changed;
- the mentions port finds CI custom text: redacted on the CI by an ordinary save; in a saved
  snapshot it is listed but refused (no definer for snapshot custom values yet), never skipped.

Real PostgreSQL and Valkey on the incident world; every organisation is new (rule 5h).
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules import metadata
from app.modules.cmdb.infra.models import CiType
from app.modules.cmdb.service.person_data import PORT
from app.modules.metadata.service import type_trees
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_api import _ci, _now, _type, _types
from tests.db.test_cmdb_mentions import MARKER, _on, _patch, _redact, _snapshots
from tests.db.test_incidents_api import Org, World, problem, role
from tests.db.test_knowledge_api import _match, _new
from tests.db.test_person_erasure_api import _name, _request
from tests.db.test_person_erasure_mentions import _build, _mentions

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

BASE = "/cmdb"
FIELDS = "/custom-fields"


async def _field(
    world: World,
    org: Org,
    name: str,
    type_code: str | None,
    field_type: str = "text",
) -> dict[str, Any]:
    """A CI custom field, scoped to a type by its code (None: every CI type)."""
    types = await _types(world, org)
    body: dict[str, Any] = {"entity": "ci", "field_type": field_type, "labels": {"en": name}}
    if type_code is not None:
        body["scope_type_id"] = types[type_code]["id"]
    made = await world.call("POST", FIELDS, org, org.admin, json=body, headers=_new())
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _made(world: World, org: Org, name: str, type_code: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    made = await _ci(world, org, name, type_code, **extra)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _get(world: World, org: Org, ci_id: str, user: uuid.UUID | None = None) -> Any:  # noqa: ANN401 - httpx response
    return await world.call("GET", f"{BASE}/cis/{ci_id}", org, user or org.admin)


async def _history(world: World, org: Org, ci_id: str, user: uuid.UUID | None = None) -> Any:  # noqa: ANN401 - httpx response
    return await world.call("GET", f"{BASE}/cis/{ci_id}/history", org, user or org.admin)


async def _change_type(
    world: World, org: Org, ci: dict[str, Any], type_id: str, *, confirm: bool
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "POST",
        f"{BASE}/cis/{ci['id']}/change-type",
        org,
        org.admin,
        json={"type_id": type_id, "confirm_dropped_fields": confirm},
        headers=_match(ci["version"]),
    )


# --- values follow the type tree ------------------------------------------------------------------


async def test_a_ci_takes_its_types_fields_and_refuses_a_siblings(world: World) -> None:
    a = world.a
    rack = (await _field(world, a, "Rack position", "hardware"))["key"]
    server = await _made(world, a, "Scoped server", "server", custom={rack: "R4-U12"})
    assert server["custom"] == {rack: "R4-U12"}
    # An application is on another branch: the hardware field is unknown to it.
    refused = await _ci(world, a, "Scoped app", "application", custom={rack: "R1"})
    assert refused.status_code == 422, refused.text
    assert "unknown_field" in {e["code"] for e in refused.json()["errors"]}
    # The type's fields, inherited ones marked.
    types = await _types(world, a)
    listed = await world.call(
        "GET", f"{FIELDS}?entity=ci&type_id={types['server']['id']}", a, a.admin
    )
    assert listed.status_code == 200, listed.text
    assert {f["key"]: f["inherited"] for f in listed.json()}[rack] is True
    # History names the custom field by key, one line per value.
    history = await _history(world, a, server["id"])
    fields = [c["field"] for e in history.json()["items"] for c in e["changes"]]
    assert f"custom.{rack}" in fields


async def test_a_type_change_previews_drops_and_records_keys_only(world: World) -> None:
    a = world.a
    port = (await _field(world, a, "Port count", "network_device", "integer"))["key"]
    secret = "Closet-B-9931"
    note = (await _field(world, a, "Closet note", "network_device"))["key"]
    switch = await _made(
        world, a, "Moving switch", "network_device", custom={port: 48, note: secret}
    )
    types = await _types(world, a)
    target = types["server"]["id"]

    preview = await world.call(
        "GET",
        f"{BASE}/cis/{switch['id']}/change-type-preview",
        a,
        a.admin,
        params={"type_id": target},
    )
    assert preview.status_code == 200, preview.text
    assert sorted(d["key"] for d in preview.json()["dropped"]) == sorted([port, note])
    assert preview.json()["blocked"] is False
    assert secret not in preview.text  # names only

    unconfirmed = await _change_type(world, a, switch, target, confirm=False)
    assert problem(unconfirmed) == (409, "cmdb_ci_type_change_drops_fields")
    assert unconfirmed.json()["params"]["field_count"] == 2
    unchanged = (await _get(world, a, switch["id"])).json()
    assert unchanged["custom"] == {port: 48, note: secret}

    moved = await _change_type(world, a, unchanged, target, confirm=True)
    assert moved.status_code == 200, moved.text
    assert moved.json()["type_id"] == target
    assert moved.json()["custom"] == {}
    history = (await _history(world, a, switch["id"])).json()
    last = history["items"][0]
    dropped = [c for c in last["changes"] if c["field"] == "fields_dropped"]
    assert dropped == [
        {
            "field": "fields_dropped",
            "old": None,
            "new": sorted([f"custom.{port}", f"custom.{note}"]),
        }
    ]
    assert not [c for c in last["changes"] if c["field"].startswith("custom.")]
    assert secret not in json.dumps(last)  # the change never carries a dropped value


# --- the type tree changes ------------------------------------------------------------------------


async def test_moving_a_type_that_would_drop_values_is_refused(world: World) -> None:
    a = world.a
    racks = await _type(world, a, "rack_gear", "hardware")
    assert racks.status_code == 201, racks.text
    pdus = await _type(world, a, "rack_pdu", "rack_gear")
    assert pdus.status_code == 201, pdus.text
    outlets = (await _field(world, a, "Outlets", "rack_gear", "integer"))["key"]
    await _made(world, a, "PDU 1", "rack_pdu", custom={outlets: 24})
    types = await _types(world, a)
    pdu = types["rack_pdu"]
    moved = await world.call(
        "PATCH",
        f"{BASE}/ci-types/{pdu['id']}",
        a,
        a.admin,
        json={"parent_id": types["application"]["id"]},
        headers=_match(pdu["version"]),
    )
    assert problem(moved) == (409, "cmdb_ci_type_move_drops_fields")
    assert moved.json()["params"]["ci_count"] == 1
    assert (await _types(world, a))["rack_pdu"]["parent_id"] == types["rack_gear"]["id"]
    # Under a type that still has the field (a new one below rack gear): allowed.
    shelves = await _type(world, a, "rack_shelf", "rack_gear")
    assert shelves.status_code == 201, shelves.text
    fresh = (await _types(world, a))["rack_pdu"]
    allowed = await world.call(
        "PATCH",
        f"{BASE}/ci-types/{fresh['id']}",
        a,
        a.admin,
        json={"parent_id": shelves.json()["id"]},
        headers=_match(fresh["version"]),
    )
    assert allowed.status_code == 200, allowed.text


async def test_forget_lineage_makes_the_same_transaction_see_a_move(world: World) -> None:
    a = world.a
    assert (await _type(world, a, "lineage_top", "hardware")).status_code == 201
    assert (await _type(world, a, "lineage_leaf", "lineage_top")).status_code == 201
    types = await _types(world, a)
    leaf = uuid.UUID(types["lineage_leaf"]["id"])
    top = uuid.UUID(types["lineage_top"]["id"])
    app = uuid.UUID(types["application"]["id"])
    entity = metadata.CustomFieldEntity.CI
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        before = await type_trees.lineage(session, entity, leaf)
        assert before is not None
        assert before[:2] == [leaf, top]
        row = await session.scalar(select(CiType).where(CiType.id == leaf))
        assert row is not None
        row.parent_id = app
        await session.flush()
        # Read once per transaction: still the old tree until it is forgotten.
        assert await type_trees.lineage(session, entity, leaf) == before
        metadata.forget_lineage(session, entity)
        assert await type_trees.lineage(session, entity, leaf) == [leaf, app]
        await session.rollback()  # nothing kept: the type stays where it was


async def test_a_type_with_fields_cannot_be_deleted(world: World) -> None:
    a = world.a
    made = await _type(world, a, "fielded_type", "hardware")
    assert made.status_code == 201, made.text
    await _field(world, a, "Fielded", "fielded_type")
    gone = await world.call(
        "DELETE",
        f"{BASE}/ci-types/{made.json()['id']}",
        a,
        a.admin,
        headers=_match(made.json()["version"]),
    )
    assert problem(gone) == (409, "cmdb_ci_type_has_fields")
    assert gone.json()["params"]["field_count"] == 1


# --- field access (ADR-047) -----------------------------------------------------------------------


async def _role_id(world: World, org: Org, key: str) -> uuid.UUID:
    roles = (await world.call("GET", "/roles", org, org.admin)).json()
    return uuid.UUID(next(r["id"] for r in roles if r["key"] == key))


async def _rule(world: World, org: Org, role_id: uuid.UUID, field: str, mode: str) -> None:
    made = await world.call(
        "POST",
        "/field-access/rules",
        org,
        org.admin,
        json={"role_id": str(role_id), "record_type": "ci", "field": field, "mode": mode},
        headers=_new(),
    )
    assert made.status_code == 201, made.text


async def test_withheld_ci_fields_stay_out_of_record_history_and_versions(world: World) -> None:
    a = world.a
    salary = "Band-7-Secret"
    hidden = (await _field(world, a, "Cost centre code", None))["key"]
    masked = (await _field(world, a, "Licence key", None))["key"]
    shown = (await _field(world, a, "Rack row", None))["key"]
    ci = await _made(
        world,
        a,
        "Access server",
        "server",
        custom={hidden: salary, masked: "LK-123", shown: "Row 3"},
    )
    ci = await _patch(world, a, ci, custom={hidden: f"{salary}-2", shown: "Row 4"})
    # requester2 sees every CI through a custom role; both their roles carry the rules (a field
    # is clear for a person while any of their roles has no rule).
    viewer = await role(world, a, "CI custom reader", [("cmdb.view", "all"), ("cmdb.edit", "all")])
    assigned = await world.call("PUT", f"/users/{a.requester2}/roles/{viewer}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    for role_id in (viewer, await _role_id(world, a, "requester")):
        await _rule(world, a, role_id, f"custom.{hidden}", "hidden")
        await _rule(world, a, role_id, f"custom.{masked}", "masked")

    record = await _get(world, a, ci["id"], a.requester2)
    assert record.status_code == 200, record.text
    body = record.json()
    assert body["custom"] == {shown: "Row 4"}
    assert body["masked_fields"] == [f"custom.{masked}"]
    assert set(body["read_only_fields"]) == {f"custom.{hidden}", f"custom.{masked}"}
    assert salary not in record.text
    assert "LK-123" not in record.text

    history = await _history(world, a, ci["id"], a.requester2)
    assert history.status_code == 200, history.text
    lines = [c for e in history.json()["items"] for c in e["changes"]]
    assert not [c for c in lines if c["field"] == f"custom.{hidden}"]
    assert [c["new"] for c in lines if c["field"] == f"custom.{masked}"] == [{"masked": True}]
    assert salary not in history.text
    assert "LK-123" not in history.text

    compared = await world.call(
        "GET",
        f"{BASE}/cis/{ci['id']}/compare",
        a,
        a.requester2,
        params={"from": 1, "to": ci["version"]},
    )
    assert compared.status_code == 200, compared.text
    assert [c["field"] for c in compared.json()["attributes"]] == [f"custom.{shown}"]
    assert compared.json()["to_version"]["masked_fields"] == [f"custom.{masked}"]
    assert salary not in compared.text
    assert "LK-123" not in compared.text
    # The admin (no rule on their role) still reads both versions' values.
    full = await world.call(
        "GET",
        f"{BASE}/cis/{ci['id']}/compare",
        a,
        a.admin,
        params={"from": 1, "to": ci["version"]},
    )
    assert {c["field"] for c in full.json()["attributes"]} == {
        f"custom.{hidden}",
        f"custom.{shown}",
    }

    # A field under a rule is read-only for them: a change is refused, nothing saved.
    current = (await _get(world, a, ci["id"])).json()
    locked = await world.call(
        "PATCH",
        f"{BASE}/cis/{ci['id']}",
        a,
        a.requester2,
        json={"custom": {masked: "LK-999"}},
        headers=_match(current["version"]),
    )
    assert problem(locked) == (403, "field_read_only")
    assert (await _get(world, a, ci["id"])).json()["custom"][masked] == "LK-123"


# --- erasure: custom text in the mentions port ---------------------------------------------------


async def test_ci_custom_text_is_found_and_redacted_now_and_in_snapshots(world: World) -> None:
    a = world.a
    name = await _name(world, a, a.tech_b)
    note = (await _field(world, a, "Contact note", None))["key"]
    ci = await _made(world, a, "Contact server", "server", custom={note: f"Ask {name} first"})
    ci = await _patch(world, a, ci, custom={note: f"Ask {name} or the desk"})

    asked = await _request(world, a, a.admin, a.tech_b, successor_id=str(a.lead))
    assert asked.status_code == 201, asked.text
    erasure = dict(asked.json())
    await _build(world, a)
    page = await _mentions(world, a, erasure)
    assert name not in json.dumps(page)  # places, never text
    field = f"custom.{note}"
    now = [m for m in _on(page, "ci", field) if m["record_id"] == ci["id"]]
    assert len(now) == 1
    versions = {str(s["id"]) for s in await _snapshots(world, a, ci["id"])}
    old = [m for m in _on(page, "ci_version", field) if m["record_id"] in versions]
    assert old, "a snapshot's custom text is listed, never skipped"

    # A snapshot's custom text goes through 0181's bound definer: the matched stretch only.
    redacted = await _redact(world, a, erasure, [m["id"] for m in old])
    assert redacted.status_code == 200, redacted.text
    for snap in await _snapshots(world, a, ci["id"]):
        held = (snap["snapshot"].get("custom") or {}).get(note)
        assert held is None or name not in held
    first = (await _snapshots(world, a, ci["id"]))[0]["snapshot"]["custom"][note]
    assert first == f"Ask {MARKER} first"  # nothing but the stretch changed

    done = await _redact(world, a, erasure, [now[0]["id"]])
    assert done.status_code == 200, done.text
    after = (await _get(world, a, ci["id"])).json()
    assert name not in after["custom"][note]
    assert MARKER in after["custom"][note]
    history = (await _history(world, a, ci["id"])).json()
    redaction = history["items"][0]
    assert redaction["reason"] == "erasure_redaction"
    assert redaction["changes"] == [{"field": field, "old": None, "new": None}]


async def test_the_snapshot_custom_definer_is_bound_and_takes_only_a_pure_redaction(
    world: World,
) -> None:
    """0181's `cmdb_redact_version_custom`: the mention decides the key; a pure redaction only."""
    a, b = world.a, world.b
    name = await _name(world, a, a.tech_c)
    note = (await _field(world, a, "Handover note", None))["key"]
    ci = await _made(world, a, "Handover box", "server", custom={note: f"Keys with {name}"})
    ci = await _patch(world, a, ci, custom={note: "Keys at the desk"})
    asked = await _request(world, a, a.admin, a.tech_c, successor_id=str(a.lead))
    assert asked.status_code == 201, asked.text
    erasure = dict(asked.json())
    await _build(world, a)
    field = f"custom.{note}"
    (old,) = [
        m
        for m in _on(await _mentions(world, a, erasure), "ci_version", field)
        if m["record_id"] in {str(s["id"]) for s in await _snapshots(world, a, ci["id"])}
    ]
    call = text("SELECT cmdb_redact_version_custom(:m, :v)")
    mention = uuid.UUID(old["id"])

    # Not redacted yet: nothing is written.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await session.scalar(call, {"m": mention, "v": f"Keys with {MARKER}"}) is False
    # Another tenant's session cannot reach the mention.
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        assert await session.scalar(call, {"m": mention, "v": f"Keys with {MARKER}"}) is False
    await world.sql(
        "UPDATE person_erasure_mentions SET state = 'redacted', redacted_at = now(),"
        " redacted_by = $3 WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        mention,
        a.admin,
    )
    # Not a pure redaction: refused, nothing written.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        with pytest.raises(DBAPIError, match="marker in place"):
            await session.scalar(call, {"m": mention, "v": "Something else"})
    snap_id = uuid.UUID(old["record_id"])
    before = await world.sql(
        "SELECT snapshot FROM cmdb_ci_versions WHERE tenant_id = $1 AND id = $2", a.tenant, snap_id
    )
    assert json.loads(before[0]["snapshot"])["custom"][note] == f"Keys with {name}"
    # The pure redaction writes that one key, and a second call changes nothing.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await session.scalar(call, {"m": mention, "v": f"Keys with {MARKER}"}) is True
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await session.scalar(call, {"m": mention, "v": f"Keys with {MARKER}"}) is False
    written = json.loads(
        (
            await world.sql(
                "SELECT snapshot FROM cmdb_ci_versions WHERE tenant_id = $1 AND id = $2",
                a.tenant,
                snap_id,
            )
        )[0]["snapshot"]
    )
    assert written["custom"][note] == f"Keys with {MARKER}"
    assert written["name"] == json.loads(before[0]["snapshot"])["name"]
    # A missing or non-text value is never written either (as 0176 for a missing old text).
    await world.sql(
        "UPDATE cmdb_ci_versions SET snapshot = jsonb_set(snapshot, ARRAY['custom', $3], '42')"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        snap_id,
        note,
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        with pytest.raises(DBAPIError, match="marker in place"):
            await session.scalar(call, {"m": mention, "v": MARKER})


async def test_erasure_moves_person_fields_to_the_successor(world: World) -> None:
    """cmdb's erasure port: a person-type custom value naming the person moves (0175 part 2)."""
    a = world.a
    contact = (await _field(world, a, "On-call contact", None, "person"))["key"]
    ci = await _made(world, a, "Paged box", "server", custom={contact: str(a.requester2)})
    other = await _made(world, a, "Other box", "server", custom={contact: str(a.lead)})
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        first = await PORT.erase_person(
            session, a.requester2, successor_id=a.tech_a, keep_files={}, now=_now(), cursor=None
        )
    assert first.counts["cmdb_ci_person_fields_moved"] == 1
    assert first.cursor is None
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        second = await PORT.erase_person(
            session, a.requester2, successor_id=a.tech_a, keep_files={}, now=_now(), cursor=None
        )
    assert second.counts["cmdb_ci_person_fields_moved"] == 0  # idempotent
    after = (await _get(world, a, ci["id"])).json()
    assert after["custom"][contact] == str(a.tech_a)
    assert after["version"] == ci["version"] + 1
    assert (await _get(world, a, other["id"])).json()["custom"][contact] == str(a.lead)
    history = (await _history(world, a, ci["id"])).json()
    assert history["items"][0]["changes"][0]["field"] == f"custom.{contact}"
    # The snapshot of the new version holds the successor; older snapshots keep the old ID.
    snaps = await _snapshots(world, a, ci["id"])
    assert snaps[-1]["snapshot"]["custom"][contact] == str(a.tech_a)
    assert snaps[0]["snapshot"]["custom"][contact] == str(a.requester2)
