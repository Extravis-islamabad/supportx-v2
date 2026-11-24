"""CI downtimes (WP-053 S5b; REQ-CMDB-020; migration 0198), on real PostgreSQL and Valkey.

- RLS: tenant B neither reads nor changes tenant A's downtimes (rule a).
- From work_items: a downtime event mirrors onto each CI and business service it names; the same
  event twice, or an older version, changes nothing; a CI dropped from the list, or a removed
  downtime, leaves the CI; an ID that is no CI of the tenant is skipped (AC2).
- The clock: a scheduled downtime becomes active at its start and completed at its end, and a
  second sweep at the same moment moves nothing (claim-once, the coordinator's condition 2).
- By hand: record, change and remove with the right, If-Match and an Idempotency-Key; history
  and the outbox event; 404 for a CI the reader may not see; a synced downtime is read-only.

The work_items side (lane A's `work_items.downtime.changed`) is fed here by its agreed shape, so
these tests stand alone; lane A's PR tests their emitting end.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text

from app.core.tenancy import TenantContext
from app.modules.cmdb.infra.models import CiDowntime
from app.modules.cmdb.service import downtimes
from app.shared.events import EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_cmdb_relationships import _given, _made
from tests.db.test_incidents_api import Org, World, problem
from tests.db.test_knowledge_api import _match, _new

pytestmark = [pytest.mark.db, MODULE_LOOP]
__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

TABLE = "cmdb_ci_downtimes"
HOUR = timedelta(hours=1)
BASE = "/cmdb/cis"


def _event(
    downtime_id: uuid.UUID,
    version: int,
    ci_ids: list[str],
    **extra: Any,  # noqa: ANN401 - JSON
) -> EventEnvelope:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "work_item_id": str(uuid.uuid4()),
        "type": "change",
        "downtime_id": str(downtime_id),
        "version": version,
        "phase": "planned",
        "kind": "full_outage",
        "starts_at": (now + HOUR).isoformat(),
        "ends_at": (now + 2 * HOUR).isoformat(),
        "ci_ids": ci_ids,
        "service_ids": [],
        "source_work_item_id": None,
        "deleted": False,
        **extra,
    }
    return EventEnvelope.model_construct(payload=payload)


async def _feed(world: World, org: Org, envelope: EventEnvelope) -> None:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await downtimes.on_downtime_changed(envelope, session)


async def _rows(world: World, org: Org, downtime_id: uuid.UUID) -> list[CiDowntime]:
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        return list(
            await session.scalars(
                select(CiDowntime).where(
                    CiDowntime.source_downtime_id == downtime_id,
                    CiDowntime.deleted_at.is_(None),
                )
            )
        )


async def test_the_downtimes_table_is_isolated_by_rls(world: World) -> None:
    a, b = world.a, world.b
    ci = await _made(world, a, f"RLS box {uuid.uuid4().hex[:6]}", "server")
    await _feed(world, a, _event(uuid.uuid4(), 1, [ci["id"]]))
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (await session.execute(text(f"SELECT count(*) FROM {TABLE}"))).scalar_one() > 0  # noqa: S608 - a fixed table name
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = await session.execute(
            text(f"SELECT count(*) FROM {TABLE} WHERE tenant_id = :a"),  # noqa: S608 - a fixed table name
            {"a": a.tenant},
        )
        assert seen.scalar_one() == 0
        changed = await session.execute(
            text(f"UPDATE {TABLE} SET state = state WHERE tenant_id = :a"),  # noqa: S608 - a fixed table name
            {"a": a.tenant},
        )
        assert changed.rowcount == 0
    assert problem(await world.call("GET", f"{BASE}/{ci['id']}/downtimes", b, b.admin)) == (
        404,
        "cmdb_ci_not_found",
    )


async def test_a_change_downtime_mirrors_once_and_follows_its_edits(world: World) -> None:
    """AC2, and idempotency: the same event twice, or an older one, changes nothing."""
    a = world.a
    tag = uuid.uuid4().hex[:6]
    web = await _made(world, a, f"Web {tag}", "server")
    db = await _made(world, a, f"Db {tag}", "database")
    service = await _made(world, a, f"Shop {tag}", "business_service")
    downtime = uuid.uuid4()
    first = _event(
        downtime, 1, [web["id"], db["id"], str(uuid.uuid4())], service_ids=[service["id"]]
    )
    await _feed(world, a, first)
    await _feed(world, a, first)  # redelivered: the processed_events claim, and the version
    rows = await _rows(world, a, downtime)
    assert sorted(str(r.ci_id) for r in rows) == sorted([web["id"], db["id"], service["id"]])
    assert {r.state for r in rows} == {"scheduled"}
    assert {r.source for r in rows} == {"change"}
    assert {r.version for r in rows} == {1}  # the replay moved nothing

    later = datetime.now(UTC) + 3 * HOUR
    moved = _event(downtime, 2, [web["id"]], starts_at=later.isoformat(), ends_at=None)
    await _feed(world, a, moved)
    rows = await _rows(world, a, downtime)
    assert [str(r.ci_id) for r in rows] == [web["id"]]  # db and the service dropped out
    assert rows[0].starts_at == later
    assert rows[0].ends_at is None
    assert rows[0].source_version == 2

    await _feed(world, a, _event(downtime, 1, [web["id"], db["id"]]))  # older: ignored
    assert [str(r.ci_id) for r in await _rows(world, a, downtime)] == [web["id"]]

    await _feed(world, a, _event(downtime, 3, [web["id"]], deleted=True))  # removed at source
    assert await _rows(world, a, downtime) == []


async def test_the_clock_moves_each_downtime_once(world: World) -> None:
    """AC1: active at its start without a refresh; a second sweep moves nothing (claim-once)."""
    a = world.a
    ci = await _made(world, a, f"Clock box {uuid.uuid4().hex[:6]}", "server")
    downtime = uuid.uuid4()
    await _feed(world, a, _event(downtime, 1, [ci["id"]]))
    [row] = await _rows(world, a, downtime)
    starts, ends = row.starts_at, row.ends_at
    assert ends is not None
    db = world.app.state.db
    for at, wanted in ((starts, "active"), (ends, "completed")):
        async with db.tenant_session(TenantContext(a.tenant)) as session:
            assert await downtimes.sweep_tenant(session, at) >= 1
        async with db.tenant_session(TenantContext(a.tenant)) as session:
            assert await downtimes.sweep_tenant(session, at) == 0  # nothing left to move
        [row] = await _rows(world, a, downtime)
        assert row.state == wanted, at
    events = await world.sql(
        "SELECT envelope->'payload'->>'state' AS state FROM outbox_events"
        " WHERE event_type = 'cmdb.downtime.changed'"
        " AND envelope->'payload'->>'downtime_id' = $1"
        " AND envelope->'payload'->>'change' = 'state' ORDER BY id",
        str(row.id),
    )
    assert [e["state"] for e in events] == ["active", "completed"]  # one event per move


async def test_a_downtime_by_hand_is_recorded_changed_and_removed(world: World) -> None:
    a = world.a
    ci = await _made(world, a, f"Hand box {uuid.uuid4().hex[:6]}", "server")
    starts = datetime.now(UTC) + HOUR
    body = {
        "starts_at": starts.isoformat(),
        "ends_at": (starts + HOUR).isoformat(),
        "kind": "maintenance",
        "description": "Disk swap",
    }
    path = f"{BASE}/{ci['id']}/downtimes"
    key = _new()
    made = await world.call("POST", path, a, a.admin, json=body, headers=key)
    assert made.status_code == 201, made.text
    again = await world.call("POST", path, a, a.admin, json=body, headers=key)
    assert again.json()["id"] == made.json()["id"]  # a retry with the key: the same downtime
    item = made.json()
    assert (item["source"], item["state"], item["editable"]) == ("manual", "scheduled", True)

    listed = (await world.call("GET", path, a, a.admin)).json()
    assert [d["id"] for d in listed["items"]] == [item["id"]]
    assert listed["counts"] == {"scheduled": 1, "active": 0, "completed": 0}

    stale = await world.call(
        "PATCH", f"{path}/{item['id']}", a, a.admin, json={"kind": "x"}, headers=_match(99)
    )
    assert problem(stale)[1] == "version_conflict"
    wrong = await world.call(
        "PATCH",
        f"{path}/{item['id']}",
        a,
        a.admin,
        json={"ends_at": (starts - HOUR).isoformat()},
        headers=_match(item["version"]),
    )
    assert wrong.status_code == 422, wrong.text
    changed = await world.call(
        "PATCH",
        f"{path}/{item['id']}",
        a,
        a.admin,
        json={"description": "Disk and fan swap"},
        headers=_match(item["version"]),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == item["version"] + 1

    removed = await world.call(
        "DELETE", f"{path}/{item['id']}", a, a.admin, headers=_match(changed.json()["version"])
    )
    assert removed.status_code == 204, removed.text
    assert (await world.call("GET", path, a, a.admin)).json()["items"] == []
    history = await world.sql(
        "SELECT kind FROM field_changes WHERE tenant_id = $1 AND record_type = 'ci_downtime'"
        " AND record_id = $2 ORDER BY occurred_at",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    # One history row per changed field: the kinds, in order, once each.
    assert list(dict.fromkeys(h["kind"] for h in history)) == ["created", "updated", "deleted"]
    audited = await world.sql(
        "SELECT action, outcome FROM audit_entries WHERE tenant_id = $1 AND object_id = $2"
        " AND action LIKE 'cmdb.downtime_%' ORDER BY occurred_at",
        a.tenant,
        ci["id"],
    )
    # Every attempt is audited, refused ones too; the three that took effect, in order.
    done = [r["action"] for r in audited if r["outcome"] == "done"]
    assert list(dict.fromkeys(done)) == [
        "cmdb.downtime_recorded",
        "cmdb.downtime_changed",
        "cmdb.downtime_removed",
    ]
    assert any(r["outcome"] != "done" for r in audited)  # the stale and the bad PATCH


async def test_a_synced_downtime_is_read_only_and_an_unseen_ci_is_404(world: World) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    ci = await _made(world, a, f"Synced box {tag}", "server", site_id=str(a.s1))
    downtime = uuid.uuid4()
    await _feed(world, a, _event(downtime, 1, [ci["id"]]))
    [row] = await _rows(world, a, downtime)
    path = f"{BASE}/{ci['id']}/downtimes/{row.id}"
    synced = await world.call(
        "PATCH", path, a, a.admin, json={"kind": "x"}, headers=_match(row.version)
    )
    assert problem(synced) == (409, "cmdb_downtime_synced")
    gone = await world.call("DELETE", path, a, a.admin, headers=_match(row.version))
    assert problem(gone) == (409, "cmdb_downtime_synced")

    # A reader limited to another site neither reads nor records this CI's downtimes.
    await _given(world, a, a.requester2, f"Site two {tag}", [("cmdb.view", "site")])
    hidden = await world.call("GET", f"{BASE}/{ci['id']}/downtimes", a, a.requester2)
    assert problem(hidden) == (404, "cmdb_ci_not_found")
    refused = await world.call(
        "POST",
        f"{BASE}/{ci['id']}/downtimes",
        a,
        a.requester2,
        json={"starts_at": datetime.now(UTC).isoformat()},
        headers=_new(),
    )
    assert refused.status_code in {403, 404}, refused.text  # never a recorded downtime
    assert len(await _rows(world, a, downtime)) == 1
