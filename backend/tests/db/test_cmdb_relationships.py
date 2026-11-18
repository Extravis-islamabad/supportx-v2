"""CMDB relationships, the map, business views and versions over HTTP (WP-053 S2; 0180).

REQ-CMDB-006..009 and 024's view side, with lane C's conditions 1 to 4: edit rights on both ends
of a link, restricted placeholders that never carry a CI's ID, the reader's current rights in
"as of" and compare, and a business view seen through the viewer's own rights.

Real PostgreSQL and Valkey on the incident world (two organisations; the admin holds
everything). Every organisation is new for the module, so nothing here touches dev data
(rule 5h).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.cmdb.service.person_data import PORT
from app.modules.cmdb.service.realtime import ROUTES
from app.shared.events import EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_api import _ci, _type, _types
from tests.db.test_incidents_api import Org, World, field_codes, problem, role
from tests.db.test_knowledge_api import _match, _new

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixture, re-used

BASE = "/cmdb"
TABLES = (
    "cmdb_relationship_types",
    "cmdb_relationship_type_rules",
    "cmdb_relationships",
    "cmdb_business_views",
)


async def _rel_types(world: World, org: Org) -> dict[str, dict[str, Any]]:
    found = await world.call("GET", f"{BASE}/relationship-types", org, org.admin)
    assert found.status_code == 200, found.text
    return {t["code"]: t for t in found.json()["items"]}


async def _made(
    world: World,
    org: Org,
    name: str,
    type_code: str = "server",
    **extra: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    made = await _ci(world, org, name, type_code, **extra)
    assert made.status_code == 201, made.text
    return dict(made.json())


async def _link(
    world: World,
    org: Org,
    ci: dict[str, Any],
    code: str,
    targets: list[dict[str, Any]],
    *,
    user: uuid.UUID | None = None,
    direction: str = "forward",
) -> httpx.Response:
    types = await _rel_types(world, org)
    body = {
        "type_id": types[code]["id"],
        "direction": direction,
        "targets": [t["id"] for t in targets],
    }
    return await world.call(
        "POST",
        f"{BASE}/cis/{ci['id']}/relationships",
        org,
        user or org.admin,
        json=body,
        headers=_new(),
    )


async def _get(world: World, org: Org, ci: dict[str, Any]) -> dict[str, Any]:
    found = await world.call("GET", f"{BASE}/cis/{ci['id']}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def _snapshot(world: World, org: Org, ci: dict[str, Any]) -> dict[str, Any]:
    rows = await world.sql(
        "SELECT snapshot FROM cmdb_ci_versions WHERE tenant_id = $1 AND ci_id = $2"
        " ORDER BY version DESC LIMIT 1",
        org.tenant,
        uuid.UUID(ci["id"]),
    )
    return dict(json.loads(rows[0]["snapshot"]))


async def _neighbours(
    world: World,
    org: Org,
    ci: dict[str, Any],
    user: uuid.UUID,
    **params: Any,  # noqa: ANN401 - query values
) -> httpx.Response:
    return await world.call("GET", f"{BASE}/cis/{ci['id']}/neighbours", org, user, params=params)


async def _given(world: World, org: Org, user: uuid.UUID, name: str, grants: list[Any]) -> None:
    made = await role(world, org, name, grants)
    assigned = await world.call("PUT", f"/users/{user}/roles/{made}", org, org.admin)
    assert assigned.status_code == 204, assigned.text


# --- tenant isolation (rule a) --------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
async def test_s2_tables_are_isolated_by_rls(world: World, table: str) -> None:
    a, b = world.a, world.b
    app = await _made(world, a, "RLS app", "application")
    db = await _made(world, a, "RLS db", "database")
    linked = await _link(world, a, app, "depends_on", [db])
    assert linked.status_code == 201, linked.text
    rack = await _type(world, a, f"rls_rack_{uuid.uuid4().hex[:6]}", None)
    assert rack.status_code == 201, rack.text
    types = await _types(world, a)
    ruled = await world.call(
        "POST",
        f"{BASE}/relationship-types",
        a,
        a.admin,
        json={
            "code": f"rls_{uuid.uuid4().hex[:8]}",
            "names_forward": {"en": "sits in", "ar": "يقع في", "ur": "میں ہے"},
            "names_inverse": {"en": "holds", "ar": "يحمل", "ur": "رکھتا ہے"},
            "rules": [
                {"from_ci_type_id": types["server"]["id"], "to_ci_type_id": rack.json()["id"]}
            ],
        },
        headers=_new(),
    )
    assert ruled.status_code == 201, ruled.text
    view = await world.call(
        "POST",
        f"{BASE}/business-views",
        a,
        a.admin,
        json={"base_ci_id": app["id"], "name": "RLS view"},
        headers=_new(),
    )
    assert view.status_code == 201, view.text
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() > 0  # noqa: S608 - fixed table names
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text(f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            {"a": a.tenant},
        )
        assert changed.rowcount == 0
    # Over HTTP too: B never reaches A's view or A's CI's map.
    other = await world.call("GET", f"{BASE}/business-views/{view.json()['id']}", b, b.admin)
    assert problem(other) == (404, "cmdb_business_view_not_found")
    assert problem(await _neighbours(world, b, app, b.admin)) == (404, "cmdb_ci_not_found")


# --- relationship types (REQ-CMDB-006) ------------------------------------------------------------


async def test_built_in_types_are_made_once_with_their_impact(world: World) -> None:
    a = world.a
    first = await _rel_types(world, a)
    again = await _rel_types(world, a)
    assert set(first) >= {
        "depends_on",
        "runs_on",
        "connected_to",
        "part_of",
        "virtualised_by",
        "backed_up_by",
        "located_in",
        "managed_by",
    }
    assert {k: v["id"] for k, v in first.items()} == {k: v["id"] for k, v in again.items()}
    assert first["runs_on"]["carries_impact"] is True
    assert first["backed_up_by"]["carries_impact"] is False  # stored for S3's impact analysis
    built_in = await world.sql(
        "SELECT count(*) AS n FROM cmdb_relationship_types WHERE tenant_id = $1 AND built_in",
        a.tenant,
    )
    assert built_in[0]["n"] == 8
    locked = await world.call(
        "DELETE",
        f"{BASE}/relationship-types/{first['runs_on']['id']}",
        a,
        a.admin,
        headers=_match(first["runs_on"]["version"]),
    )
    assert problem(locked) == (409, "cmdb_built_in_locked")


async def test_a_tenant_type_needs_both_names_in_every_language(world: World) -> None:
    a = world.a
    missing = await world.call(
        "POST",
        f"{BASE}/relationship-types",
        a,
        a.admin,
        json={
            "code": "feeds",
            "names_forward": {"en": "feeds"},
            "names_inverse": {"en": "fed by", "ar": "يُغذّى من", "ur": "سے ملتا ہے"},
        },
        headers=_new(),
    )
    codes = field_codes(missing)
    assert codes["names_forward.ar"] == "required"
    assert codes["names_forward.ur"] == "required"
    technician = await world.call(
        "POST",
        f"{BASE}/relationship-types",
        a,
        a.tech_a,
        json={"code": "x_y", "names_forward": {}, "names_inverse": {}},
        headers=_new(),
    )
    assert technician.status_code == 403


async def test_a_server_to_rack_type_refuses_two_applications(world: World) -> None:
    """006 AC2, with a rule on `hardware` covering a server below it."""
    a = world.a
    rack_type = await _type(world, a, f"rack_{uuid.uuid4().hex[:6]}", None)
    assert rack_type.status_code == 201, rack_type.text
    types = await _types(world, a)
    code = f"in_rack_{uuid.uuid4().hex[:6]}"
    made = await world.call(
        "POST",
        f"{BASE}/relationship-types",
        a,
        a.admin,
        json={
            "code": code,
            "names_forward": {"en": "racked in", "ar": "مركّب في", "ur": "ریک میں"},
            "names_inverse": {"en": "racks", "ar": "يضم", "ur": "ریک کرتا ہے"},
            "carries_impact": False,
            "rules": [
                {
                    "from_ci_type_id": types["hardware"]["id"],
                    "to_ci_type_id": rack_type.json()["id"],
                    "suggested": True,
                }
            ],
        },
        headers=_new(),
    )
    assert made.status_code == 201, made.text
    assert made.json()["carries_impact"] is False
    server = await _made(world, a, "Racked server")
    rack = await _made(world, a, "Rack A1", rack_type.json()["api_name"])
    app_one = await _made(world, a, "App one", "application")
    app_two = await _made(world, a, "App two", "application")
    assert (await _link(world, a, server, code, [rack])).status_code == 201
    refused = await _link(world, a, app_one, code, [app_two])
    assert field_codes(refused) == {"targets.0": "cmdb_relationship_not_allowed"}
    offered = await world.call(
        "GET",
        f"{BASE}/relationship-types",
        a,
        a.admin,
        params={"for_ci_type": types["server"]["id"]},
    )
    items = offered.json()["items"]
    assert items[0]["code"] == code  # suggested first
    assert items[0]["suggested"] is True
    used = await world.call(
        "DELETE",
        f"{BASE}/relationship-types/{made.json()['id']}",
        a,
        a.admin,
        headers=_match(made.json()["version"]),
    )
    assert problem(used) == (409, "cmdb_relationship_type_in_use")
    assert used.json()["params"]["relationship_count"] == 1


async def test_type_changes_are_audited(world: World) -> None:
    a = world.a
    made = await world.call(
        "POST",
        f"{BASE}/relationship-types",
        a,
        a.admin,
        json={
            "code": f"audited_{uuid.uuid4().hex[:6]}",
            "names_forward": {"en": "watches", "ar": "يراقب", "ur": "نگرانی کرتا ہے"},
            "names_inverse": {"en": "watched by", "ar": "مراقَب من", "ur": "زیرِ نگرانی"},
        },
        headers=_new(),
    )
    assert made.status_code == 201, made.text
    rows = await world.sql(
        "SELECT action FROM audit_entries WHERE tenant_id = $1"
        " AND action LIKE 'cmdb.relationship%'",
        a.tenant,
    )
    assert "cmdb.relationship_type_created" in {r["action"] for r in rows}


# --- adding and removing (REQ-CMDB-007) -----------------------------------------------------------


async def test_one_application_depends_on_three_databases(world: World) -> None:
    """007 AC1: a history line, a new version and a snapshot on all four CIs; one event."""
    a = world.a
    app = await _made(world, a, "Billing app", "application")
    dbs = [await _made(world, a, f"Billing db {n}", "database") for n in range(3)]
    linked = await _link(world, a, app, "depends_on", dbs)
    assert linked.status_code == 201, linked.text
    assert len(linked.json()["items"]) == 3
    for ci in (app, *dbs):
        now = await _get(world, a, ci)
        assert now["version"] == 2
        history = await world.call("GET", f"{BASE}/cis/{ci['id']}/history", a, a.admin)
        latest = history.json()["items"][0]
        assert latest["kind"] == "child_added"
        assert {c["field"] for c in latest["changes"]} == {"relationship"}
    app_links = (await _snapshot(world, a, app))["relationships"]
    assert {(link["direction"], link["ci_id"]) for link in app_links} == {
        ("forward", d["id"]) for d in dbs
    }
    db_links = (await _snapshot(world, a, dbs[0]))["relationships"]
    assert [(link["direction"], link["ci_id"]) for link in db_links] == [("inverse", app["id"])]
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'cmdb.relationship.changed' AND aggregate_id = $2",
        a.tenant,
        app["id"],
    )
    assert len(events) == 1
    assert "Billing" not in events[0]["envelope"]  # IDs only


async def test_a_duplicate_and_a_self_link_are_refused(world: World) -> None:
    a = world.a
    web = await _made(world, a, "Web 7", "application")
    host = await _made(world, a, "Host 7")
    assert (await _link(world, a, web, "runs_on", [host])).status_code == 201
    again = await _link(world, a, web, "runs_on", [host])
    assert problem(again) == (409, "cmdb_relationship_exists")  # 007 AC2
    assert again.json()["params"]["display_id"] == host["display_id"]
    # The same link from the other side is the same link.
    inverse = await _link(world, a, host, "runs_on", [web], direction="inverse")
    assert problem(inverse) == (409, "cmdb_relationship_exists")
    itself = await _link(world, a, web, "connected_to", [web])
    assert field_codes(itself) == {"targets": "cmdb_relationship_self"}


async def test_edit_rights_on_every_end_all_or_nothing(world: World) -> None:
    """Lane C's condition 1: view-only on a target is a 403 naming it, and nothing is linked."""
    a = world.a
    source = await _made(world, a, "Site one app", "application", site_id=str(a.s1))
    near = await _made(world, a, "Site one db", "database", site_id=str(a.s1))
    far = await _made(world, a, "Site two db", "database", site_id=str(a.s2))
    await _given(
        world, a, a.requester, "Site CMDB editor", [("cmdb.view", "all"), ("cmdb.edit", "site")]
    )
    denied = await _link(world, a, source, "depends_on", [near, far], user=a.requester)
    assert problem(denied) == (403, "cmdb_relationship_target_denied")
    assert denied.json()["params"]["display_id"] == far["display_id"]
    assert (await _get(world, a, near))["version"] == 1  # all or nothing
    assert (await _get(world, a, source))["version"] == 1
    allowed = await _link(world, a, source, "depends_on", [near], user=a.requester)
    assert allowed.status_code == 201, allowed.text
    # A target they cannot see at all: a 404 that names nothing.
    await _given(
        world,
        a,
        a.requester2,
        "Site CMDB editor only",
        [("cmdb.view", "site"), ("cmdb.edit", "site")],
    )
    hidden = await _link(world, a, source, "depends_on", [far], user=a.requester2)
    assert problem(hidden) == (404, "cmdb_ci_not_found")
    assert far["display_id"] not in hidden.text
    # Removing needs both ends too.
    across = await _link(world, a, source, "managed_by", [far])
    assert across.status_code == 201, across.text
    link = across.json()["items"][0]
    refused = await world.call(
        "DELETE",
        f"{BASE}/relationships/{link['id']}",
        a,
        a.requester,
        headers=_match(link["version"]),
    )
    assert problem(refused) == (403, "cmdb_relationship_target_denied")


