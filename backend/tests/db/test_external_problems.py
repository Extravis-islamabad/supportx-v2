"""Incidents from an outside system's problems (WP-053 S7a, D-050): lane A's entry point.

Real PostgreSQL with RLS, run as monitoring_integrations will: in the caller's transaction, as
the connection's service account holding a real role (the coordinator's condition 2). The rules
agreed with lane B and the coordinator on 2026-11-25:

- one incident per outside problem for life; a replay or an older version changes nothing;
- the key table is tenant-isolated (condition 4);
- a merged incident's key follows the survivor, and the loser's key never re-creates (3);
- recovery resolves an untouched incident; a person's change keeps it open with a note and
  the assignee is told; an auto-assign rule or another integration's account is not a person;
- a person closing it by hand makes later events a no-op, never a re-create;
- refusals are labelled; without the role, nothing is made;
- the subject is plain text, capped; an empty one falls back to a labelled one.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDenied
from app.core.tenancy import TenantContext
from app.modules import work_items
from app.modules.identity_access import Subject, subject_for
from app.modules.work_items import ExternalProblemRefused, ExternalSource
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_incidents_api import CONSOLE, Org, World, role

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, used by name

NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)
RIGHTS = [
    ("incidents.create", "all"),
    ("incidents.view", "all"),
    ("incidents.edit", "all"),
    ("incidents.assign", "all"),
    ("incidents.change_priority", "all"),
    ("incidents.resolve", "all"),
    ("cmdb.view", "all"),
]


async def _service_account(world: World, org: Org, *, rights: bool = True) -> uuid.UUID:
    """A real service account (WP-057 S4a, no sign-in) with a real role, never a bypass."""
    made = await world.call(
        "POST", "/service-accounts", org, org.admin,
        json={"name": f"MonetX {uuid.uuid4().hex[:6]}", "owner_id": str(org.admin)},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )  # fmt: skip
    assert made.status_code == 201, made.text
    account = uuid.UUID(made.json()["id"])
    if rights:
        given = await role(world, org, f"Monitoring {uuid.uuid4().hex[:6]}", RIGHTS)
        put = await world.call("PUT", f"/service-accounts/{account}/roles/{given}", org, org.admin)
        assert put.status_code == 204, put.text
    return account


async def _template(world: World, org: Org) -> uuid.UUID:
    listed = await world.call("GET", "/incidents/templates", org, org.admin)  # makes the defaults
    assert listed.status_code == 200, listed.text
    found = [t for t in listed.json() if t.get("is_default")] or listed.json()
    return uuid.UUID(found[0]["id"])


@asynccontextmanager
async def _as(
    world: World, org: Org, account: uuid.UUID
) -> AsyncIterator[tuple[AsyncSession, Subject]]:
    """One transaction as the service account, as monitoring_integrations runs it."""
    context = TenantContext(org.tenant, user_id=account)
    async with world.app.state.db.tenant_session(context) as session:
        yield session, await subject_for(session, org.tenant, account)


def _source() -> ExternalSource:
    return ExternalSource("monetx", uuid.uuid4())


async def _create(
    world: World,
    org: Org,
    account: uuid.UUID,
    source: ExternalSource,
    external_id: str,
    version: int = 1,
    priority: str = "p2",
    **extra: Any,  # noqa: ANN401 - the entry point's own keywords, passed through
) -> work_items.ExternalRecordRef:
    template = await _template(world, org)
    async with _as(world, org, account) as (session, actor):
        return await work_items.create_from_external_problem(
            session, actor=actor, source=source, external_id=external_id, version=version,
            template_id=template, priority=priority, group_id=None, ci_ids=[],
            subject=extra.pop("subject", "Disk full on db1"), opened_at=NOW, **extra,
        )  # fmt: skip


async def _recover(
    world: World,
    org: Org,
    account: uuid.UUID,
    source: ExternalSource,
    external_id: str,
    version: int,
    *,
    resolve: bool = True,
) -> work_items.ExternalRecordRef | None:
    async with _as(world, org, account) as (session, actor):
        return await work_items.external_problem_recovered(
            session, actor=actor, source=source, external_id=external_id, version=version,
            recovered_at=NOW, resolve=resolve,
        )  # fmt: skip


async def _record(world: World, org: Org, record_id: uuid.UUID) -> dict[str, Any]:
    got = await world.call("GET", f"/incidents/{record_id}", org, org.admin)
    assert got.status_code == 200, got.text
    return dict(got.json())


async def _history(world: World, org: Org, record_id: uuid.UUID) -> list[tuple[str, Any, str]]:
    rows = await world.sql(
        "SELECT field, new_value, source FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = 'external_problem' ORDER BY occurred_at, id",
        org.tenant,
        record_id,
    )
    return [(r["field"], json.loads(r["new_value"]), r["source"]) for r in rows]


async def test_one_incident_per_problem_a_replay_or_older_version_changes_nothing(
    world: World,
) -> None:
    a = world.a
    account = await _service_account(world, a)
    source = _source()
    made = await _create(world, a, account, source, "P-1", version=3,
                         note_codes=["external_problem.opened"])  # fmt: skip
    assert (made.created, made.decision) == (True, "created")
    assert made.record_id is not None
    again = await _create(world, a, account, source, "P-1", version=3)
    assert (again.created, again.decision, again.record_id) == (False, "exists", made.record_id)
    record = await _record(world, a, made.record_id)
    assert (record["subject"], record["channel"]) == ("Disk full on db1", "monetx")
    assert record["requester_id"] == str(account)  # no person is told it was logged
    async with _as(world, a, account) as (session, actor):
        stale = await work_items.update_from_external_problem(
            session, actor=actor, source=source, external_id="P-1", version=2, priority="p1"
        )
    assert stale is not None
    assert stale.decision == "stale_version"
    assert (await _record(world, a, made.record_id))["priority"] == "p2"
    rows = await world.sql(
        "SELECT source, automation_ref FROM field_changes WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        made.record_id,
    )
    assert {r["source"] for r in rows} == {"integration"}
    refs = {
        json.dumps(json.loads(r["automation_ref"]), sort_keys=True)
        for r in rows
        if r["automation_ref"]
    }
    assert refs == {json.dumps({"connection_id": str(source.source_id), "kind": "monitoring",
                                "source": "monetx"}, sort_keys=True)}  # fmt: skip
    assert ("external_problem", "opened", "integration") in await _history(world, a, made.record_id)
    # The same problem ID from another connection is another problem.
    other = await _create(world, a, account, _source(), "P-1")
    assert other.created
    assert other.record_id != made.record_id


async def test_a_newer_version_updates_the_open_incident(world: World) -> None:
    a = world.a
    account = await _service_account(world, a)
    source = _source()
    made = await _create(world, a, account, source, "P-2")
    assert made.record_id is not None
    async with _as(world, a, account) as (session, actor):
        updated = await work_items.update_from_external_problem(
            session, actor=actor, source=source, external_id="P-2", version=2, priority="p1",
            subject="Disk full on db1 and db2",
        )  # fmt: skip
        never = await work_items.update_from_external_problem(
            session, actor=actor, source=source, external_id="never-seen", version=1
        )
    assert updated is not None
    assert updated.decision == "updated"
    assert never is None  # never seen: the caller creates first
    record = await _record(world, a, made.record_id)
    assert (record["priority"], record["subject"]) == ("p1", "Disk full on db1 and db2")


async def test_recovery_resolves_an_incident_only_a_rule_has_touched(world: World) -> None:
    a = world.a
    account = await _service_account(world, a)
    source = _source()
    made = await _create(world, a, account, source, "P-3")
    assert made.record_id is not None
    # As an auto-assign rule would: a change made by a rule, not by a person.
    await world.sql(
        "INSERT INTO field_changes (id, tenant_id, record_type, record_id, record_version,"
        " change_id, kind, field, old_value, new_value, actor_type, actor_id, source, occurred_at)"
        " VALUES ($1, $2, 'work_item', $3, 1, $4, 'updated', 'group_id', NULL, '\"g\"',"
        " 'system', NULL, 'rule', now())",
        uuid.uuid4(), a.tenant, made.record_id, uuid.uuid4(),
    )  # fmt: skip
    done = await _recover(world, a, account, source, "P-3", 2)
    assert done is not None
    assert done.decision == "resolved"
    assert (await _record(world, a, made.record_id))["status_category"] == "resolved"
    later = await _recover(world, a, account, source, "P-3", 3)
    assert later is not None
    assert later.decision == "closed_noop"


async def test_a_persons_change_keeps_it_open_and_tells_the_assignee(world: World) -> None:
    a = world.a
    account = await _service_account(world, a)
    source = _source()
    made = await _create(world, a, account, source, "P-4")
    assert made.record_id is not None
    record = await _record(world, a, made.record_id)
    patched = await world.call(
        "PATCH", f"/incidents/{made.record_id}", a, a.admin,
        json={"subject": "Disk full on db1 (investigating)"},
        headers={"If-Match": f'"{record["version"]}"', **CONSOLE},
    )  # fmt: skip
    assert patched.status_code == 200, patched.text
    kept = await _recover(world, a, account, source, "P-4", 2)
    assert kept is not None
    assert kept.decision == "noted"
    assert (await _record(world, a, made.record_id))["status_category"] != "resolved"
    assert ("external_problem", "recovered_kept_open", "integration") in await _history(
        world, a, made.record_id
    )
    events = await world.sql(
        "SELECT envelope->'payload'->>'why' AS why FROM outbox_events WHERE tenant_id = $1"
        " AND envelope->>'event_type' = 'work_items.work_item.source_recovered'"
        " AND envelope->'payload'->>'work_item_id' = $2",
        a.tenant, str(made.record_id),
    )  # fmt: skip
    assert [e["why"] for e in events] == ["touched"]


async def test_another_integrations_service_account_is_not_a_person(world: World) -> None:
    a = world.a
    account = await _service_account(world, a)
    other = await _service_account(world, a)
    source = _source()
    made = await _create(world, a, account, source, "P-5")
    assert made.record_id is not None
    async with _as(world, a, other) as (session, actor):  # another integration edits it
        await work_items.update_from_external_problem(
            session, actor=actor, source=_source(), external_id="unrelated", version=1
        )
    await world.sql(
        "INSERT INTO field_changes (id, tenant_id, record_type, record_id, record_version,"
        " change_id, kind, field, old_value, new_value, actor_type, actor_id, source, occurred_at)"
        " VALUES ($1, $2, 'work_item', $3, 1, $4, 'updated', 'subject', NULL, '\"x\"',"
        " 'user', $5, 'api', now())",
        uuid.uuid4(), a.tenant, made.record_id, uuid.uuid4(), str(other),
    )  # fmt: skip
    done = await _recover(world, a, account, source, "P-5", 2)
    assert done is not None
    assert done.decision == "resolved"


async def test_closed_by_hand_later_events_are_a_no_op_never_a_re_create(world: World) -> None:
    a = world.a
    account = await _service_account(world, a)
    source = _source()
    made = await _create(world, a, account, source, "P-6")
    assert made.record_id is not None
    await world.sql(
        "UPDATE work_items SET status_category = 'closed' WHERE tenant_id = $1 AND id = $2",
        a.tenant, made.record_id,
    )  # fmt: skip
    assert (await _recover(world, a, account, source, "P-6", 2)).decision == "closed_noop"  # type: ignore[union-attr]  # never None for a known key
    again = await _create(world, a, account, source, "P-6", version=9)
    assert (again.created, again.record_id) == (False, made.record_id)


async def test_a_merged_incidents_key_follows_the_survivor_and_never_re_creates(
    world: World,
) -> None:
    a = world.a
    account = await _service_account(world, a)
    source = _source()
    loser = await _create(world, a, account, source, "P-7")
    survivor = await world.create(a, a.admin)
    assert loser.record_id is not None
    await world.sql(
        "INSERT INTO work_item_links (id, tenant_id, source_id, target_id, kind, created_at,"
        " updated_at, version) VALUES ($1, $2, $3, $4, 'merged_into', now(), now(), 1)",
        uuid.uuid4(), a.tenant, loser.record_id, uuid.UUID(survivor["id"]),
    )  # fmt: skip
    again = await _create(world, a, account, source, "P-7", version=2)
    assert (again.created, again.record_id, again.display_id) == (
        False, uuid.UUID(survivor["id"]), survivor["display_id"],
    )  # fmt: skip
    async with _as(world, a, account) as (session, actor):
        moved = await work_items.update_from_external_problem(
            session, actor=actor, source=source, external_id="P-7", version=3, priority="p1"
        )
    assert moved is not None
    assert moved.record_id == uuid.UUID(survivor["id"])
    count = await world.sql(
        "SELECT count(*) AS n FROM work_item_external_keys WHERE tenant_id = $1"
        " AND external_id = 'P-7'",
        a.tenant,
    )
    assert count[0]["n"] == 1


async def test_labelled_refusals_and_no_role_makes_nothing(world: World) -> None:
    a = world.a
    account = await _service_account(world, a)
    source = _source()
    with pytest.raises(ExternalProblemRefused) as unknown:
        await _create(world, a, account, source, "P-8", priority="p9")
    assert unknown.value.code == "priority_unknown"
    with pytest.raises(ExternalProblemRefused) as person:
        await _create(world, a, account, source, "P-9", requester_id=account)
    assert person.value.code == "requester_unusable"  # a service account is no requester
    bare = await _service_account(world, a, rights=False)
    with pytest.raises(PermissionDenied):  # the create right's own refusal, never bypassed
        await _create(world, a, bare, source, "P-10")
    keys = await world.sql(
        "SELECT external_id FROM work_item_external_keys WHERE tenant_id = $1"
        " AND source_id = $2",
        a.tenant, source.source_id,
    )  # fmt: skip
    assert keys == []  # nothing was made


async def test_the_subject_is_plain_and_an_empty_one_is_labelled(world: World) -> None:
    a = world.a
    account = await _service_account(world, a)
    source = _source()
    long_title = "<b>Disk</b>\x00 full " + "very " * 80
    made = await _create(world, a, account, source, "P-11", subject=long_title)
    assert made.record_id is not None
    subject = (await _record(world, a, made.record_id))["subject"]
    assert len(subject) <= 250
    assert "\x00" not in subject
    assert subject.endswith("…")
    empty = await _create(world, a, account, source, "P-12", subject="  \x1b ")
    assert empty.record_id is not None
    assert (await _record(world, a, empty.record_id))["subject"] == "Monitoring problem P-12"


async def test_the_session_must_be_the_actor(world: World) -> None:
    a = world.a
    account = await _service_account(world, a)
    template = await _template(world, a)
    async with world.app.state.db.tenant_session(
        TenantContext(a.tenant, user_id=a.admin)
    ) as session:
        actor = await subject_for(session, a.tenant, account)
        with pytest.raises(ValueError, match="service account"):
            await work_items.create_from_external_problem(
                session, actor=actor, source=_source(), external_id="P-13", version=1,
                template_id=template, priority="p2", group_id=None, ci_ids=[], subject="x",
                opened_at=NOW,
            )  # fmt: skip


async def test_tenant_b_neither_sees_nor_writes_tenant_as_keys(world: World) -> None:
    a, b = world.a, world.b
    account = await _service_account(world, a)
    made = await _create(world, a, account, _source(), "P-14")
    assert made.record_id is not None
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        seen = (
            await session.execute(text("SELECT count(*) FROM work_item_external_keys"))
        ).scalar_one()
        assert seen == 0  # tenant B never sees tenant A's keys
        with pytest.raises(DBAPIError):  # RLS refuses a row for another tenant
            await session.execute(
                text(
                    "INSERT INTO work_item_external_keys (id, tenant_id, source_kind, source_id,"
                    " external_id, work_item_id, last_version) VALUES (:i, :t, 'monetx', :s,"
                    " 'x', :w, 1)"
                ),
                {"i": uuid.uuid4(), "t": a.tenant, "s": uuid.uuid4(), "w": made.record_id},
            )
