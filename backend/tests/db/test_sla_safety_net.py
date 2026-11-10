"""The SLA safety net never lets one record stop the others (lane B, 2026-11-10).

On the shared stack one running timer on a record in the trash made `sla_fired` raise
NotFound, and with it every safety-net run, so no other late warning, breach or escalation
fired. Now each record fires in its own transaction; a record in the trash waits (it is
restored as it was); a record that is gone has its clocks stopped once, never retried.
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest

from app.core.tenancy import TenantContext
from app.modules.sla.service import timers
from app.modules.work_items.service import work_items as work_items_service
from app.shared.clock import FrozenClock
from tests.db import test_incidents_api
from tests.db.test_incidents_api import BASE, World
from tests.db.test_sla_clock import _p1, _targets

pytestmark = [pytest.mark.db, pytest.mark.valkey]
world = test_incidents_api.world  # the incident world fixture, reused


async def _states(world: World, record_id: uuid.UUID) -> set[str]:
    rows = await world.sql("SELECT state FROM sla_targets WHERE record_id = $1", record_id)
    return {r["state"] for r in rows}


async def test_one_bad_record_never_stops_the_rest_of_the_sweep(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = world.a
    live: dict[str, Any] = await _p1(world, a)
    failing: dict[str, Any] = await _p1(world, a)
    trashed: dict[str, Any] = await _p1(world, a)
    gone: dict[str, Any] = await _p1(world, a)
    # In the trash, through the API (REQ-WI-020).
    removed = await world.call(
        "DELETE",
        f"{BASE}/{trashed['id']}",
        a,
        a.admin,
        headers={"If-Match": f'"{trashed["version"]}"'},
    )
    assert removed.status_code == 204, removed.text
    # Gone for good: its clocks name a record that no longer exists (as after an erasure).
    erased = uuid.uuid4()
    await world.sql(
        "UPDATE sla_targets SET record_id = $1 WHERE tenant_id = $2 AND record_id = $3",
        erased,
        a.tenant,
        uuid.UUID(gone["id"]),
    )
    # One record whose firing fails outright: the sweep must go on past it.
    real_fire = timers.fire

    async def fire(session: Any, record_id: uuid.UUID, *, now: Any) -> Any:  # noqa: ANN401 - as timers.fire
        if record_id == uuid.UUID(failing["id"]):
            msg = "boom"
            raise RuntimeError(msg)
        return await real_fire(session, record_id, now=now)

    monkeypatch.setattr(timers, "fire", fire)
    late = (await _targets(world, live))["resolution:1"]["due_at"] + timedelta(hours=1)
    monkeypatch.setattr(timers, "system_clock", FrozenClock(late))

    await timers.safety_net(world.app.state.db, settings=None)  # type: ignore[arg-type]  # settings is unused

    assert "breached" in await _states(world, uuid.UUID(live["id"]))  # the others still fire
    assert await _states(world, erased) == {"stopped"}  # stopped once, never retried
    # In the trash: untouched, so it is restored exactly as it was.
    assert await _states(world, uuid.UUID(trashed["id"])) == {"running"}
    # A second sweep is quiet for the gone one: its clocks are stopped, nothing is late.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert erased not in await timers.overdue_records(session, late)


async def test_a_sweep_pages_past_records_it_skips(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skipped (trashed) records never crowd out the others behind a fixed first page."""
    a = world.a
    first: dict[str, Any] = await _p1(world, a)
    second: dict[str, Any] = await _p1(world, a)
    monkeypatch.setattr(timers, "SAFETY_NET_BATCH", 1)
    late = (await _targets(world, first))["resolution:1"]["due_at"] + timedelta(hours=1)
    monkeypatch.setattr(timers, "system_clock", FrozenClock(late))
    # The default batch is read when the function is defined; give the page size explicitly.
    real = timers.overdue_records

    async def one_at_a_time(session: Any, before: Any, *, limit: int = 1, after: Any = None) -> Any:  # noqa: ANN401 - as timers.overdue_records
        del limit
        return await real(session, before, limit=1, after=after)

    monkeypatch.setattr(timers, "overdue_records", one_at_a_time)
    await timers.safety_net(world.app.state.db, settings=None)  # type: ignore[arg-type]  # settings is unused
    for item in (first, second):
        assert "breached" in await _states(world, uuid.UUID(item["id"]))