async def test_removing_gives_both_ends_a_version(world: World) -> None:
    a = world.a
    app = await _made(world, a, "Unlinked app", "application")
    host = await _made(world, a, "Unlinked host")
    link = (await _link(world, a, app, "runs_on", [host])).json()["items"][0]
    removed = await world.call(
        "DELETE", f"{BASE}/relationships/{link['id']}", a, a.admin, headers=_match(link["version"])
    )
    assert removed.status_code == 204, removed.text
    for ci in (app, host):
        assert (await _get(world, a, ci))["version"] == 3
        assert (await _snapshot(world, a, ci))["relationships"] == []
        history = await world.call("GET", f"{BASE}/cis/{ci['id']}/history", a, a.admin)
        assert history.json()["items"][0]["kind"] == "child_removed"
    gone = await world.call(
        "DELETE", f"{BASE}/relationships/{link['id']}", a, a.admin, headers=_match(2)
    )
    assert problem(gone) == (404, "cmdb_relationship_not_found")
    # Removed, so the same link may be made again.
    assert (await _link(world, a, app, "runs_on", [host])).status_code == 201


async def test_relationship_events_reach_both_ends(world: World) -> None:
    """007 AC3's server side: both CIs' record channels and list audiences, IDs only."""
    a = world.a
    app = await _made(world, a, "Live app", "application", site_id=str(a.s1))
    host = await _made(world, a, "Live host", site_id=str(a.s2))
    assert (await _link(world, a, app, "runs_on", [host])).status_code == 201
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'cmdb.relationship.changed' AND aggregate_id = $2",
        a.tenant,
        app["id"],
    )
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    channels: set[str] = set()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        for spec in ROUTES:
            if envelope.event_type in spec.event_types:
                effects = await spec.route(envelope, session)
                channels |= {p.channel.name for p in effects.publications}
                assert "Live" not in repr(effects.publications)
                assert all(
                    p.fields == ("relationships",)
                    for p in effects.publications
                    if p.channel.kind == "ci"
                )
    t = a.tenant
    assert {
        f"t:{t}:ci:{app['id']}",
        f"t:{t}:ci:{host['id']}",
        f"t:{t}:queue:cmdb.site.{a.s1}",
        f"t:{t}:queue:cmdb.site.{a.s2}",
    } <= channels


