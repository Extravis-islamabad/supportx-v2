"""Configuration items in automation and notifications (WP-053 S5d; REQ-CMDB-023).

Real PostgreSQL and Valkey, the incidents test world. Committed events are fed to the trigger
consumer as the worker does (`drain`), and to the notification engine (`run_engine`).

The coordinator's conditions (C1-C3) and lane C's shape (L1-L5, R1-R6):
- each type offers its own events: a trigger naming another is refused when saved (L2);
- a rule's own change never re-triggers it (the causation chain, R5);
- a relationship fires on both ends, each on its own, and nothing about the other end reaches
  either end's run or its history, even for someone who may see that end only (C2, R4);
- a rule sets only its listed fields (C3); a CI's CREATED starts no workflow (R6);
- AC1: "a server's state becomes under maintenance, tell its owner": one notice, and nothing to
  someone who may not see the CI.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.database import Database, create_engine
from app.core.errors import ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.automation.domain.triggers import RATE_CAP
from app.modules.automation.service import workflow_events
from app.modules.automation.service.registry import record_type
from app.modules.cmdb.service import cis, downtimes
from app.shared.events import EventEnvelope
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_automation_api import set_
from tests.db.test_automation_triggers_api import drain
from tests.db.test_cmdb_api import _ci, _states
from tests.db.test_cmdb_downtimes import _event, _feed
from tests.db.test_cmdb_relationships import _given, _link
from tests.db.test_incidents_api import Org, World, field_codes
from tests.db.test_notifications_api import run_engine

pytestmark = [pytest.mark.db, pytest.mark.valkey, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, used by name

CMDB = "/cmdb"
CI_OFFER = {
    "created",
    "updated",
    "status_changed",
    "relationship_added",
    "relationship_removed",
    "downtime_started",
}


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


async def _trigger(world: World, org: Org, **body: Any) -> Any:  # noqa: ANN401 - JSON
    payload = {"record_type": "cmdb_ci", "name": "CI trigger", "state": "enabled", **body}
    return await world.call("POST", "/automation/triggers", org, org.admin, json=payload)


async def _edit(world: World, org: Org, ci: dict[str, Any], **values: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    current = await world.call("GET", f"{CMDB}/cis/{ci['id']}", org, org.admin)
    assert current.status_code == 200, current.text
    saved = await world.call(
        "PATCH",
        f"{CMDB}/cis/{ci['id']}",
        org,
        org.admin,
        json=values,
        headers={"If-Match": f'"{current.json()["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    return dict(saved.json())


async def _runs(world: World, org: Org, ci: dict[str, Any]) -> list[dict[str, Any]]:
    rows = await world.sql(
        "SELECT record_id, kind, automation_name, outcome, detail::text AS detail"
        " FROM automation_runs WHERE tenant_id = $1 AND record_id = $2 ORDER BY occurred_at",
        org.tenant,
        uuid.UUID(ci["id"]),
    )
    return [dict(r) for r in rows]


async def _rule_history(world: World, org: Org, ci: dict[str, Any]) -> list[str]:
    rows = await world.sql(
        "SELECT row_to_json(h)::text AS row FROM field_changes h"
        " WHERE tenant_id = $1 AND record_id = $2 AND automation_ref IS NOT NULL",
        org.tenant,
        uuid.UUID(ci["id"]),
    )
    return [str(r["row"]) for r in rows]


# --- what each type offers (L1, L2, L5) ---------------------------------------------------------


async def test_each_type_lists_its_own_trigger_events(world: World) -> None:
    a = world.a
    ci = await world.call(
        "GET", "/automation/trigger-events", a, a.admin, params={"record_type": "cmdb_ci"}
    )
    assert ci.status_code == 200, ci.text
    assert set(ci.json()["offered"]) == CI_OFFER
    incident = await world.call(
        "GET", "/automation/trigger-events", a, a.admin, params={"record_type": "incident"}
    )
    assert incident.status_code == 200, incident.text
    offered = set(incident.json()["offered"])
    assert len(offered) == 6  # no stage_entered: an incident has no stages (lane A)
    assert not offered & {
        "stage_entered",
        "relationship_added",
        "relationship_removed",
        "downtime_started",
    }
    release = await world.call(
        "GET", "/automation/trigger-events", a, a.admin, params={"record_type": "release"}
    )
    assert "stage_entered" in release.json()["offered"]


async def test_a_trigger_on_an_event_its_type_does_not_offer_is_refused(world: World) -> None:
    a = world.a
    on_incident = await world.call(
        "POST",
        "/automation/triggers",
        a,
        a.admin,
        json={
            "record_type": "incident",
            "name": "Not an incident event",
            "state": "enabled",
            "events": ["downtime_started"],
            "actions": [{"kind": "note", "text": "x"}],
        },
    )
    assert on_incident.status_code == 422, on_incident.text
    assert field_codes(on_incident)["events"] == "trigger_event_not_offered"
    on_ci = await _trigger(
        world, a, events=["note_added"], actions=[set_("criticality", "high", "overwrite")]
    )
    assert on_ci.status_code == 422, on_ci.text
    assert field_codes(on_ci)["events"] == "trigger_event_not_offered"
    fine = await _trigger(
        world,
        a,
        name="On a new relationship",
        events=["relationship_added"],
        actions=[set_("criticality", "high", "overwrite")],
        state="disabled",
    )
    assert fine.status_code == 201, fine.text


async def test_a_ci_trigger_is_never_given_a_note_it_could_not_add(world: World) -> None:
    """A CI has no notes: a note action is refused when saved, never failed on every run."""
    a = world.a
    refused = await _trigger(
        world, a, name="Notes", events=["updated"], actions=[{"kind": "note", "text": "x"}]
    )
    assert refused.status_code == 422, refused.text
    assert field_codes(refused)["actions.0.kind"] == "action_not_offered"


async def test_a_rule_may_set_only_its_listed_fields(world: World) -> None:
    a = world.a
    refused = await _trigger(
        world,
        a,
        name="Renames",
        events=["updated"],
        actions=[set_("name", "Renamed", "overwrite")],
    )
    assert refused.status_code == 422, refused.text
    assert field_codes(refused)["actions.0.field"] == "field_not_settable"
    ci = await _made(world, a, "Apply list")
    database = Database(create_engine(world.db.app_url, application_name="tests"))
    try:
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            with pytest.raises(ValidationFailed) as error:
                await cis.automated_update(
                    session,
                    uuid.UUID(ci["id"]),
                    {"name": "Renamed", "criticality": "high"},
                    automation_ref={"kind": "trigger", "trigger": "x"},
                    cause_id=uuid.uuid4(),
                )
            assert {e.code for e in error.value.errors} == {"field_not_settable"}
    finally:
        await database.dispose()


# --- the causation chain (R5) -------------------------------------------------------------------


async def test_a_state_trigger_runs_once_and_its_own_change_never_triggers_it_again(
    world: World,
) -> None:
    a = world.a
    states = await _states(world, a)
    made = await _trigger(
        world,
        a,
        name="Maintenance means high",
        events=["status_changed", "updated"],
        actions=[set_("criticality", "high", "overwrite")],
    )
    assert made.status_code == 201, made.text
    ci = await _made(world, a, "Mail server")
    await _edit(world, a, ci, state_id=states["under_maintenance"]["id"])
    await drain(world, a)
    after = await world.call("GET", f"{CMDB}/cis/{ci['id']}", a, a.admin)
    assert after.json()["criticality"] == "high"
    done = [
        r for r in await _runs(world, a, ci) if r["automation_name"] == "Maintenance means high"
    ]
    assert [r["outcome"] for r in done].count("applied") == 1, done
    assert any(r["outcome"] == "own_change" for r in done), done
    history = await _rule_history(world, a, ci)
    assert history
    assert all("Maintenance means high" in h for h in history)


async def test_a_rule_setting_what_the_ci_already_holds_changes_nothing(world: World) -> None:
    """Lane A: a rule's IDs arrive as text; compared typed, an equal value writes nothing."""
    a = world.a
    states = await _states(world, a)
    ci = await _made(world, a, "Same state", state_id=states["in_use"]["id"])
    before = await world.call("GET", f"{CMDB}/cis/{ci['id']}", a, a.admin)
    database = Database(create_engine(world.db.app_url, application_name="tests"))
    try:
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            changed = await cis.automated_update(
                session,
                uuid.UUID(ci["id"]),
                {"state_id": states["in_use"]["id"]},  # text, as a rule's JSON value
                automation_ref={"kind": "trigger", "trigger": "Same"},
                cause_id=uuid.uuid4(),
            )
    finally:
        await database.dispose()
    assert changed == []
    after = await world.call("GET", f"{CMDB}/cis/{ci['id']}", a, a.admin)
    assert after.json()["version"] == before.json()["version"]
    assert await _rule_history(world, a, ci) == []


