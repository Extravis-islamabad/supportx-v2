"""The CMDB foundation over HTTP (WP-053 S1; REQ-CMDB-001..005, 024's write side, 031; 0173).

Real PostgreSQL and Valkey on the incident world (two organisations, each with sites, groups,
technicians and requesters; the admin holds everything). Every organisation is new for each test,
so nothing here touches dev data (rule 5h).
"""

import json
import time
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules.cmdb.service.person_data import PORT
from app.modules.cmdb.service.realtime import ROUTES
from app.modules.identity_access.service.person_data import missing_ports
from app.shared.events import EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_assets_api import _add as add_asset
from tests.db.test_assets_api import _product
from tests.db.test_incidents_api import Org, World, problem, role
from tests.db.test_knowledge_api import _match, _new
from tooling import timing

pytestmark = MODULE_LOOP

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

BASE = "/cmdb"
TABLES = ("cmdb_ci_types", "cmdb_ci_states", "cmdb_cis", "cmdb_ci_versions", "cmdb_settings")


async def _types(world: World, org: Org) -> dict[str, dict[str, Any]]:
    found = await world.call("GET", f"{BASE}/ci-types", org, org.admin)
    assert found.status_code == 200, found.text
    return {t["api_name"]: t for t in found.json()["items"]}


async def _states(world: World, org: Org) -> dict[str, dict[str, Any]]:
    found = await world.call("GET", f"{BASE}/ci-states", org, org.admin)
    assert found.status_code == 200, found.text
    return {s["api_name"]: s for s in found.json()["items"]}


async def _ci(
    world: World,
    org: Org,
    name: str,
    type_code: str = "server",
    user: uuid.UUID | None = None,
    **extra: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    types = await _types(world, org)
    body = {"type_id": types[type_code]["id"], "name": name, **extra}
    return await world.call(
        "POST", f"{BASE}/cis", org, user or org.admin, json=body, headers=_new()
    )


async def _type(world: World, org: Org, api_name: str, parent: str | None) -> httpx.Response:
    types = await _types(world, org)
    body = {
        "api_name": api_name,
        "names": {"en": api_name.title(), "ar": "نوع", "ur": "قسم"},
        "parent_id": types[parent]["id"] if parent else None,
    }
    return await world.call("POST", f"{BASE}/ci-types", org, org.admin, json=body, headers=_new())


# --- tenant isolation (rule a) --------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
async def test_cmdb_tables_are_isolated_by_rls(world: World, table: str) -> None:
    a, b = world.a, world.b
    made = await _ci(world, a, "Alpha web 1")
    assert made.status_code == 201, made.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() > 0  # noqa: S608 - fixed table names
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert seen.scalar_one() == 0
        if table != "cmdb_ci_versions":  # insert-only: its own test below
            changed = await session.execute(
                text(f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
                {"a": a.tenant},
            )
            assert changed.rowcount == 0
    # Over HTTP too: B never finds A's CI.
    other = await world.call("GET", f"{BASE}/cis/{made.json()['id']}", b, b.admin)
    assert problem(other) == (404, "cmdb_ci_not_found")


async def test_tenant_b_cannot_write_a_ci_for_tenant_a(world: World) -> None:
    a = world.a
    types = await _types(world, a)
    states = await _states(world, a)
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO cmdb_cis (id, tenant_id, display_id, type_id, state_id, name) "
                    "VALUES (:i, :t, 'CI-999', :ty, :st, 'Theirs')"
                ),
                {
                    "i": uuid.uuid4(),
                    "t": a.tenant,
                    "ty": types["server"]["id"],
                    "st": states["in_use"]["id"],
                },
            )


async def test_versions_are_insert_only_for_the_app(world: World) -> None:
    made = await _ci(world, world.a, "Snapshot only")
    assert made.status_code == 201, made.text
    for statement in (
        "UPDATE cmdb_ci_versions SET version = version",
        "DELETE FROM cmdb_ci_versions",
    ):
        with pytest.raises(DBAPIError):
            async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
                await session.execute(text(statement))