async def test_history_never_names_a_ci_the_reader_cannot_see(world: World) -> None:
    a = world.a
    mine = await _made(world, a, "Seen app", "application", site_id=str(a.s1))
    theirs = await _made(world, a, "Unseen db", "database", site_id=str(a.s2))
    assert (await _link(world, a, mine, "depends_on", [theirs])).status_code == 201
    await _given(world, a, a.requester2, "Site one viewer", [("cmdb.view", "site")])
    seen = await world.call("GET", f"{BASE}/cis/{mine['id']}/history", a, a.requester2)
    assert seen.status_code == 200, seen.text
    (change,) = seen.json()["items"][0]["changes"]
    assert change["new"]["restricted"] is True
    assert change["new"]["ci_id"] is None
    assert theirs["id"] not in seen.text


# --- neighbours (REQ-CMDB-008) --------------------------------------------------------------------


async def test_neighbours_follow_depth_and_type_filters(world: World) -> None:
    a = world.a
    service = await _made(world, a, "Pay service", "business_service")
    app = await _made(world, a, "Pay app", "application")
    db = await _made(world, a, "Pay db", "database")
    host = await _made(world, a, "Pay host")
    assert (await _link(world, a, service, "depends_on", [app])).status_code == 201
    assert (await _link(world, a, app, "depends_on", [db])).status_code == 201
    assert (await _link(world, a, app, "runs_on", [host])).status_code == 201
    one = (await _neighbours(world, a, service, a.admin)).json()
    assert {n["key"] for n in one["nodes"]} == {service["id"], app["id"]}
    assert one["truncated"] is False
    assert one["node_max"] == 500
    assert one["counts_available"] is False  # the S5 port is not registered yet
    two = (await _neighbours(world, a, service, a.admin, depth=2)).json()
    assert {n["key"] for n in two["nodes"]} == {service["id"], app["id"], db["id"], host["id"]}
    node = next(n for n in two["nodes"] if n["key"] == db["id"])
    assert node["type_label_key"] == "cmdb_ci_type.database"
    assert node["state_category"] == "active"
    assert node["counts"] is None
    types = await _rel_types(world, a)
    only = await _neighbours(world, a, service, a.admin, depth=2, types=[types["depends_on"]["id"]])
    assert host["id"] not in {n["key"] for n in only.json()["nodes"]}
    ci_types = await _types(world, a)
    apps_only = await _neighbours(
        world, a, service, a.admin, depth=2, ci_types=[ci_types["application"]["id"]]
    )
    # database sits below application in the type tree: kept; the server is not.
    assert {n["key"] for n in apps_only.json()["nodes"]} == {service["id"], app["id"], db["id"]}