async def test_a_state_saved_with_another_field_reaches_an_updated_trigger_once(
    world: World,
) -> None:
    """Lane C (2): a CI's combined save fires an "updated" trigger, once."""
    a = world.a
    states = await _states(world, a)
    made = await _trigger(
        world,
        a,
        name="Any edit",
        events=["updated"],
        actions=[set_("business_impact", "low", "overwrite")],
    )
    assert made.status_code == 201, made.text
    ci = await _made(world, a, "Combined save")
    await _edit(world, a, ci, state_id=states["under_maintenance"]["id"], criticality="high")
    await drain(world, a)
    runs = [r for r in await _runs(world, a, ci) if r["automation_name"] == "Any edit"]
    assert [r["outcome"] for r in runs].count("applied") == 1, runs


# --- relationships: both ends, nothing about the other (R1-R4, C2) ----------------------------


async def test_a_relationship_fires_on_both_ends_and_neither_names_the_other(world: World) -> None:
    a = world.a
    made = await _trigger(
        world,
        a,
        name="A new dependency",
        events=["relationship_added"],
        actions=[set_("business_impact", "high", "overwrite")],
    )
    assert made.status_code == 201, made.text
    seen = await _made(world, a, "Seen app", "application", site_id=str(a.s2))
    unseen = await _made(world, a, "Unseen db", "database", site_id=str(a.s1))
    assert (await _link(world, a, seen, "depends_on", [unseen])).status_code == 201
    await drain(world, a)
    for ci, other in ((seen, unseen), (unseen, seen)):
        runs = [r for r in await _runs(world, a, ci) if r["automation_name"] == "A new dependency"]
        assert [r["outcome"] for r in runs] == ["applied"], runs
        assert other["id"] not in str(runs)
        assert all(other["id"] not in h for h in await _rule_history(world, a, ci))
        got = await world.call("GET", f"{CMDB}/cis/{ci['id']}", a, a.admin)
        assert got.json()["business_impact"] == "high"
    # Someone who may see the app but not the database finds nothing of it there (R4).
    await _given(
        world,
        a,
        a.requester2,
        "Site two automation viewer",
        [("cmdb.view", "site"), ("automation.view", "all")],
    )
    log = await world.call(
        "GET", "/automation/runs", a, a.requester2, params={"record_id": seen["id"]}
    )
    assert log.status_code == 200, log.text
    assert log.json(), "the app's run is in its log"
    assert unseen["id"] not in log.text
    assert "Unseen db" not in log.text
    history = await world.call("GET", f"{CMDB}/cis/{seen['id']}/history", a, a.requester2)
    assert history.status_code == 200, history.text
    assert unseen["id"] not in history.text


