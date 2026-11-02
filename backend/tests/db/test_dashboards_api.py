"""Dashboards over HTTP (WP-036). Test names cite parity file 09 criteria (REQ-DSH-*).

The incident world of test_reports_api.py (lane A's real incident source): org A has an admin,
a lead (all scope), technicians with the D-052 `group` scope, and org B for isolation.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantContext
from app.modules.analytics.domain.dashboard import ME, with_viewer
from app.modules.analytics.domain.widgets import BUILTIN_DASHBOARDS
from app.shared.events import EventEnvelope
from tests.db import test_reports_api
from tests.db.test_incidents_api import CONSOLE, Org, World

pytestmark = pytest.mark.db
world = test_reports_api.world
reports = test_reports_api.reports

BASE = "/dashboards"
OPEN = {"field": "status_category", "op": "in", "value": ["open", "paused"]}


def _kpi(widget_id: str = "open", **report: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {
        "id": widget_id,
        "title": "Open",
        "report": {"entity": "incident", "measures": ["open_count"], "chart": "kpi", **report},
        "place": {"x": 0, "y": 0, "w": 3, "h": 2},
    }


def _body(name: str = "Team board", **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"name": name, "body": {"widgets": [_kpi()]}, **extra}


async def _create(world: World, org: Org, user: uuid.UUID, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    response = await world.call(
        "POST",
        BASE,
        org,
        user,
        json=_body(**extra),
        headers={**CONSOLE, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _patch(
    world: World,
    org: Org,
    user: uuid.UUID,
    dashboard: dict[str, Any],
    **changes: Any,  # noqa: ANN401 - JSON
) -> Any:  # noqa: ANN401 - httpx response
    return await world.call(
        "PATCH",
        f"{BASE}/{dashboard['ref']}",
        org,
        user,
        json=changes,
        headers={**CONSOLE, "If-Match": f'"{dashboard["version"]}"'},
    )


async def _home(world: World, org: Org, user: uuid.UUID) -> str:
    response = await world.call("GET", f"{BASE}/home", org, user)
    assert response.status_code == 200, response.text
    return str(response.json()["dashboard_ref"])


# --- REQ-DSH-003: ready-made dashboards work with no set-up --------------------------------------


async def test_req_dsh_003_ac1_builtin_dashboards_run_for_every_viewer(reports: World) -> None:
    world = reports
    a = world.a
    await test_reports_api.seed(world)
    listed = await world.call("GET", BASE, a, a.tech_a)
    assert listed.status_code == 200, listed.text
    builtin = [d for d in listed.json()["items"] if d["builtin"]]
    assert {d["builtin"] for d in builtin} == set(BUILTIN_DASHBOARDS)
    for user in (a.admin, a.tech_a):
        for dashboard in builtin:
            for widget in dashboard["body"]["widgets"]:
                if widget["report"] is None:  # a records list (D-114): the entity's own list
                    tree = with_viewer(widget["records"]["filter"], user)
                    query = {"limit": 5} | ({"filter": json.dumps(tree)} if tree else {})
                    listed = await world.call("GET", "/incidents", a, user, params=query)
                    assert listed.status_code == 200, (dashboard["builtin"], widget["id"])
                    continue
                definition = with_viewer(widget["report"], user)
                run = await world.call(
                    "POST",
                    "/reports/run",
                    a,
                    user,
                    json={"definition": definition},
                    headers=CONSOLE,
                )
                assert run.status_code == 200, (dashboard["builtin"], widget["id"], run.text)
    # The service desk's "open" KPI counts what each viewer may list (REQ-DSH-028 AC1).
    kpi = with_viewer(_kpi()["report"], a.tech_a)
    lead = await test_reports_api.ran(world, a, a.lead, **{**kpi, "entity": "incident"})
    tech = await test_reports_api.ran(world, a, a.tech_a, **{**kpi, "entity": "incident"})
    assert lead["totals"][0] > tech["totals"][0]


async def test_req_dsh_003_ac3_a_builtin_dashboard_cannot_be_edited(reports: World) -> None:
    world = reports
    a = world.a
    response = await world.call(
        "PATCH",
        f"{BASE}/builtin:service_desk",
        a,
        a.admin,
        json={"name": "Mine"},
        headers={**CONSOLE, "If-Match": '"1"'},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "dashboard_not_editable"


# --- REQ-DSH-002: home per role, the user's own choice ------------------------------------------


async def test_req_dsh_002_role_homes_own_choice_and_reset(reports: World) -> None:
    world = reports
    a = world.a
    assert await _home(world, a, a.tech_a) == "builtin:my_work"  # AC1: technician
    assert await _home(world, a, a.admin) == "builtin:service_desk"  # AC1: manager
    chosen = await world.call(
        "PUT", f"{BASE}/home", a, a.tech_a, json={"dashboard_ref": "builtin:service_desk"}
    )
    assert chosen.json() == {"dashboard_ref": "builtin:service_desk", "chosen": True}
    assert await _home(world, a, a.tech_a) == "builtin:service_desk"  # AC2: kept
    reset = await world.call("PUT", f"{BASE}/home", a, a.tech_a, json={"dashboard_ref": None})
    assert reset.json() == {"dashboard_ref": "builtin:my_work", "chosen": False}

    # An admin gives technicians a shared home; the technician's own choice still wins.
    board = await _create(world, a, a.admin, shared=True)
    denied = await world.call(
        "PUT", f"{BASE}/role-homes/technician", a, a.tech_a, json={"dashboard_ref": board["ref"]}
    )
    assert denied.status_code == 403
    set_home = await world.call(
        "PUT", f"{BASE}/role-homes/technician", a, a.admin, json={"dashboard_ref": board["ref"]}
    )
    assert set_home.status_code == 204, set_home.text
    assert await _home(world, a, a.tech_a) == board["ref"]
    # Un-sharing it: a role home must be shared, so technicians fall back to the built-in one.
    await _patch(world, a, a.admin, board, shared=False)
    assert await _home(world, a, a.tech_a) == "builtin:my_work"
    private = await _create(world, a, a.admin)
    refused = await world.call(
        "PUT", f"{BASE}/role-homes/technician", a, a.admin, json={"dashboard_ref": private["ref"]}
    )
    assert refused.status_code == 422
    assert refused.json()["errors"][0]["code"] == "dashboard_not_shared"


# --- REQ-DSH-026, 029: private and shared; permissions -------------------------------------------


async def test_req_dsh_026_private_until_shared_and_dsh_029_sharing_needs_permission(
    reports: World,
) -> None:
    world = reports
    a = world.a
    mine = await _create(world, a, a.tech_a)
    assert mine["shared"] is False
    hidden = await world.call("GET", f"{BASE}/{mine['ref']}", a, a.tech_b)
    assert hidden.status_code == 404  # AC1: only the owner
    refused = await _patch(world, a, a.tech_a, mine, shared=True)
    assert refused.status_code == 403  # REQ-DSH-029 AC1: technicians may not share
    assert refused.json()["params"]["permission"] == "dashboards.share"

    shared = await _create(world, a, a.admin, shared=True)
    seen = (await world.call("GET", BASE, a, a.tech_b)).json()["items"]
    entry = next(d for d in seen if d["ref"] == shared["ref"])
    assert entry["shared"] is True  # AC2: in everyone's picker
    assert entry["can_edit"] is False
    other = await world.call("GET", f"{BASE}/{shared['ref']}", world.b, world.b.admin)
    assert other.status_code == 404  # never another tenant's


async def test_req_dsh_021_copy_gives_an_independent_private_dashboard(reports: World) -> None:
    world = reports
    a = world.a
    original = await world.call("GET", f"{BASE}/builtin:service_desk", a, a.tech_a)
    body = original.json()["body"]
    copy = await _create(
        world, a, a.tech_a, name="My desk", copied_from="builtin:service_desk", body=body
    )
    assert copy["shared"] is False
    assert copy["copied_from"] == "builtin:service_desk"
    assert copy["can_edit"] is True
    assert len(copy["body"]["widgets"]) == len(body["widgets"])
    changed = await _patch(
        world, a, a.tech_a, copy, body={**copy["body"], "widgets": copy["body"]["widgets"][:1]}
    )
    assert changed.status_code == 200, changed.text
    again = await world.call("GET", f"{BASE}/builtin:service_desk", a, a.tech_a)
    assert len(again.json()["body"]["widgets"]) == len(body["widgets"])  # AC2: independent


# --- REQ-DSH-009, 019: widgets are checked like reports; layout saves with If-Match --------------


async def test_req_dsh_009_widgets_are_checked_and_me_is_the_saver(reports: World) -> None:
    world = reports
    a = world.a
    bad = await world.call(
        "POST",
        BASE,
        a,
        a.tech_a,
        json={
            "name": "Bad",
            "body": {"widgets": [_kpi(filter={"field": "nope", "op": "eq", "value": 1})]},
        },
        headers={**CONSOLE, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert bad.status_code == 422, bad.text
    mine = await _create(
        world,
        a,
        a.tech_a,
        body={"widgets": [_kpi(filter={"field": "technician_id", "op": "eq", "value": ME})]},
    )
    assert mine["body"]["widgets"][0]["report"]["filter"]["value"] == ME  # kept for each viewer
    overlapping = await world.call(
        "POST",
        BASE,
        a,
        a.tech_a,
        json={"name": "Twice", "body": {"widgets": [_kpi("w"), _kpi("w")]}},
        headers={**CONSOLE, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert overlapping.status_code == 422


async def test_req_dsh_019_layout_saves_with_if_match_history_and_event(reports: World) -> None:
    world = reports
    a = world.a
    board = await _create(world, a, a.tech_a)
    moved = {
        "widgets": [{**board["body"]["widgets"][0], "place": {"x": 6, "y": 1, "w": 6, "h": 3}}],
        "filters": {"days": 30},
    }
    saved = await _patch(world, a, a.tech_a, board, body=moved)
    assert saved.status_code == 200, saved.text
    assert saved.json()["body"]["widgets"][0]["place"]["x"] == 6
    stale = await _patch(world, a, a.tech_a, board, name="Old")  # the version read before
    assert stale.status_code == 409
    events = await world.sql(
        "SELECT event_type, envelope FROM outbox_events WHERE tenant_id = $1"
        " AND aggregate_id = $2 ORDER BY id",
        a.tenant,
        board["ref"],
    )
    assert [e["event_type"] for e in events] == [
        "analytics.dashboard.saved",
        "analytics.dashboard.saved",
    ]
    payload = json.loads(events[-1]["envelope"])["payload"]
    assert payload["changed_fields"] == ["body"]
    assert "name" not in payload  # ids and changed fields only (rule c)
    history = await world.sql(
        "SELECT kind FROM field_changes WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        uuid.UUID(board["ref"]),
    )
    assert {h["kind"] for h in history} >= {"created", "updated"}


# --- REQ-DSH-005: favourites first ---------------------------------------------------------------


async def test_req_dsh_005_ac1_starring_moves_to_favourites_at_once(reports: World) -> None:
    world = reports
    a = world.a
    starred = await world.call("PUT", f"{BASE}/favourites/builtin:my_work", a, a.tech_a)
    assert starred.status_code == 204, starred.text
    listed = (await world.call("GET", BASE, a, a.tech_a)).json()
    assert listed["favourites"] == ["builtin:my_work"]
    hidden = await world.call("PUT", f"{BASE}/favourites/{uuid.uuid4()}", a, a.tech_a)
    assert hidden.status_code == 404
    await world.call("DELETE", f"{BASE}/favourites/builtin:my_work", a, a.tech_a)
    assert (await world.call("GET", BASE, a, a.tech_a)).json()["favourites"] == []


# --- REQ-DSH-016, 028: live, and a viewer who loses access hears it ------------------------------


async def test_req_dsh_028_ac2_unsharing_reaches_former_viewers_private_only_the_owner(
    reports: World,
) -> None:
    world = reports
    a = world.a
    from app.modules.analytics.service.realtime import ROUTES  # noqa: PLC0415 - the module's routes

    route = next(r for r in ROUTES if "analytics.dashboard.saved" in r.event_types)
    board = await _create(world, a, a.admin, shared=True)
    await _patch(world, a, a.admin, board, shared=False)
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND aggregate_id = $2 ORDER BY id",
        a.tenant,
        board["ref"],
    )
    channels = []
    for row in rows:
        envelope = EventEnvelope.model_validate(json.loads(row["envelope"]))
        effects = await route.route(envelope, None)  # type: ignore[arg-type]  # unused session
        channels.append([p.channel for p in effects.publications])
    created, unshared = channels
    assert "broadcast" in str(created[0])  # shared: everyone refetches the picker
    assert "broadcast" in str(unshared[0])  # un-shared: former viewers hear it, then get 404
    private = await _create(world, a, a.tech_a)
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND aggregate_id = $2",
        a.tenant,
        private["ref"],
    )
    envelope = EventEnvelope.model_validate(json.loads(rows[0]["envelope"]))
    effects = await route.route(envelope, None)  # type: ignore[arg-type]  # unused session
    assert [str(a.tech_a) in str(p.channel) for p in effects.publications] == [True]


# --- RLS: every new table -------------------------------------------------------------------------


async def test_dashboard_tables_are_isolated_by_rls(reports: World) -> None:
    world = reports
    a, b = world.a, world.b
    board = await _create(world, a, a.admin, shared=True)
    await world.call("PUT", f"{BASE}/favourites/{board['ref']}", a, a.admin)
    await world.call(
        "PUT", f"{BASE}/role-homes/technician", a, a.admin, json={"dashboard_ref": board["ref"]}
    )
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in ("dashboards", "dashboard_preferences", "dashboard_role_defaults"):
            count = await session.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608 - fixed names
            assert count == 0, table
        updated = await session.execute(
            text("UPDATE dashboards SET shared = false WHERE id = :id"),
            {"id": uuid.UUID(board["ref"])},
        )
        assert updated.rowcount == 0
        changed = await session.execute(
            text("UPDATE dashboard_role_defaults SET dashboard_ref = 'builtin:my_work'")
        )
        assert changed.rowcount == 0
    assert (await world.call("GET", f"{BASE}/{board['ref']}", b, b.admin)).status_code == 404
    assert await _home(world, a, a.tech_a) == board["ref"]  # org A's role home still applies