async def test_a_restricted_neighbour_is_a_bare_placeholder(world: World) -> None:
    """Lane C's condition 2: an opaque key, no fields; its own neighbours are never shown."""
    a = world.a
    seen = await _made(world, a, "Front app", "application", site_id=str(a.s1))
    hidden = await _made(world, a, "Secret db", "database", site_id=str(a.s2))
    beyond = await _made(world, a, "Beyond host", site_id=str(a.s1))
    assert (await _link(world, a, seen, "depends_on", [hidden])).status_code == 201
    assert (await _link(world, a, hidden, "runs_on", [beyond])).status_code == 201
    await _given(world, a, a.requester2, "Site one map viewer", [("cmdb.view", "site")])
    found = await _neighbours(world, a, seen, a.requester2, depth=3)
    assert found.status_code == 200, found.text
    body = found.json()
    restricted = [n for n in body["nodes"] if n["restricted"]]
    assert len(restricted) == 1
    (placeholder,) = restricted
    assert placeholder["key"].startswith("r")
    assert placeholder["id"] is None
    assert placeholder["name"] is None
    assert placeholder["type_id"] is None
    assert placeholder["state_category"] is None
    assert hidden["id"] not in found.text
    assert "Secret" not in found.text
    assert beyond["id"] not in found.text  # never walked through
    (edge,) = body["edges"]
    assert edge["to_key"] == placeholder["key"]
    assert edge["id"] is None  # nothing to act on
    assert edge["type_id"]  # the relationship type may show
    direct = await _neighbours(world, a, hidden, a.requester2)
    assert problem(direct) == (404, "cmdb_ci_not_found")