async def test_one_end_at_its_rate_cap_never_stops_the_other_end(world: World) -> None:
    """R2: each end runs on its own; the source end's loop stop ends only that end."""
    a = world.a
    made = await _trigger(
        world,
        a,
        name="Rate per end",
        events=["relationship_added"],
        actions=[set_("criticality", "low", "overwrite")],
    )
    assert made.status_code == 201, made.text
    source = await _made(world, a, "Busy app", "application")
    target = await _made(world, a, "Quiet db", "database")
    # The source end already had RATE_CAP automated changes this minute.
    for _ in range(RATE_CAP):
        await world.sql(
            "INSERT INTO automation_runs (id, tenant_id, record_type, record_id, kind, outcome)"
            " VALUES ($1, $2, 'cmdb_ci', $3, 'trigger', 'applied')",
            uuid.uuid4(),
            a.tenant,
            uuid.UUID(source["id"]),
        )
    assert (await _link(world, a, source, "depends_on", [target])).status_code == 201
    await drain(world, a)
    quiet = await world.call("GET", f"{CMDB}/cis/{target['id']}", a, a.admin)
    assert quiet.json()["criticality"] == "low"  # the other end ran
    busy = await world.call("GET", f"{CMDB}/cis/{source['id']}", a, a.admin)
    assert busy.json()["criticality"] != "low"  # the source end stopped at its cap


# --- no workflow from a CI's creation (R6) ------------------------------------------------------