async def test_a_trashed_record_waits_then_fires_after_its_restore(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lane B's #353 review: in the trash nothing fires; restored, it fires as it was."""
    a = world.a
    item: dict[str, Any] = await _p1(world, a)
    removed = await world.call(
        "DELETE", f"{BASE}/{item['id']}", a, a.admin, headers={"If-Match": f'"{item["version"]}"'}
    )
    assert removed.status_code == 204, removed.text
    late = (await _targets(world, item))["resolution:1"]["due_at"] + timedelta(hours=1)
    monkeypatch.setattr(timers, "system_clock", FrozenClock(late))
    await timers.safety_net(world.app.state.db, settings=None)  # type: ignore[arg-type]  # settings is unused
    assert await _states(world, uuid.UUID(item["id"])) == {"running"}
    trashed = await world.sql(
        "SELECT version FROM work_items WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    restored = await world.call(
        "POST",
        f"{BASE}/{item['id']}/restore",
        a,
        a.admin,
        headers={"If-Match": f'"{trashed[0]["version"]}"'},
    )
    assert restored.status_code == 200, restored.text
    await timers.safety_net(world.app.state.db, settings=None)  # type: ignore[arg-type]  # settings is unused
    assert "breached" in await _states(world, uuid.UUID(item["id"]))


async def test_a_gone_record_stops_once_and_a_second_sweep_changes_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = world.a
    item: dict[str, Any] = await _p1(world, a)
    erased = uuid.uuid4()
    await world.sql(
        "UPDATE sla_targets SET record_id = $1 WHERE tenant_id = $2 AND record_id = $3",
        erased,
        a.tenant,
        uuid.UUID(item["id"]),
    )
    late = (await _targets(world, item | {"id": str(erased)}))["resolution:1"]["due_at"]
    monkeypatch.setattr(timers, "system_clock", FrozenClock(late + timedelta(hours=1)))
    await timers.safety_net(world.app.state.db, settings=None)  # type: ignore[arg-type]  # settings is unused

    async def snapshot() -> list[tuple[str, int]]:
        rows = await world.sql(
            "SELECT state, version FROM sla_targets WHERE record_id = $1 ORDER BY id", erased
        )
        return [(r["state"], r["version"]) for r in rows]

    first = await snapshot()
    assert {state for state, _ in first} == {"stopped"}
    runs = await world.sql(
        "SELECT r.state FROM sla_escalation_runs r JOIN sla_targets t ON t.id = r.target_id"
        " WHERE t.record_id = $1",
        erased,
    )
    assert {r["state"] for r in runs} <= {"cancelled", "ran"}
    await timers.safety_net(world.app.state.db, settings=None)  # type: ignore[arg-type]  # settings is unused
    assert await snapshot() == first  # nothing moved: never retried


async def test_a_restore_records_where_the_sla_stands_and_fires_what_fell_due(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Haider, 2026-11-10: the clock keeps running in the trash; the restore says so.

    restored_at holds the latest restore (a second one moves it); each restore's history line
    names each open target's standing; what fell due is breached at once, not at the next sweep;
    SLA reports may filter on restored_at.
    """
    a = world.a
    item: dict[str, Any] = await _p1(world, a)
    due = (await _targets(world, item))["resolution:1"]["due_at"]
    removed = await world.call(
        "DELETE", f"{BASE}/{item['id']}", a, a.admin, headers={"If-Match": f'"{item["version"]}"'}
    )
    assert removed.status_code == 204, removed.text
    later = due + timedelta(hours=3)
    monkeypatch.setattr(work_items_service, "_now", lambda: later)
    trashed = (
        await world.sql(
            "SELECT version FROM work_items WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            uuid.UUID(item["id"]),
        )
    )[0]["version"]
    restored = await world.call(
        "POST",
        f"{BASE}/{item['id']}/restore",
        a,
        a.admin,
        headers={"If-Match": f'"{trashed}"'},
    )
    assert restored.status_code == 200, restored.text
    row = (
        await world.sql(
            "SELECT restored_at FROM work_items WHERE tenant_id = $1 AND id = $2",
            a.tenant,
            uuid.UUID(item["id"]),
        )
    )[0]
    assert row["restored_at"] == later
    restore_lines = [
        c["new"]
        for h in await world.history(a, item)
        if h["kind"] == "restored"
        for c in h["changes"]
        if c["field"] == "sla_on_restore"
    ]
    assert any(line.startswith("resolution:overdue:") for line in restore_lines)
    # Breached now: the restore fired what fell due while it was in the trash.
    assert "breached" in await _states(world, uuid.UUID(item["id"]))
    # Reports may filter on it ("restored from trash").
    from app.modules.work_items.service.access import FIELDS  # noqa: PLC0415 - one check

    assert "restored_at" in FIELDS.fields
