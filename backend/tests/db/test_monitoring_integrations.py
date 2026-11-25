"""MonetX connections, topology import and CI health (WP-053 S6; migration 0207).

Real PostgreSQL on the incident world (two new organisations per test: rule 5h), MonetX as the
in-process stand-in (tests/monetx_fake.py) behind the client's transport. Covers:
- rule 5a: the four tables are isolated per tenant;
- the token never comes back (`has_secret` only); If-Match; Idempotency-Key; audited;
- the import: new devices become CIs, the CMDB's source precedence keeps a person's edit,
  stale after one missed run, ended (end-of-life state, never deleted) after three, and only
  links the import made are ever removed;
- health: only CIs the reader may see; one MonetX read for many readers (single flight); the
  breaker answers `unknown` with `monitoring_unreachable`; without the licence feature every CI
  is `unmonitored` and MonetX is never asked; a private address on SaaS is refused by egress
  (`monitoring_not_reachable_from_saas`);
- the health event carries the state code only.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import EntitlementRequired
from app.core.tenancy import TenantContext
from app.modules import licensing
from app.modules.monitoring_integrations.domain.monitoring import NOT_REACHABLE_FROM_SAAS
from app.modules.monitoring_integrations.infra.models import MonitoredDevice
from app.modules.monitoring_integrations.infra.monetx_client import (
    EgressTransport,
    MonitoringUnavailableError,
)
from app.modules.monitoring_integrations.service import connections, health, topology
from app.shared.egress import Allowance
from app.shared.files.keyring import KeyRing
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_files_api import audit_actions
from tests.db.test_incidents_api import Org, World
from tests.monetx_fake import FakeMonetX

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used
pytestmark = [pytest.mark.db, MODULE_LOOP]

BASE = "/monitoring/connections"
TOKEN = "monetx-t0ken-0123456789abcdef"
TABLES = (
    "monitoring_connections",
    "monitoring_topology_runs",
    "monitoring_devices",
    "monitoring_links",
)


@pytest.fixture
async def monetx(world: World) -> AsyncIterator[FakeMonetX]:
    """A stand-in MonetX for every connection, a key ring for the token, a fresh cache."""
    fake = FakeMonetX()
    settings = world.app.state.settings
    world.app.state.settings = settings.model_copy(
        update={"files_keys": SecretStr(KeyRing.generate())}
    )
    connections.set_transport_factory(lambda _row, _token, _settings: fake)
    health.use_cache(None)
    yield fake
    connections.set_transport_factory(None)
    health.use_cache(None)
    world.app.state.settings = settings


async def _add(world: World, org: Org, **body: Any) -> httpx.Response:  # noqa: ANN401 - JSON
    values = {"name": "Alpha MonetX", "base_url": "https://monetx.example.com", "token": TOKEN}
    return await world.call(
        "POST",
        BASE,
        org,
        org.admin,
        json=values | body,
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )


async def _import(world: World, org: Org) -> int:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        return await topology.run_tenant(session, world.app.state.settings)


async def _devices(world: World, org: Org) -> dict[str, MonitoredDevice]:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        rows = await session.scalars(select(MonitoredDevice))
        return {r.external_id: r for r in rows}


async def _ci(world: World, org: Org, ci_id: uuid.UUID) -> dict[str, Any]:
    found = await world.call("GET", f"/cmdb/cis/{ci_id}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


async def _run_now(world: World, org: Org, connection_id: str) -> None:
    asked = await world.call("POST", f"{BASE}/{connection_id}/runs", org, org.admin)
    assert asked.status_code == 202, asked.text


# --- tenant isolation (rule a) --------------------------------------------------------------------


async def _seed_all_four(world: World, org: Org) -> None:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        connection = uuid.uuid4()
        params = {"t": org.tenant, "c": connection}
        await session.execute(
            text(
                "INSERT INTO monitoring_connections (id, tenant_id, name, base_url) "
                "VALUES (:c, :t, :n, 'https://m.example.com')"
            ),
            {**params, "n": f"RLS {connection.hex[:8]}"},
        )
        await session.execute(
            text(
                "INSERT INTO monitoring_topology_runs (id, tenant_id, connection_id, started_at) "
                "VALUES (:i, :t, :c, now())"
            ),
            {**params, "i": uuid.uuid4()},
        )
        await session.execute(
            text(
                "INSERT INTO monitoring_devices (id, tenant_id, connection_id, external_id, ci_id) "
                "VALUES (:i, :t, :c, 'd1', :ci)"
            ),
            {**params, "i": uuid.uuid4(), "ci": uuid.uuid4()},
        )
        await session.execute(
            text(
                "INSERT INTO monitoring_links "
                "(id, tenant_id, connection_id, external_id, relationship_id) "
                "VALUES (:i, :t, :c, 'l1', :r)"
            ),
            {**params, "i": uuid.uuid4(), "r": uuid.uuid4()},
        )


@pytest.mark.parametrize("table", TABLES)
async def test_tenant_b_neither_sees_nor_changes_tenant_as_rows(world: World, table: str) -> None:
    await _seed_all_four(world, world.a)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() > 0  # noqa: S608 - fixed table names
    async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
        params = {"a": world.a.tenant}
        seen = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"),  # noqa: S608 - fixed table names
            params,
        )
        assert seen.scalar_one() == 0
        # monitoring_links is insert/delete only (the app has no UPDATE on it): try the delete.
        write = (
            f"DELETE FROM {table} WHERE tenant_id = :a"  # noqa: S608 - fixed table names
            if table == "monitoring_links"
            else f"UPDATE {table} SET updated_at = now() WHERE tenant_id = :a"  # noqa: S608
        )
        changed = await session.execute(text(write), params)
        assert changed.rowcount == 0


async def test_tenant_b_cannot_write_a_connection_for_tenant_a(world: World) -> None:
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO monitoring_connections (id, tenant_id, name, base_url) "
                    "VALUES (:i, :a, 'Sneaky', 'https://m.example.com')"
                ),
                {"i": uuid.uuid4(), "a": world.a.tenant},
            )


async def test_a_device_cannot_point_at_another_tenants_connection(world: World) -> None:
    await _seed_all_four(world, world.a)
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        theirs = (
            await session.execute(text("SELECT id FROM monitoring_connections LIMIT 1"))
        ).scalar_one()
    with pytest.raises(DBAPIError):
        async with world.app.state.db.tenant_session(TenantContext(world.b.tenant)) as session:
            await session.execute(
                text(
                    "INSERT INTO monitoring_devices "
                    "(id, tenant_id, connection_id, external_id, ci_id) "
                    "VALUES (:i, :b, :c, 'd9', :ci)"
                ),
                {"i": uuid.uuid4(), "b": world.b.tenant, "c": theirs, "ci": uuid.uuid4()},
            )


# --- connections ----------------------------------------------------------------------------------


async def test_the_token_never_comes_back_and_changes_need_if_match(
    world: World, monetx: FakeMonetX
) -> None:
    del monetx
    created = await _add(world, world.a)
    assert created.status_code == 201, created.text
    assert TOKEN not in created.text
    out = created.json()
    assert out["has_secret"] is True
    one = await world.call("GET", f"{BASE}/{out['id']}", world.a, world.a.admin)
    assert TOKEN not in one.text
    listed = await world.call("GET", BASE, world.a, world.a.admin)
    assert TOKEN not in listed.text
    body = {"name": "Renamed", "base_url": "https://monetx.example.com"}
    stale = await world.call(
        "PUT",
        f"{BASE}/{out['id']}",
        world.a,
        world.a.admin,
        json=body,
        headers={"If-Match": '"99"'},
    )
    assert stale.status_code == 409, stale.text
    changed = await world.call(
        "PUT",
        f"{BASE}/{out['id']}",
        world.a,
        world.a.admin,
        json=body,
        headers={"If-Match": f'"{out["version"]}"'},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["has_secret"] is True  # no token sent: the old one is kept
    actions = await audit_actions(world, world.a)
    assert {"monitoring.connection_created", "monitoring.connection_changed"} <= set(actions)


async def test_only_monitoring_managers_reach_connections(world: World, monetx: FakeMonetX) -> None:
    del monetx
    denied = await world.call("GET", BASE, world.a, world.a.tech_a)
    assert denied.status_code == 403, denied.text


async def test_another_tenant_gets_404(world: World, monetx: FakeMonetX) -> None:
    del monetx
    created = (await _add(world, world.a)).json()
    found = await world.call("GET", f"{BASE}/{created['id']}", world.b, world.b.admin)
    assert found.status_code == 404, found.text


async def test_a_connection_test_reads_once_and_reports_a_code(
    world: World, monetx: FakeMonetX
) -> None:
    created = (await _add(world, world.a)).json()
    ok = await world.call("GET", f"{BASE}/{created['id']}/test", world.a, world.a.admin)
    assert ok.json() == {"ok": True, "reason": None}
    monetx.fail = "monitoring_refused"
    refused = await world.call("GET", f"{BASE}/{created['id']}/test", world.a, world.a.admin)
    assert refused.json() == {"ok": False, "reason": "monitoring_refused"}


async def test_a_private_monetx_is_refused_from_saas_by_egress(world: World) -> None:
    """Egress (not a deployment-mode branch, rule f) blocks a private address."""
    transport = EgressTransport(
        base_url="https://10.0.0.5",
        token=TOKEN,
        allowance=Allowance(),  # SaaS opens no private range (installation configuration only)
        tenant_id=world.a.tenant,
    )
    with pytest.raises(MonitoringUnavailableError) as caught:
        await transport.read("/api/v1/devices", {"limit": "1"})
    assert caught.value.code == NOT_REACHABLE_FROM_SAAS


async def test_without_the_feature_a_connection_cannot_be_added(
    world: World, monetx: FakeMonetX, monkeypatch: pytest.MonkeyPatch
) -> None:
    del monetx

    async def refuse(_tenant: uuid.UUID, _feature: object) -> None:
        raise EntitlementRequired(params={"feature": "monetx_integration"})

    monkeypatch.setattr(licensing, "require_feature", refuse)
    refused = await _add(world, world.a)
    assert refused.status_code == 403, refused.text


# --- topology import ------------------------------------------------------------------------------


async def test_the_import_makes_cis_keeps_a_persons_edit_and_never_deletes(
    world: World, monetx: FakeMonetX
) -> None:
    a = world.a
    monetx.devices = [
        {"id": "d1", "name": "core-sw-1", "kind": "switch"},
        {"id": "d2", "name": "app-01", "kind": "vm"},
    ]
    created = (await _add(world, a)).json()
    await _run_now(world, a, created["id"])
    assert await _import(world, a) == 1
    devices = await _devices(world, a)
    assert set(devices) == {"d1", "d2"}
    switch = await _ci(world, a, devices["d1"].ci_id)
    assert switch["name"] == "core-sw-1"
    assert switch["source"] == "monetx"

    # A person renames it: a manual edit outranks monetx by default (S4 precedence).
    edited = await world.call(
        "PATCH",
        f"/cmdb/cis/{switch['id']}",
        a,
        a.admin,
        json={"name": "Core switch"},
        headers={"If-Match": f'"{switch["version"]}"'},
    )
    assert edited.status_code == 200, edited.text
    monetx.devices = [{"id": "d1", "name": "core-sw-1-renamed", "kind": "switch"}]
    await _run_now(world, a, created["id"])
    await _import(world, a)
    assert (await _ci(world, a, devices["d1"].ci_id))["name"] == "Core switch"

    # d2 missed one run: stale. Two more: ended, its CI end-of-life, still there.
    assert (await _devices(world, a))["d2"].state == "stale"
    for _ in range(2):
        await _run_now(world, a, created["id"])
        await _import(world, a)
    d2 = (await _devices(world, a))["d2"]
    assert (d2.state, d2.missed_runs) == ("ended", 3)
    ci = await _ci(world, a, d2.ci_id)
    states = await world.call("GET", "/cmdb/ci-states", a, a.admin)
    category = {s["id"]: s["category"] for s in states.json()["items"]}
    assert category[ci["state_id"]] == "end_of_life"


async def test_only_links_the_import_made_are_ever_removed(
    world: World, monetx: FakeMonetX
) -> None:
    a = world.a
    monetx.devices = [
        {"id": "d1", "name": "edge-1", "kind": "router"},
        {"id": "d2", "name": "edge-2", "kind": "router"},
        {"id": "d3", "name": "edge-3", "kind": "router"},
    ]
    monetx.links = [{"id": "l12", "from": "d1", "to": "d2"}]
    created = (await _add(world, a)).json()
    await _run_now(world, a, created["id"])
    await _import(world, a)
    devices = await _devices(world, a)

    # A person draws d2 → d3 by hand.
    types = await world.call("GET", "/cmdb/relationship-types", a, a.admin)
    connected = next(t for t in types.json()["items"] if t["code"] == "connected_to")
    drawn = await world.call(
        "POST",
        f"/cmdb/cis/{devices['d2'].ci_id}/relationships",
        a,
        a.admin,
        json={"type_id": connected["id"], "targets": [str(devices["d3"].ci_id)]},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert drawn.status_code == 201, drawn.text

    # MonetX drops l12 and never knew d2 → d3: only l12 goes.
    monetx.links = []
    await _run_now(world, a, created["id"])
    await _import(world, a)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        live = {
            (str(f), str(t))
            for f, t in await session.execute(
                text("SELECT from_ci_id, to_ci_id FROM cmdb_relationships WHERE deleted_at IS NULL")
            )
        }
    assert (str(devices["d2"].ci_id), str(devices["d3"].ci_id)) in live  # drawn by hand: kept
    assert (str(devices["d1"].ci_id), str(devices["d2"].ci_id)) not in live  # the import's: gone


# --- health ---------------------------------------------------------------------------------------


async def _monitored(world: World, monetx: FakeMonetX) -> dict[str, MonitoredDevice]:
    monetx.devices = [
        {"id": "d1", "name": "db-01", "kind": "server"},
        {"id": "d2", "name": "db-02", "kind": "server"},
    ]
    monetx.health = {
        "d1": {"status": "critical", "problem_count": 2, "since": "2026-11-25T10:00:00+00:00"},
        "d2": {"status": "ok", "problem_count": 0},
    }
    created = (await _add(world, world.a)).json()
    await _run_now(world, world.a, created["id"])
    await _import(world, world.a)
    return await _devices(world, world.a)


def _ids(devices: dict[str, MonitoredDevice]) -> list[tuple[str, str]]:
    return [("ci_ids", str(d.ci_id)) for d in devices.values()]


async def test_health_maps_states_and_one_read_serves_many_readers(
    world: World, monetx: FakeMonetX
) -> None:
    devices = await _monitored(world, monetx)
    before = monetx.reads_of("/api/v1/health")
    for _ in range(3):
        found = await world.call(
            "GET", "/monitoring/health", world.a, world.a.admin, params=_ids(devices)
        )
        assert found.status_code == 200, found.text
    states = {i["ci_id"]: (i["state"], i["problem_count"]) for i in found.json()["items"]}
    assert states[str(devices["d1"].ci_id)] == ("down", 2)
    assert states[str(devices["d2"].ci_id)] == ("up", 0)
    assert monetx.reads_of("/api/v1/health") - before == 1  # cached 15 s, single flight


async def test_health_leaves_out_cis_the_reader_may_not_see(
    world: World, monetx: FakeMonetX
) -> None:
    devices = await _monitored(world, monetx)
    unseen = uuid.uuid4()
    found = await world.call(
        "GET",
        "/monitoring/health",
        world.b,
        world.b.admin,
        params=[*_ids(devices), ("ci_ids", str(unseen))],
    )
    assert found.status_code == 200, found.text
    assert found.json()["items"] == []  # another tenant's CIs and unknown IDs: absent


async def test_an_open_breaker_answers_unknown_without_asking(
    world: World, monetx: FakeMonetX
) -> None:
    devices = await _monitored(world, monetx)
    monetx.fail = "monitoring_unreachable"
    health.use_cache(None)  # a clean start (it also resets the breakers)
    for _ in range(3):  # the threshold; each read misses the cache, the breaker kept
        health._CACHE[0] = health.MemoryCache()  # noqa: SLF001 - an empty cache only
        await world.call("GET", "/monitoring/health", world.a, world.a.admin, params=_ids(devices))
    asked = monetx.reads_of("/api/v1/health")
    health._CACHE[0] = health.MemoryCache()  # noqa: SLF001 - an empty cache, the breaker kept
    found = await world.call(
        "GET", "/monitoring/health", world.a, world.a.admin, params=_ids(devices)
    )
    assert {(i["state"], i["reason"]) for i in found.json()["items"]} == {
        ("unknown", "monitoring_unreachable")
    }
    assert monetx.reads_of("/api/v1/health") == asked


async def test_without_the_feature_every_ci_is_unmonitored_and_monetx_is_not_asked(
    world: World, monetx: FakeMonetX, monkeypatch: pytest.MonkeyPatch
) -> None:
    devices = await _monitored(world, monetx)

    async def lapsed(_tenant: uuid.UUID, _feature: object) -> bool:
        return False

    monkeypatch.setattr(licensing, "has_feature", lapsed)
    before = len(monetx.reads)
    found = await world.call(
        "GET", "/monitoring/health", world.a, world.a.admin, params=_ids(devices)
    )
    assert {i["state"] for i in found.json()["items"]} == {"unmonitored"}
    assert len(monetx.reads) == before


async def test_a_change_of_health_emits_the_state_code_only(
    world: World, monetx: FakeMonetX
) -> None:
    devices = await _monitored(world, monetx)
    await world.call("GET", "/monitoring/health", world.a, world.a.admin, params=_ids(devices))
    monetx.health["d1"] = {"status": "up", "problem_count": 0}
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        assert await health.refresh_tenant(session, world.app.state.settings) >= 1
    rows = await world.sql(
        "SELECT envelope->'payload' AS payload FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'monitoring_integrations.health.changed' ORDER BY created_at",
        world.a.tenant,
    )
    emitted = [json.loads(r["payload"]) for r in rows]
    assert emitted, "a change of health is an event"
    for data in emitted:  # IDs and the state code, nothing MonetX said beyond it
        assert set(data) <= {"event_id", "ci_id", "state", "occurred_at", "tenant_id"}, data