# --- types (REQ-CMDB-001) -----------------------------------------------------------------------


async def test_built_in_types_and_states_are_made_once(world: World) -> None:
    a = world.a
    types = await _types(world, a)
    assert {"server", "hardware", "business_service", "database"} <= set(types)
    assert types["server"]["parent_id"] == types["hardware"]["id"]
    assert all(t["built_in"] for t in types.values())
    states = await _states(world, a)
    assert states["retired"]["category"] == "end_of_life"
    again = await _types(world, a)
    assert len(again) == len(types)


async def test_a_type_in_use_cannot_be_deleted(world: World) -> None:
    a = world.a
    made = await _type(world, a, "kiosk", "hardware")
    assert made.status_code == 201, made.text
    ci = await _ci(world, a, "Lobby kiosk", "kiosk")
    assert ci.status_code == 201, ci.text
    refused = await world.call(
        "DELETE",
        f"{BASE}/ci-types/{made.json()['id']}",
        a,
        a.admin,
        headers=_match(made.json()["version"]),
    )
    assert problem(refused) == (409, "cmdb_ci_type_in_use")
    assert refused.json()["params"]["ci_count"] == 1
    built_in = (await _types(world, a))["printer"]
    locked = await world.call(
        "DELETE",
        f"{BASE}/ci-types/{built_in['id']}",
        a,
        a.admin,
        headers=_match(built_in["version"]),
    )
    assert problem(locked) == (409, "cmdb_built_in_locked")
    loop = await world.call(
        "PATCH",
        f"{BASE}/ci-types/{(await _types(world, a))['hardware']['id']}",
        a,
        a.admin,
        json={"parent_id": made.json()["id"]},
        headers=_match((await _types(world, a))["hardware"]["version"]),
    )
    assert problem(loop)[0] in {409, 422}  # a built-in type keeps its place


async def test_configuration_changes_are_audited(world: World) -> None:
    a = world.a
    assert (await _type(world, a, "audited_type", None)).status_code == 201
    rows = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1 AND action LIKE 'cmdb.%'", a.tenant
    )
    assert "cmdb.ci_type_created" in {r["action"] for r in rows}
    tech = await _type(world, a, "not_mine", None)
    assert tech.status_code == 201
    denied = await world.call(
        "POST",
        f"{BASE}/ci-types",
        a,
        a.tech_a,
        json={"api_name": "tech_type", "names": {"en": "Tech"}},
        headers=_new(),
    )
    assert denied.status_code == 403


# --- CIs: create, edit, version, history (REQ-CMDB-002, 003, 024) ---------------------------------