async def test_a_ci_carries_no_template_so_creating_one_starts_no_workflow(world: World) -> None:
    a = world.a
    ci = await _made(world, a, "No workflow")
    kind = record_type("cmdb_ci")
    assert kind is not None
    assert kind.facts is not None
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = 'cmdb.ci.created'"
        " AND envelope::jsonb -> 'payload' ->> 'ci_id' = $2",
        a.tenant,
        ci["id"],
    )
    envelope = EventEnvelope.model_validate_json(rows[0]["envelope"])
    database = Database(create_engine(world.db.app_url, application_name="tests"))
    try:
        async with database.tenant_session(TenantContext(a.tenant)) as session:
            facts = await kind.facts(session, uuid.UUID(ci["id"]))
            assert facts is not None
            assert "template_id" not in facts
            await workflow_events.on_record_event(envelope, session)
    finally:
        await database.dispose()
    started = await world.sql(
        "SELECT count(*) AS n FROM workflow_instances WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        uuid.UUID(ci["id"]),
    )
    assert started[0]["n"] == 0


# --- notifications (AC1) ------------------------------------------------------------------------


async def test_ac1_the_owner_hears_once_and_someone_who_cannot_see_it_hears_nothing(
    world: World,
) -> None:
    a = world.a
    states = await _states(world, a)
    rules = (await world.call("GET", "/notifications/rules", a, a.admin)).json()
    view = next(r for r in rules if r["event_code"] == "cmdb_ci.state_changed")
    saved = await world.call(
        "PUT",
        "/notifications/rules/cmdb_ci.state_changed",
        a,
        a.admin,
        json={
            "recipients": ["ci_owner"],
            "channels": view["channels"],
            "group_ids": view["group_ids"],
            "enabled": True,
            "user_ids": [str(a.requester2)],  # named, but may not see an S1 CI
            "conditions": [
                {
                    "field": "state_id",
                    "operator": "in",
                    "values": [states["under_maintenance"]["id"]],
                }
            ],
            "notify_actor": True,
        },
        headers={"If-Match": f'"{view["version"]}"'},
    )
    assert saved.status_code == 200, saved.text
    # The owner (a technician) sees the CI; requester2, named in the rule, sees only site S2.
    await _given(world, a, a.requester2, "Site two CI reader", [("cmdb.view", "site")])
    ci = await _made(
        world,
        a,
        "Production server",
        site_id=str(a.s1),
        owner_user_id=str(a.tech_a),
    )
    await _edit(world, a, ci, state_id=states["under_maintenance"]["id"])
    await _edit(world, a, ci, description="Disk swap booked")  # not a state change: no notice
    await run_engine(world, a)
    told = await world.sql(
        "SELECT user_id, channel, state, reason FROM notification_deliveries"
        " WHERE tenant_id = $1 AND record_id = $2 AND event_code = 'cmdb_ci.state_changed'",
        a.tenant,
        uuid.UUID(ci["id"]),
    )
    reached = [d for d in told if d["state"] != "skipped" and d["reason"] is None]
    owner = [d for d in reached if d["user_id"] == a.tech_a]
    assert owner, told  # the owner hears of it ...
    assert len({d["channel"] for d in owner}) == len(owner)  # ... once per channel, one change
    assert all(d["user_id"] != a.requester2 for d in reached), told