async def test_end_of_life_and_trashed_neighbours(world: World) -> None:
    a = world.a
    base = await _made(world, a, "EOL base", "application")
    states = {
        s["api_name"]: s
        for s in (await world.call("GET", f"{BASE}/ci-states", a, a.admin)).json()["items"]
    }
    old = await _made(world, a, "Retired host", state_id=states["retired"]["id"])
    binned = await _made(world, a, "Binned host")
    assert (await _link(world, a, base, "runs_on", [old, binned])).status_code == 201
    binned = await _get(world, a, binned)
    gone = await world.call(
        "DELETE", f"{BASE}/cis/{binned['id']}", a, a.admin, headers=_match(binned["version"])
    )
    assert gone.status_code == 204, gone.text
    hidden_eol = await _neighbours(world, a, base, a.admin)
    assert {n["key"] for n in hidden_eol.json()["nodes"]} == {base["id"]}
    shown = await _neighbours(world, a, base, a.admin, eol="true")
    assert {n["key"] for n in shown.json()["nodes"]} == {base["id"], old["id"]}


# --- business views (REQ-CMDB-009) ----------------------------------------------------------------


async def _view(
    world: World,
    org: Org,
    base: dict[str, Any],
    name: str,
    user: uuid.UUID | None = None,
    **extra: Any,  # noqa: ANN401 - JSON
) -> httpx.Response:
    return await world.call(
        "POST",
        f"{BASE}/business-views",
        org,
        user or org.admin,
        json={"base_ci_id": base["id"], "name": name, **extra},
        headers=_new(),
    )