async def test_create_edit_version_history_and_snapshots(world: World) -> None:
    a = world.a
    made = await _ci(world, a, "Mail server", business_impact="high", site_id=str(a.s1))
    assert made.status_code == 201, made.text
    ci = made.json()
    assert ci["display_id"].startswith("CI-")
    assert ci["source"] == "manual"
    assert made.headers["ETag"] == '"1"'
    edited = await world.call(
        "PATCH",
        f"{BASE}/cis/{ci['id']}",
        a,
        a.admin,
        json={"name": "Mail server 1", "criticality": "critical"},
        headers=_match(1),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2
    stale = await world.call(
        "PATCH",
        f"{BASE}/cis/{ci['id']}",
        a,
        a.admin,
        json={"name": "Lost update"},
        headers=_match(1),
    )
    assert problem(stale) == (409, "version_conflict")
    history = (await world.call("GET", f"{BASE}/cis/{ci['id']}/history", a, a.admin)).json()
    assert [e["kind"] for e in history["items"]] == ["updated", "created"]
    assert {c["field"] for c in history["items"][0]["changes"]} == {"name", "criticality"}
    versions = await world.sql(
        "SELECT version, snapshot FROM cmdb_ci_versions WHERE tenant_id = $1 AND ci_id = $2"
        " ORDER BY version",
        a.tenant,
        uuid.UUID(ci["id"]),
    )
    assert [v["version"] for v in versions] == [1, 2]
    assert json.loads(versions[1]["snapshot"])["name"] == "Mail server 1"
    events = await world.sql(
        "SELECT event_type, envelope FROM outbox_events WHERE aggregate_id = $1 ORDER BY id",
        ci["id"],
    )
    assert [e["event_type"] for e in events] == ["cmdb.ci.created", "cmdb.ci.updated"]
    assert "Mail server" not in json.dumps([e["envelope"] for e in events])  # IDs and codes only


async def test_create_is_idempotent(world: World) -> None:
    a = world.a
    types = await _types(world, a)
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = {"type_id": types["server"]["id"], "name": "Once only"}
    first = await world.call("POST", f"{BASE}/cis", a, a.admin, json=body, headers=key)
    again = await world.call("POST", f"{BASE}/cis", a, a.admin, json=body, headers=key)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    rows = await world.sql(
        "SELECT count(*) AS n FROM cmdb_cis WHERE tenant_id = $1 AND name = 'Once only'", a.tenant
    )
    assert rows[0]["n"] == 1


async def test_copy_change_type_delete_and_restore(world: World) -> None:
    a = world.a
    made = await _type(world, a, "appliance", "hardware")
    assert made.status_code == 201, made.text
    ci = (await _ci(world, a, "Firewall", "appliance", description="Edge firewall")).json()
    copy = await world.call("POST", f"{BASE}/cis/{ci['id']}/copy", a, a.admin, headers=_new())
    assert copy.status_code == 201, copy.text
    assert copy.json()["id"] != ci["id"]
    assert copy.json()["description"] == "Edge firewall"
    server = (await _types(world, a))["server"]
    moved = await world.call(
        "POST",
        f"{BASE}/cis/{ci['id']}/change-type",
        a,
        a.admin,
        json={"type_id": server["id"]},
        headers=_match(ci["version"]),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["type_id"] == server["id"]
    gone = await world.call(
        "DELETE", f"{BASE}/cis/{ci['id']}", a, a.admin, headers=_match(moved.json()["version"])
    )
    assert gone.status_code == 204, gone.text
    assert (await world.call("GET", f"{BASE}/cis/{ci['id']}", a, a.admin)).status_code == 404
    trash = (await world.call("GET", f"{BASE}/cis/trash", a, a.admin)).json()["items"]
    assert ci["id"] in {t["id"] for t in trash}
    back = await world.call(
        "POST",
        f"{BASE}/cis/{ci['id']}/restore",
        a,
        a.admin,
        headers=_match(moved.json()["version"] + 1),
    )
    assert back.status_code == 200, back.text
    assert back.json()["deleted_at"] is None


async def test_scopes_and_rights(world: World) -> None:
    """cmdb.view at site scope sees only its site's CIs; cmdb.manage covers every write."""
    a = world.a
    at_s1 = (await _ci(world, a, "S1 router", "network_device", site_id=str(a.s1))).json()
    at_s2 = (await _ci(world, a, "S2 router", "network_device", site_id=str(a.s2))).json()
    viewer = await role(world, a, "Site CMDB viewer", [("cmdb.view", "site")])
    assigned = await world.call("PUT", f"/users/{a.requester}/roles/{viewer}", a, a.admin)
    assert assigned.status_code == 204, assigned.text
    seen = await world.call("GET", f"{BASE}/cis", a, a.requester)
    assert seen.status_code == 200, seen.text
    ids = {c["id"] for c in seen.json()["items"]}
    assert at_s1["id"] in ids
    assert at_s2["id"] not in ids
    hidden = await world.call("GET", f"{BASE}/cis/{at_s2['id']}", a, a.requester)
    assert problem(hidden) == (404, "cmdb_ci_not_found")
    no_write = await world.call(
        "PATCH",
        f"{BASE}/cis/{at_s1['id']}",
        a,
        a.requester,
        json={"name": "x"},
        headers=_match(1),
    )
    assert no_write.status_code == 403
    manager = await role(
        world, a, "Old CMDB manager", [("cmdb.view", "all"), ("cmdb.manage", "all")]
    )
    assert (
        await world.call("PUT", f"/users/{a.tech_b}/roles/{manager}", a, a.admin)
    ).status_code == 204
    by_manage = await _ci(world, a, "Made with manage", user=a.tech_b)
    assert by_manage.status_code == 201, by_manage.text


async def test_group_and_own_scopes_see_only_theirs(world: World) -> None:
    """D-172: own groups (owning or managing group) and own (owner) on plain roles."""
    a = world.a
    owned_by_ga = (await _ci(world, a, "GA box", owner_group_id=str(a.ga))).json()
    managed_by_ga = (await _ci(world, a, "GA managed", managed_by_group_id=str(a.ga))).json()
    gb_only = (await _ci(world, a, "GB box", owner_group_id=str(a.gb))).json()
    mine = (await _ci(world, a, "Requester's box", owner_user_id=str(a.requester2))).json()
    group_role = await role(world, a, "Group CMDB viewer", [("cmdb.view", "group")])
    # A requester (no CMDB right of their own) put in GA only: technicians see all by default.
    member = await world.call(
        "PUT", f"/organization/groups/{a.ga}/members/{a.requester}", a, a.admin
    )
    assert member.status_code in {200, 204}, member.text
    given = await world.call("PUT", f"/users/{a.requester}/roles/{group_role}", a, a.admin)
    assert given.status_code == 204, given.text
    listed = await world.call("GET", f"{BASE}/cis", a, a.requester)
    seen = {c["id"] for c in listed.json()["items"]}
    assert {owned_by_ga["id"], managed_by_ga["id"]} <= seen
    assert gb_only["id"] not in seen
    other = await world.call("GET", f"{BASE}/cis/{gb_only['id']}", a, a.requester)
    assert problem(other) == (404, "cmdb_ci_not_found")
    params = {"search": "GB box"}
    picked = await world.call("GET", f"{BASE}/cis/picker", a, a.requester, params=params)
    assert picked.json()["items"] == []
    own_role = await role(world, a, "Own CMDB viewer", [("cmdb.view", "own")])
    assert (
        await world.call("PUT", f"/users/{a.requester2}/roles/{own_role}", a, a.admin)
    ).status_code == 204
    own = {
        c["id"] for c in (await world.call("GET", f"{BASE}/cis", a, a.requester2)).json()["items"]
    }
    assert own == {mine["id"]}


# --- from assets and the picker (REQ-CMDB-005, 031) -----------------------------------------------


async def test_cis_from_ten_assets(world: World) -> None:
    a = world.a
    product = await _product(world, a, "laptop", "CMDB laptop")
    assets = []
    for n in range(10):
        made = await add_asset(world, a, {"name": f"Laptop {n}", "product_id": product})
        assert made.status_code == 201, made.text
        assets.append(made.json()["id"])
    workstation = (await _types(world, a))["workstation"]
    body = {"asset_ids": [*assets, str(uuid.uuid4())], "type_id": workstation["id"]}
    made = await world.call(
        "POST", f"{BASE}/cis/from-assets", a, a.admin, json=body, headers=_new()
    )
    assert made.status_code == 201, made.text
    result = made.json()
    assert len(result["created"]) == 10
    assert {c["source"] for c in result["created"]} == {"asset_sync"}
    assert {c["name"] for c in result["created"]} == {f"Laptop {n}" for n in range(10)}
    assert [s["reason"] for s in result["skipped"]] == ["gone"]
    again = await world.call(
        "POST", f"{BASE}/cis/from-assets", a, a.admin, json=body, headers=_new()
    )
    assert again.json()["created"] == []
    assert sorted({s["reason"] for s in again.json()["skipped"]}) == ["gone", "has_ci"]


async def test_the_picker_leaves_end_of_life_out(world: World) -> None:
    a = world.a
    states = await _states(world, a)
    live = (await _ci(world, a, "Picker live box")).json()
    old = (await _ci(world, a, "Picker old box", state_id=states["retired"]["id"])).json()
    found = await world.call("GET", f"{BASE}/cis/picker", a, a.admin, params={"search": "Picker"})
    assert {c["id"] for c in found.json()["items"]} == {live["id"]}
    settings = (await world.call("GET", f"{BASE}/settings", a, a.admin)).json()
    off = await world.call(
        "PUT",
        f"{BASE}/settings",
        a,
        a.admin,
        json={"exclude_eol_from_pickers": False},
        headers=_match(settings["version"]),
    )
    assert off.status_code == 200, off.text
    found = await world.call("GET", f"{BASE}/cis/picker", a, a.admin, params={"search": "Picker"})
    assert {c["id"] for c in found.json()["items"]} == {live["id"], old["id"]}
    wild = await world.call("GET", f"{BASE}/cis/picker", a, a.admin, params={"search": "%"})
    assert wild.json()["items"] == []  # a wildcard is a character, never "everything"


async def _eol_in_pickers(world: World, org: Org, *, left_out: bool) -> None:
    settings = (await world.call("GET", f"{BASE}/settings", org, org.admin)).json()
    put = await world.call(
        "PUT",
        f"{BASE}/settings",
        org,
        org.admin,
        json={"exclude_eol_from_pickers": left_out},
        headers=_match(settings["version"]),
    )
    assert put.status_code == 200, put.text


async def test_links_follow_the_picker_and_refs_never_name_what_is_hidden(world: World) -> None:
    """Lane A's #524 review: `can_link` refuses what the picker hides; `ci_refs` is a dict."""
    from app.modules.cmdb import can_link, can_see, ci_refs  # noqa: PLC0415 - the public interface under test
    from app.modules.identity_access import subject_for  # noqa: PLC0415 - as other modules call it

    a = world.a
    states = await _states(world, a)
    assert (await _type(world, a, "link_kiosk", "hardware")).status_code == 201
    live = (await _ci(world, a, "Link live box")).json()
    old = (await _ci(world, a, "Link old box", state_id=states["retired"]["id"])).json()
    own = (await _ci(world, a, "Link kiosk", "link_kiosk")).json()
    trashed = (await _ci(world, a, "Link trashed box")).json()
    gone = await world.call(
        "DELETE", f"{BASE}/cis/{trashed['id']}", a, a.admin, headers=_match(trashed["version"])
    )
    assert gone.status_code == 204, gone.text
    ids = [uuid.UUID(x["id"]) for x in (live, old, own, trashed)]
    await _eol_in_pickers(world, a, left_out=True)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        admin = await subject_for(session, a.tenant, a.admin)
        requester = await subject_for(session, a.tenant, a.requester)
        assert await can_link(session, admin, ids[0])
        assert await can_see(session, admin, ids[1])
        assert not await can_link(session, admin, ids[1])  # end of life, left out of pickers
        assert not await can_link(session, admin, ids[3])  # in the trash
        refs = await ci_refs(session, admin, [*ids, ids[0]])
        assert list(refs) == ids  # one per ID, in the order asked
        assert (refs[ids[0]].state_category, refs[ids[0]].type_label_key) == (
            "active",
            "cmdb_ci_type.server",
        )
        assert refs[ids[1]].state_category == "end_of_life"
        assert (refs[ids[2]].type_label_key, refs[ids[2]].type_names["en"]) == (
            None,
            "Link_Kiosk",
        )
        assert (refs[ids[3]].gone, refs[ids[3]].name) == (True, None)
        seen = await ci_refs(session, requester, ids[:3])
        assert all(r.hidden and r.name is None and r.type_names == {} for r in seen.values())
        assert not await can_link(session, requester, ids[0])
    await _eol_in_pickers(world, a, left_out=False)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        admin = await subject_for(session, a.tenant, a.admin)
        assert await can_link(session, admin, ids[1])  # shown in pickers again: linkable


# --- realtime (rule c) ----------------------------------------------------------------------------


async def test_ci_events_reach_the_record_and_list_channels(world: World) -> None:
    a = world.a
    ci = (await _ci(world, a, "Live box", site_id=str(a.s1), owner_group_id=str(a.ga))).json()
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE aggregate_id = $1 ORDER BY id", ci["id"]
    )
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    channels: set[str] = set()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        for spec in ROUTES:
            if envelope.event_type in spec.event_types:
                effects = await spec.route(envelope, session)
                channels |= {p.channel.name for p in effects.publications}
                assert "Live box" not in repr(effects.publications)  # IDs, fields, version only
    t = a.tenant
    assert {
        f"t:{t}:ci:{ci['id']}",
        f"t:{t}:queue:cmdb",
        f"t:{t}:queue:cmdb.site.{a.s1}",
        f"t:{t}:queue:cmdb.group.{a.ga}",
    } <= channels


# --- erasure (ADR-052) ----------------------------------------------------------------------------


async def test_erasure_moves_owned_cis_to_the_successor(world: World) -> None:
    a = world.a
    owned = (await _ci(world, a, "Owned box", owner_user_id=str(a.tech_a))).json()
    assert "cmdb" not in missing_ports()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        first = await PORT.erase_person(
            session, a.tech_a, successor_id=a.tech_b, keep_files={}, now=_now(), cursor=None
        )
    assert first.counts == {
        "cmdb_cis_moved": 1,
        "cmdb_views_moved": 0,
        "cmdb_ci_person_fields_moved": 0,
    }
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        second = await PORT.erase_person(
            session, a.tech_a, successor_id=a.tech_b, keep_files={}, now=_now(), cursor=None
        )
    assert second.counts == {
        "cmdb_cis_moved": 0,
        "cmdb_views_moved": 0,
        "cmdb_ci_person_fields_moved": 0,
    }
    after = (await world.call("GET", f"{BASE}/cis/{owned['id']}", a, a.admin)).json()
    assert after["owner_user_id"] == str(a.tech_b)
    assert after["version"] == 2


def _now() -> Any:  # noqa: ANN401 - a datetime
    from datetime import UTC, datetime  # noqa: PLC0415 - only the erasure test needs it

    return datetime.now(UTC)


# --- volume ---------------------------------------------------------------------------------------

ROWS = timing.volume(10_000, 1_000)


async def test_the_list_stays_fast_at_volume(world: World) -> None:
    a = world.a
    types = await _types(world, a)
    states = await _states(world, a)
    await world.sql(
        "INSERT INTO cmdb_cis (id, tenant_id, display_id, type_id, state_id, name)"
        " SELECT gen_random_uuid(), $1, 'CI-V' || g, $2, $3, 'Volume ' || g"
        " FROM generate_series(1, $4) g",
        a.tenant,
        uuid.UUID(types["server"]["id"]),
        uuid.UUID(states["in_use"]["id"]),
        ROWS,
    )
    await world.sql("ANALYZE cmdb_cis")
    started = time.perf_counter()
    page = await world.call("GET", f"{BASE}/cis", a, a.admin, params={"limit": 50})
    elapsed = time.perf_counter() - started
    assert page.status_code == 200, page.text
    assert len(page.json()["items"]) == 50
    assert elapsed < 2.0, f"first page took {elapsed:.2f}s at {ROWS} rows"
    by_type = await world.call(
        "GET", f"{BASE}/cis", a, a.admin, params={"limit": 50, "type_tree": types["hardware"]["id"]}
    )
    assert by_type.status_code == 200
    assert len(by_type.json()["items"]) == 50
