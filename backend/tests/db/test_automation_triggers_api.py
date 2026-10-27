"""Triggers, loop protection and transition settings over HTTP (WP-029 part 2).

Real PostgreSQL and Valkey, the incidents test world. Committed events are fed to the trigger
consumer the way the consumer worker does it (`drain`): one tenant transaction per event with
the consumer's idempotency claim, until no new event appears. Each test names the requirement
and criterion it proves.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.automation.service.triggers import TRIGGER_EVENT_TYPES, on_record_event
from app.shared.events import EventEnvelope, claim
from tests.db.test_automation_api import set_
from tests.db.test_incidents_api import BASE, Org, World, incidents_world, problem
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.valkey]
CONSUMER = "automation__triggers"


@pytest_asyncio.fixture
async def world(migrated_db: ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(migrated_db) as built:
        yield built


async def envelopes(world: World, org: Org) -> list[EventEnvelope]:
    rows = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1 AND event_type = ANY($2)"
        " ORDER BY id",
        org.tenant,
        list(TRIGGER_EVENT_TYPES),
    )
    return [EventEnvelope.model_validate_json(row["envelope"]) for row in rows]


async def deliver(world: World, envelope: EventEnvelope) -> bool:
    """One delivery as the consumer worker makes it (False: already processed)."""
    database = Database(
        create_engine(world.db.app_url, application_name="tests", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(envelope.tenant_id)) as session:
            if not await claim(session, CONSUMER, envelope):
                return False
            await on_record_event(envelope, session)
        return True
    finally:
        await database.dispose()


async def drain(world: World, org: Org, rounds: int = 40) -> int:
    """Deliver every committed event, and those the triggers then cause, until none is left."""
    done: set[uuid.UUID] = set()
    for _ in range(rounds):
        fresh = [e for e in await envelopes(world, org) if e.event_id not in done]
        if not fresh:
            return len(done)
        for envelope in fresh:
            await deliver(world, envelope)
            done.add(envelope.event_id)
    msg = "events kept coming: the loop guard did not stop the chain"
    raise AssertionError(msg)


async def add_trigger(world: World, org: Org, **body: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    payload = {"record_type": "incident", "name": "Trigger", "state": "enabled", **body}
    created = await world.call("POST", "/automation/triggers", org, org.admin, json=payload)
    assert created.status_code == 201, created.text
    return dict(created.json())


def note(text_: str) -> dict[str, Any]:
    return {"kind": "note", "text": text_}


async def runs(world: World, org: Org, item: dict[str, Any]) -> list[dict[str, Any]]:
    found = await world.call("GET", f"{BASE}/{item['id']}/automation", org, org.tech_a)
    assert found.status_code == 200, found.text
    return list(found.json())


async def current(world: World, org: Org, item: dict[str, Any]) -> dict[str, Any]:
    found = await world.call("GET", f"{BASE}/{item['id']}", org, org.admin)
    assert found.status_code == 200, found.text
    return dict(found.json())


# --- triggers -----------------------------------------------------------------------------------


async def test_req_rul_009_ac1_ac4_a_status_trigger_runs_once_and_history_names_it(
    world: World,
) -> None:
    org = world.a
    await add_trigger(
        world,
        org,
        name="Resolved check",
        events=["status_changed"],
        conditions={"field": "status", "op": "changed_to", "value": "resolved"},
        actions=[
            set_("tags", ["resolved-check"], "overwrite"),
            note("Check the fix with the user."),
        ],
    )
    item = await world.create(org, org.admin)
    resolved = await world.act(org, org.admin, item, "resolve")
    assert resolved.status_code == 200, resolved.text
    await drain(world, org)
    assert (await current(world, org, item))["tags"] == ["resolved-check"]
    by_trigger = [
        h
        for h in await world.history(org, item)
        if (h.get("automation") or {}).get("kind") == "trigger"
    ]
    assert {h["automation"]["trigger"] for h in by_trigger} == {"Resolved check"}
    assert len(by_trigger) == 2  # the field and the note, each named
    applied = [r for r in await runs(world, org, item) if r["kind"] == "trigger"]
    assert [r["outcome"] for r in applied] == ["applied"]  # once, not again on its own change


async def test_req_rul_009_ac3_a_redelivered_event_runs_nothing_twice(world: World) -> None:
    org = world.a
    await add_trigger(world, org, name="Noter", events=["created"], actions=[note("Hello.")])
    item = await world.create(org, org.admin)
    (created,) = [
        e for e in await envelopes(world, org) if e.event_type == "work_items.work_item.created"
    ]
    assert await deliver(world, created) is True
    assert await deliver(world, created) is False
    notes = await world.sql(
        "SELECT count(*) AS n FROM work_item_conversations WHERE work_item_id = $1",
        uuid.UUID(item["id"]),
    )
    assert notes[0]["n"] == 1


async def test_req_rul_009_ac2_a_rolled_back_change_runs_nothing(world: World) -> None:
    org = world.a
    await add_trigger(world, org, name="Noter", events=["created"], actions=[note("Hello.")])
    refused = await world.call(
        "POST", BASE, org, org.admin, json={"subject": "", "requester_id": str(org.requester)}
    )
    assert refused.status_code == 422
    assert await drain(world, org) == 0  # nothing committed, nothing in the outbox


async def test_req_rul_010_a_failed_action_never_undoes_the_others_and_says_why(
    world: World,
) -> None:
    org = world.a
    spare = await world.call("POST", "/organization/groups", org, org.admin, json={"name": "Old"})
    assert spare.status_code == 201, spare.text
    await add_trigger(
        world,
        org,
        name="Two steps",
        events=["created"],
        actions=[set_("group_id", spare.json()["id"], "overwrite"), note("Second step.")],
    )
    off = await world.call(
        "PATCH",
        f"/organization/groups/{spare.json()['id']}",
        org,
        org.admin,
        json={"disabled": True},
        headers={"If-Match": f'"{spare.json()["version"]}"'},
    )
    assert off.status_code == 200, off.text
    item = await world.create(org, org.admin)
    await drain(world, org)
    (run,) = [r for r in await runs(world, org, item) if r["kind"] == "trigger"]
    assert run["outcome"] == "partial"
    assert [(a["kind"], a["outcome"]) for a in run["detail"]["actions"]] == [
        ("set", "failed"),
        ("note", "applied"),
    ]
    assert run["detail"]["actions"][0]["reason"]  # a reason the UI can label
    assert (await current(world, org, item))["group_id"] != spare.json()["id"]


async def test_req_rul_029_a_trigger_is_checked_when_saved(world: World) -> None:
    org = world.a
    bad = await world.call(
        "POST",
        "/automation/triggers",
        org,
        org.admin,
        json={
            "record_type": "incident",
            "name": "Bad",
            "events": ["updated"],
            "conditions": {"field": "priority", "op": "changed_from", "value": "p1"},
            "actions": [{"kind": "note", "text": "  "}],
        },
    )
    assert bad.status_code == 422
    codes = {(e["field"], e["code"]) for e in bad.json()["errors"]}
    assert codes == {
        ("body.conditions", "operator_not_allowed"),
        ("body.actions.0.text", "required"),
    }


# --- loop protection ----------------------------------------------------------------------------


async def test_req_rul_028_ac1_ac3_two_triggers_stop_at_the_cap_named_and_told_once(
    world: World,
) -> None:
    org = world.a
    ping = await add_trigger(
        world,
        org,
        name="Ping",
        events=["updated"],
        conditions={"field": "tags", "op": "changed_to", "value": ["a"]},
        actions=[set_("tags", ["b"], "overwrite")],
    )
    await add_trigger(
        world,
        org,
        name="Pong",
        events=["updated"],
        conditions={"field": "tags", "op": "changed_to", "value": ["b"]},
        actions=[set_("tags", ["a"], "overwrite")],
    )
    item = await world.create(org, org.admin)
    edited = await world.patch(org, org.admin, item, tags=["a"])
    assert edited.status_code == 200, edited.text
    await drain(world, org)
    log = await runs(world, org, item)
    (stop,) = [r for r in log if r["kind"] == "loop_guard"]
    assert stop["outcome"] == "chain_depth"
    assert stop["detail"]["triggers"] == ["Ping", "Pong"]
    assert len([r for r in log if r["kind"] == "trigger" and r["outcome"] == "applied"]) == 5
    told = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'automation.loop.stopped'",
        org.tenant,
    )
    assert len(told) == 1
    stops = await world.call("GET", "/automation/loop-stops", org, org.admin)
    assert [s["record_id"] for s in stops.json()] == [item["id"]]
    assert ping["id"] in str(told[0]["envelope"])


async def test_req_rul_028_ac2_a_trigger_never_fires_on_its_own_change(world: World) -> None:
    org = world.a
    await add_trigger(
        world,
        org,
        name="Marker",
        events=["updated"],
        conditions={"field": "tags", "op": "changed"},
        actions=[set_("tags", ["marked"], "overwrite")],
    )
    item = await world.create(org, org.admin)
    await world.patch(org, org.admin, item, tags=["first"])
    await drain(world, org)
    outcomes = [r["outcome"] for r in await runs(world, org, item) if r["kind"] == "trigger"]
    assert sorted(outcomes) == ["applied", "own_change"]
    assert (await current(world, org, item))["tags"] == ["marked"]


# --- transitions --------------------------------------------------------------------------------


async def save_transition(
    world: World,
    org: Org,
    action: str,
    version: int = 0,
    **body: Any,  # noqa: ANN401 - JSON
) -> dict[str, Any]:
    saved = await world.call(
        "PUT",
        f"/automation/transitions/{action}",
        org,
        org.admin,
        params={"record_type": "incident"},
        json=body,
        headers={"If-Match": f'"{version}"'},
    )
    assert saved.status_code == 200, saved.text
    return dict(saved.json())


def offered(record: dict[str, Any], action: str) -> tuple[bool, str | None]:
    (state,) = [a for a in record["actions"] if a["action"] == action]
    return state["allowed"], state.get("reason")


async def test_req_wf_004_who_may_run_is_shown_disabled_with_the_reason_and_refused(
    world: World,
) -> None:
    org = world.a
    await save_transition(world, org, "resolve", relatives=["assignee"])
    item = await world.create(org, org.admin, group_id=str(org.ga), technician_id=str(org.tech_a))
    other = await world.call("GET", f"{BASE}/{item['id']}", org, org.tech_c)
    assert offered(other.json(), "resolve") == (False, "not_for_you")
    refused = await world.act(org, org.tech_c, other.json(), "resolve")
    assert problem(refused) == (403, "transition_not_allowed")
    assert refused.json()["params"] == {"reason": "not_for_you"}
    mine = await world.call("GET", f"{BASE}/{item['id']}", org, org.tech_a)
    assert offered(mine.json(), "resolve") == (True, None)
    assert (await world.act(org, org.tech_a, mine.json(), "resolve")).status_code == 200


async def test_req_wf_003_ac1_offered_only_when_its_conditions_hold(world: World) -> None:
    org = world.a
    await save_transition(
        world, org, "resolve", conditions={"field": "priority", "op": "eq", "value": "p1"}
    )
    item = await world.create(org, org.admin)
    assert offered(await current(world, org, item), "resolve") == (False, "not_offered")


async def test_req_wf_003_ac3_after_actions_run_once_committed_and_a_failure_keeps_the_move(
    world: World,
) -> None:
    org = world.a
    spare = await world.call("POST", "/organization/groups", org, org.admin, json={"name": "Old"})
    await save_transition(
        world,
        org,
        "resolve",
        after_actions=[set_("group_id", spare.json()["id"], "overwrite"), note("Resolved.")],
    )
    await world.call(
        "PATCH",
        f"/organization/groups/{spare.json()['id']}",
        org,
        org.admin,
        json={"disabled": True},
        headers={"If-Match": f'"{spare.json()["version"]}"'},
    )
    item = await world.create(org, org.admin)
    resolved = await world.act(org, org.admin, item, "resolve")
    assert resolved.status_code == 200, resolved.text
    assert [r for r in await runs(world, org, item) if r["kind"] == "trigger"] == []  # not yet
    await drain(world, org)
    (run,) = [r for r in await runs(world, org, item) if r["kind"] == "trigger"]
    assert (run["automation_name"], run["outcome"]) == ("resolve", "partial")
    assert (await current(world, org, item))["status"] == "resolved"


async def test_transition_settings_version_and_reset(world: World) -> None:
    org = world.a
    first = await save_transition(world, org, "close", roles=["tenant_admin"])
    assert first["version"] == 1
    stale = await world.call(
        "PUT",
        "/automation/transitions/close",
        org,
        org.admin,
        params={"record_type": "incident"},
        json={},
        headers={"If-Match": '"0"'},
    )
    assert stale.status_code == 409
    unknown = await world.call(
        "PUT",
        "/automation/transitions/fly",
        org,
        org.admin,
        params={"record_type": "incident"},
        json={},
        headers={"If-Match": '"0"'},
    )
    assert problem(unknown) == (404, "transition_not_found")
    reset = await world.call(
        "DELETE",
        "/automation/transitions/close",
        org,
        org.admin,
        params={"record_type": "incident"},
        headers={"If-Match": '"1"'},
    )
    assert reset.status_code == 204
    listed = await world.call(
        "GET", "/automation/transitions", org, org.admin, params={"record_type": "incident"}
    )
    assert listed.json() == []


async def test_transition_settings_are_tenant_isolated(world: World) -> None:
    await save_transition(world, world.a, "close", roles=["tenant_admin"])
    database = Database(
        create_engine(world.db.app_url, application_name="tests", use_null_pool=True)
    )
    try:
        async with database.tenant_session(TenantContext(world.b.tenant)) as session:
            seen = await session.execute(text("SELECT count(*) FROM transition_settings"))
            assert seen.scalar_one() == 0
        with pytest.raises(ProgrammingError):
            async with database.tenant_session(TenantContext(world.b.tenant)) as session:
                await session.execute(
                    text(
                        "INSERT INTO transition_settings (tenant_id, record_type, action)"
                        " VALUES (:t, 'incident', 'resolve')"
                    ),
                    {"t": world.a.tenant},
                )
    finally:
        await database.dispose()