async def test_save_as_new_leaves_the_first_unchanged(world: World) -> None:
    """009 AC2."""
    a = world.a
    service = await _made(world, a, "Orders service", "business_service")
    first = await _view(
        world, a, service, "Orders map", layout="tree", filters={"depth": 2, "show_eol": True}
    )
    assert first.status_code == 201, first.text
    original = first.json()
    copy = await world.call(
        "POST",
        f"{BASE}/business-views/{original['id']}/save-as-new",
        a,
        a.admin,
        json={"name": "Orders map, radial", "layout": "radial"},
        headers=_new(),
    )
    assert copy.status_code == 201, copy.text
    assert copy.json()["id"] != original["id"]
    assert copy.json()["filters"]["depth"] == 2
    again = await world.call("GET", f"{BASE}/business-views/{original['id']}", a, a.admin)
    assert again.json()["name"] == "Orders map"
    assert again.json()["layout"] == "tree"
    assert again.json()["version"] == original["version"]
    listed = await world.call(
        "GET", f"{BASE}/business-views", a, a.admin, params={"base_ci_id": service["id"]}
    )
    assert {v["id"] for v in listed.json()["items"]} == {original["id"], copy.json()["id"]}


async def test_only_the_owner_or_configure_changes_a_view(world: World) -> None:
    a = world.a
    service = await _made(world, a, "Owned service", "business_service")
    await _given(world, a, a.tech_b, "CMDB editor", [("cmdb.view", "all"), ("cmdb.edit", "all")])
    made = await _view(world, a, service, "Tech B's map", user=a.tech_b)
    assert made.status_code == 201, made.text
    view = made.json()
    assert view["owner_id"] == str(a.tech_b)
    await _given(world, a, a.tech_c, "Another editor", [("cmdb.view", "all"), ("cmdb.edit", "all")])
    not_owner = await world.call(
        "DELETE",
        f"{BASE}/business-views/{view['id']}",
        a,
        a.tech_c,
        headers=_match(view["version"]),
    )
    assert problem(not_owner) == (403, "cmdb_business_view_not_owner")
    renamed = await world.call(
        "PATCH",
        f"{BASE}/business-views/{view['id']}",
        a,
        a.tech_b,
        json={"name": "Tech B's map 2"},
        headers=_match(view["version"]),
    )
    assert renamed.status_code == 200, renamed.text
    stale = await world.call(
        "PATCH",
        f"{BASE}/business-views/{view['id']}",
        a,
        a.tech_b,
        json={"name": "Lost"},
        headers=_match(view["version"]),
    )
    assert problem(stale) == (409, "version_conflict")
    by_admin = await world.call(
        "DELETE",
        f"{BASE}/business-views/{view['id']}",
        a,
        a.admin,
        headers=_match(renamed.json()["version"]),
    )
    assert by_admin.status_code == 204, by_admin.text
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND aggregate_id = $2"
        " AND event_type = 'cmdb.business_view.changed'",
        a.tenant,
        view["id"],
    )
    assert len(events) == 3
    assert "Tech B" not in json.dumps([e["envelope"] for e in events])