async def test_a_downtime_starting_fires_once_and_recording_one_for_later_does_not(
    world: World,
) -> None:
    """S5d: downtime_started fires when the sweep makes a downtime active, never on recording it."""
    a = world.a
    made = await _trigger(
        world,
        a,
        name="Downtime begins",
        events=["downtime_started"],
        actions=[set_("business_impact", "high", "overwrite")],
    )
    assert made.status_code == 201, made.text
    ci = await _made(world, a, f"Maintained box {uuid.uuid4().hex[:6]}")
    starts = datetime.now(UTC) + timedelta(hours=1)
    recorded = await world.call(
        "POST",
        f"{CMDB}/cis/{ci['id']}/downtimes",
        a,
        a.admin,
        json={
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "kind": "maintenance",
            "description": "Disk swap",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert recorded.status_code == 201, recorded.text
    await drain(world, a)
    mine = [r for r in await _runs(world, a, ci) if r["automation_name"] == "Downtime begins"]
    assert mine == []  # scheduled for later is not a start
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert await downtimes.sweep_tenant(session, starts) >= 1
    await drain(world, a)
    mine = [r for r in await _runs(world, a, ci) if r["automation_name"] == "Downtime begins"]
    assert [r["outcome"] for r in mine] == ["applied"], mine
    got = await world.call("GET", f"{CMDB}/cis/{ci['id']}", a, a.admin)
    assert got.json()["business_impact"] == "high"
    # Nothing about the downtime itself reaches the run's log (only "downtimes" changed).
    assert recorded.json()["id"] not in str(mine)
    assert "Disk swap" not in str(mine)


async def _started_runs(world: World, org: Org, ci: dict[str, Any], name: str) -> list[str]:
    await drain(world, org)
    return [r["outcome"] for r in await _runs(world, org, ci) if r["automation_name"] == name]


async def test_an_edit_moving_a_downtime_start_to_now_fires_it_once(world: World) -> None:
    """Lane A (#626): an `updated` can carry the move into active; the sweep then emits nothing."""
    a = world.a
    name = f"Edited start {uuid.uuid4().hex[:6]}"
    made = await _trigger(
        world,
        a,
        name=name,
        events=["downtime_started"],
        actions=[set_("business_impact", "high", "overwrite")],
    )
    assert made.status_code == 201, made.text
    ci = await _made(world, a, f"Edited box {uuid.uuid4().hex[:6]}")
    later = datetime.now(UTC) + timedelta(hours=1)
    path = f"{CMDB}/cis/{ci['id']}/downtimes"
    recorded = await world.call(
        "POST",
        path,
        a,
        a.admin,
        json={
            "starts_at": later.isoformat(),
            "ends_at": (later + timedelta(hours=1)).isoformat(),
            "kind": "maintenance",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert recorded.status_code == 201, recorded.text
    assert await _started_runs(world, a, ci, name) == []
    item = recorded.json()
    moved = await world.call(
        "PATCH",
        f"{path}/{item['id']}",
        a,
        a.admin,
        json={"starts_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat()},
        headers={"If-Match": f'"{item["version"]}"'},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["state"] == "active"
    assert await _started_runs(world, a, ci, name) == ["applied"]
    # Another edit while it is already active is not a second start.
    again = await world.call(
        "PATCH",
        f"{path}/{item['id']}",
        a,
        a.admin,
        json={"kind": "repair"},
        headers={"If-Match": f'"{moved.json()["version"]}"'},
    )
    assert again.status_code == 200, again.text
    assert await _started_runs(world, a, ci, name) == ["applied"]


async def test_a_mirrored_work_item_downtime_moved_to_now_fires_it_once(world: World) -> None:
    """Lane A (#626): the work-item mirror recomputes the state on an update, too."""
    a = world.a
    name = f"Mirrored start {uuid.uuid4().hex[:6]}"
    made = await _trigger(
        world,
        a,
        name=name,
        events=["downtime_started"],
        actions=[set_("business_impact", "high", "overwrite")],
    )
    assert made.status_code == 201, made.text
    ci = await _made(world, a, f"Mirrored box {uuid.uuid4().hex[:6]}")
    downtime = uuid.uuid4()
    await _feed(world, a, _event(downtime, 1, [ci["id"]]))
    assert await _started_runs(world, a, ci, name) == []
    now = datetime.now(UTC)
    earlier = {
        "starts_at": (now - timedelta(minutes=5)).isoformat(),
        "ends_at": (now + timedelta(hours=1)).isoformat(),
    }
    await _feed(world, a, _event(downtime, 2, [ci["id"]], **earlier))
    assert await _started_runs(world, a, ci, name) == ["applied"]


async def test_a_mirrored_downtime_added_already_started_fires_once_and_not_again_at_the_sweep(
    world: World,
) -> None:
    """Lane A (#626): added with no previous state and already active is one start; the sweep
    finds the state unchanged and emits nothing more."""
    a = world.a
    name = f"Added started {uuid.uuid4().hex[:6]}"
    made = await _trigger(
        world,
        a,
        name=name,
        events=["downtime_started"],
        actions=[set_("business_impact", "high", "overwrite")],
    )
    assert made.status_code == 201, made.text
    ci = await _made(world, a, f"Started box {uuid.uuid4().hex[:6]}")
    now = datetime.now(UTC)
    started = {
        "starts_at": (now - timedelta(minutes=5)).isoformat(),
        "ends_at": (now + timedelta(hours=1)).isoformat(),
    }
    await _feed(world, a, _event(uuid.uuid4(), 1, [ci["id"]], **started))
    assert await _started_runs(world, a, ci, name) == ["applied"]
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await downtimes.sweep_tenant(session, datetime.now(UTC))
    assert await _started_runs(world, a, ci, name) == ["applied"]