async def test_a_view_is_seen_through_the_viewers_rights(world: World) -> None:
    """Lane C's condition 4: no view on a hidden base; no position of a hidden CI."""
    a = world.a
    base = await _made(world, a, "Shared base", "business_service", site_id=str(a.s1))
    near = await _made(world, a, "Near node", site_id=str(a.s1))
    far = await _made(world, a, "Far node", site_id=str(a.s2))
    hidden_base = await _made(world, a, "Hidden base", "business_service", site_id=str(a.s2))
    positions = {near["id"]: {"x": 10, "y": 20}, far["id"]: {"x": -5, "y": 7.5}}
    made = await _view(world, a, base, "Shared map", positions=positions)
    assert made.status_code == 201, made.text
    secret = await _view(world, a, hidden_base, "Hidden map")
    assert secret.status_code == 201, secret.text
    await _given(world, a, a.requester, "Site one CMDB viewer", [("cmdb.view", "site")])
    listed = await world.call("GET", f"{BASE}/business-views", a, a.requester)
    ids = {v["id"] for v in listed.json()["items"]}
    assert made.json()["id"] in ids
    assert secret.json()["id"] not in ids
    one = await world.call("GET", f"{BASE}/business-views/{made.json()['id']}", a, a.requester)
    assert set(one.json()["positions"]) == {near["id"]}
    assert far["id"] not in one.text
    assert one.json()["can_edit"] is False
    hidden = await world.call("GET", f"{BASE}/business-views/{secret.json()['id']}", a, a.requester)
    assert problem(hidden) == (404, "cmdb_business_view_not_found")
    # An admin who sees only site one moves the near node: the far one, which only others see,
    # stays pinned (a save never drops what the editor cannot see).
    await _given(
        world,
        a,
        a.requester,
        "Site one CMDB admin",
        [("cmdb.view", "site"), ("cmdb.configure", "all")],
    )
    moved = await world.call(
        "PATCH",
        f"{BASE}/business-views/{made.json()['id']}",
        a,
        a.requester,
        json={"positions": {near["id"]: {"x": 1, "y": 2}}},
        headers=_match(made.json()["version"]),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["positions"] == {near["id"]: {"x": 1.0, "y": 2.0}}
    stored = await world.sql(
        "SELECT positions FROM cmdb_business_views WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(made.json()["id"]),
    )
    assert json.loads(stored[0]["positions"]) == {
        near["id"]: {"x": 1.0, "y": 2.0},
        far["id"]: {"x": -5, "y": 7.5},
    }


async def test_a_view_on_a_ci_needs_edit_to_be_made(world: World) -> None:
    a = world.a
    base = await _made(world, a, "Viewer base", "business_service")
    await _given(world, a, a.requester2, "Only a viewer", [("cmdb.view", "all")])
    refused = await _view(world, a, base, "Not mine to make", user=a.requester2)
    assert refused.status_code == 403


# --- versions (REQ-CMDB-024) ----------------------------------------------------------------------


async def test_as_of_and_compare_show_attributes_and_relationships(world: World) -> None:
    """024 AC1/AC2, through the reader's current rights (lane C's condition 3)."""
    a = world.a
    server = await _made(world, a, "Versioned server", site_id=str(a.s1))
    rack = await _made(world, a, "Versioned rack", site_id=str(a.s2))
    assert (await _link(world, a, server, "located_in", [rack])).status_code == 201
    current = await _get(world, a, server)
    edited = await world.call(
        "PATCH",
        f"{BASE}/cis/{server['id']}",
        a,
        a.admin,
        json={"criticality": "high"},
        headers=_match(current["version"]),
    )
    assert edited.status_code == 200, edited.text
    listed = await world.call("GET", f"{BASE}/cis/{server['id']}/versions", a, a.admin)
    assert [v["version"] for v in listed.json()["items"]] == [3, 2, 1]
    # The versions' own save times (the database's clock), so no clock skew can move the test.
    saved = {
        r["version"]: r["saved_at"]
        for r in await world.sql(
            "SELECT version, saved_at FROM cmdb_ci_versions WHERE tenant_id = $1 AND ci_id = $2",
            a.tenant,
            uuid.UUID(server["id"]),
        )
    }
    then = await world.call(
        "GET", f"{BASE}/cis/{server['id']}/as-of", a, a.admin, params={"at": saved[1].isoformat()}
    )
    assert then.status_code == 200, then.text
    assert then.json()["version"] == 1
    assert then.json()["relationships"] == []
    now = await world.call(
        "GET",
        f"{BASE}/cis/{server['id']}/as-of",
        a,
        a.admin,
        params={"at": saved[3].isoformat()},
    )
    assert now.json()["version"] == 3
    assert now.json()["fields"]["criticality"] == "high"
    (link,) = now.json()["relationships"]
    assert link["direction"] == "forward"
    assert link["ci"]["key"] == rack["id"]
    never = await world.call(
        "GET",
        f"{BASE}/cis/{server['id']}/as-of",
        a,
        a.admin,
        params={"at": "2000-01-01T00:00:00+00:00"},
    )
    assert problem(never) == (404, "cmdb_ci_version_not_found")
    compared = await world.call(
        "GET", f"{BASE}/cis/{server['id']}/compare", a, a.admin, params={"from": 1, "to": 3}
    )
    assert compared.status_code == 200, compared.text
    body = compared.json()
    assert [(c["field"], c["kind"]) for c in body["attributes"]] == [("criticality", "added")]
    assert [r["ci"]["key"] for r in body["relationships_added"]] == [rack["id"]]
    assert body["relationships_removed"] == []
    # A reader who may not see the rack now: a placeholder in every version.
    await _given(world, a, a.requester, "Site one version reader", [("cmdb.view", "site")])
    limited = await world.call(
        "GET", f"{BASE}/cis/{server['id']}/compare", a, a.requester, params={"from": 1, "to": 3}
    )
    assert limited.status_code == 200, limited.text
    (placeholder,) = limited.json()["relationships_added"]
    assert placeholder["ci"]["restricted"] is True
    assert placeholder["id"] is None
    assert rack["id"] not in limited.text
    assert "Versioned rack" not in limited.text
    hidden = await world.call("GET", f"{BASE}/cis/{rack['id']}/versions", a, a.requester)
    assert problem(hidden) == (404, "cmdb_ci_not_found")


async def test_an_old_version_names_a_related_ci_as_it_is_now(world: World) -> None:
    """Lane C's refinement (S2 §7.3): snapshots keep the related CI's ID and the type only, never
    its name. A reader who sees it now reads its current name; one who doesn't reads "restricted",
    never the name it had then."""
    a = world.a
    app = await _made(world, a, "Billing app", "application", site_id=str(a.s1))
    db = await _made(world, a, "Old db name", "database", site_id=str(a.s2))
    assert (await _link(world, a, app, "depends_on", [db])).status_code == 201
    stored = await world.sql(
        "SELECT snapshot FROM cmdb_ci_versions WHERE tenant_id = $1 AND ci_id = $2",
        a.tenant,
        uuid.UUID(app["id"]),
    )
    assert "Old db name" not in json.dumps([json.loads(r["snapshot"]) for r in stored])
    current = await _get(world, a, db)
    renamed = await world.call(
        "PATCH",
        f"{BASE}/cis/{db['id']}",
        a,
        a.admin,
        json={"name": "New db name"},
        headers=_match(current["version"]),
    )
    assert renamed.status_code == 200, renamed.text
    listed = await world.call("GET", f"{BASE}/cis/{app['id']}/versions", a, a.admin)
    linked = max(v["version"] for v in listed.json()["items"])
    seen = await world.call(
        "GET", f"{BASE}/cis/{app['id']}/compare", a, a.admin, params={"from": 1, "to": linked}
    )
    assert "New db name" in seen.text
    assert "Old db name" not in seen.text
    await _given(world, a, a.requester, "Site one app reader", [("cmdb.view", "site")])
    limited = await world.call(
        "GET", f"{BASE}/cis/{app['id']}/compare", a, a.requester, params={"from": 1, "to": linked}
    )
    assert limited.status_code == 200, limited.text
    (placeholder,) = limited.json()["relationships_added"]
    assert placeholder["ci"]["restricted"] is True
    assert "Old db name" not in limited.text
    assert "New db name" not in limited.text


async def test_versions_show_only_the_cis_saved_fields(world: World) -> None:
    """A snapshot key outside the CI's fields is never shown (custom fields wait for 0175 part 2
    with ADR-047 field access and sealed values)."""
    a = world.a
    ci = await _made(world, a, "Snapshot only fields")
    shown = await world.call(
        "GET",
        f"{BASE}/cis/{ci['id']}/as-of",
        a,
        a.admin,
        params={"at": (datetime.now(UTC) + timedelta(seconds=5)).isoformat()},
    )
    assert set(shown.json()["fields"]) == {
        "type_id",
        "name",
        "description",
        "state_id",
        "site_id",
        "owner_user_id",
        "owner_group_id",
        "managed_by_group_id",
        "business_impact",
        "criticality",
        "asset_id",
        "source",
    }


# --- erasure (ADR-052) ----------------------------------------------------------------------------


async def test_erasure_moves_owned_views_to_the_successor(world: World) -> None:
    a = world.a
    base = await _made(world, a, "Erasure base", "business_service")
    await _given(world, a, a.requester, "View maker", [("cmdb.view", "all"), ("cmdb.edit", "all")])
    view = (await _view(world, a, base, "Requester's map", user=a.requester)).json()
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        first = await PORT.erase_person(
            session,
            a.requester,
            successor_id=a.lead,
            keep_files={},
            now=datetime.now(UTC),
            cursor=None,
        )
    assert first.counts["cmdb_views_moved"] == 1
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        second = await PORT.erase_person(
            session,
            a.requester,
            successor_id=a.lead,
            keep_files={},
            now=datetime.now(UTC),
            cursor=None,
        )
    assert second.counts["cmdb_views_moved"] == 0
    after = await world.call("GET", f"{BASE}/business-views/{view['id']}", a, a.admin)
    assert after.json()["owner_id"] == str(a.lead)
    assert after.json()["version"] == view["version"] + 1
