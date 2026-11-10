"""Change-set fingerprints, per-subject salts and history erasure (WP-064 S2, D-150, ADR-046).

Each lifecycle save's entry holds a fingerprint of its values in record history, never the
values; the verifier recomputes it from `field_changes`. A person's salt makes their free text
erasable: erasure blanks it in history and destroys the salt, and the verifier then says
"erased on request", but only because the erasure itself is logged.
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from app.core.tenancy import TenantContext
from app.modules.audit.service.erasure import erase_subject
from app.modules.audit.service.recording import WORKER, record
from app.shared.history import Change, history, record_changes
from tests.db import test_incidents_api
from tests.db.test_audit_api import run_verify, seal_all
from tests.db.test_incidents_api import Org, World, incidents_world
from tooling import db_testing

pytestmark = [pytest.mark.db, pytest.mark.valkey]
world = test_incidents_api.world  # the incident world fixture, reused

SECRET = "Ahmed Raza's laptop"


async def _saves(world: World, org: Org, item_id: str) -> list[Any]:
    return await world.sql(
        "SELECT id, action, fingerprint, personal_fingerprint, fingerprint_saves,"
        " personal_subjects,"
        " row_to_json(e)::text AS raw FROM audit_entries e"
        " WHERE tenant_id = $1 AND object_id = $2 AND fingerprint IS NOT NULL"
        " ORDER BY occurred_at, id",
        org.tenant,
        item_id,
    )


async def _detail(world: World, org: Org, entry_id: uuid.UUID) -> dict[str, Any]:
    response = await world.call("GET", f"/audit/entries/{entry_id}", org, org.admin)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _verified(world: World, org: Org) -> Any:  # noqa: ANN401 - VerificationResult
    await seal_all(world, org)
    return await run_verify(world, org)


async def _run(world: World, org: Org, run_id: uuid.UUID) -> dict[str, Any]:
    runs = await world.call("GET", "/audit/verification-runs", org, org.admin)
    assert runs.status_code == 200, runs.text
    return next(r for r in runs.json() if r["id"] == str(run_id))


async def _incident(world: World, org: Org, requester: uuid.UUID) -> dict[str, Any]:
    item = await world.create(
        org,
        org.admin,
        subject=SECRET,
        description=f"<p>{SECRET} does not boot.</p>",
        requester_id=str(requester),
    )
    changed = await world.patch(org, org.admin, item, subject=f"{SECRET} still fails")
    assert changed.status_code == 200, changed.text
    return dict(changed.json())


async def _salt(world: World, org: Org, subject: uuid.UUID) -> Any:  # noqa: ANN401 - a row
    rows = await world.sql(
        "SELECT salt, erased_at FROM audit_subject_salts WHERE tenant_id = $1 AND subject_id = $2",
        org.tenant,
        subject,
    )
    return rows[0] if rows else None


# --- at save time -------------------------------------------------------------------------------


async def test_a_save_is_fingerprinted_without_its_values_and_verifies(world: World) -> None:
    a = world.a
    item = await _incident(world, a, a.requester)
    saves = await _saves(world, a, item["id"])
    assert len(saves) >= 2
    salt = await _salt(world, a, a.requester)
    assert salt is not None
    assert len(salt["salt"]) == 16
    assert salt["erased_at"] is None
    for entry in saves:
        assert entry["fingerprint"].startswith("fp1:")
        assert len(entry["fingerprint"]) == 68
        assert list(entry["personal_subjects"]) == [a.requester]  # free text: the requester's
        assert entry["fingerprint_saves"]
        assert entry["personal_fingerprint"].startswith("fp1:")  # the subject is salted in
        assert entry["personal_fingerprint"] != entry["fingerprint"]
        # No value, and no salt, in the stored entry ...
        assert "Ahmed" not in entry["raw"]
        assert "boot" not in entry["raw"]
        assert salt["salt"].hex() not in entry["raw"]
        # ... nor in what the API shows of it.
        detail = await _detail(world, a, entry["id"])
        text = json.dumps(detail)
        assert "Ahmed" not in text
        assert salt["salt"].hex() not in text
        assert detail["fingerprint_status"] == "verified"
    result = await _verified(world, a)
    assert result.status == "passed", result
    run = await _run(world, a, result.run_id)
    assert run["fingerprints_verified"] >= len(saves)
    assert (run["fingerprint_mismatches"], run["fingerprints_erased"]) == (0, 0)


async def test_a_save_without_free_text_uses_no_salt(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, requester_id=str(a.requester2))
    raised = await world.patch(a, a.admin, item, urgency="critical")
    assert raised.status_code == 200, raised.text
    last = (await _saves(world, a, item["id"]))[-1]
    assert list(last["personal_subjects"]) == []
    assert last["personal_fingerprint"] is None  # no personal field, no personal half
    assert (await _detail(world, a, last["id"]))["fingerprint_status"] == "verified"


# --- tampering ----------------------------------------------------------------------------------


async def test_a_changed_history_value_is_a_mismatch(world: World) -> None:
    a = world.a
    item = await _incident(world, a, a.requester)
    last = (await _saves(world, a, item["id"]))[-1]
    # Someone with database access rewrites the subject in record history (superuser: the
    # tenant is named explicitly, RLS does not bind it).
    await world.sql(
        "UPDATE field_changes SET new_value = '\"Nothing happened\"'::jsonb"
        " WHERE tenant_id = $1 AND record_id = $2 AND field = 'subject' AND change_id = $3",
        a.tenant,
        uuid.UUID(item["id"]),
        last["fingerprint_saves"][-1],
    )
    assert (await _detail(world, a, last["id"]))["fingerprint_status"] == "mismatch"
    result = await _verified(world, a)
    assert result.status == "failed"
    run = await _run(world, a, result.run_id)
    assert run["problem"] == "fingerprint_mismatch"
    assert run["first_broken_entry_id"] == str(last["id"])
    assert run["fingerprint_mismatches"] == 1
    # The chain itself is whole: only record history was changed.
    assert run["fingerprints_verified"] >= 1


async def test_a_removed_history_row_is_a_mismatch(world: World) -> None:
    b = world.b
    item = await _incident(world, b, b.requester)
    first = (await _saves(world, b, item["id"]))[0]
    await world.sql(
        "DELETE FROM field_changes WHERE tenant_id = $1 AND change_id = $2 AND field = 'priority'",
        b.tenant,
        first["fingerprint_saves"][0],
    )
    assert (await _detail(world, b, first["id"]))["fingerprint_status"] == "mismatch"


# --- erasure ------------------------------------------------------------------------------------


async def test_erasure_shows_erased_on_request_and_everyone_else_still_verifies(
    world: World,
) -> None:
    a = world.a
    erased = await _incident(world, a, a.requester)
    other = await _incident(world, a, a.requester2)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await erase_subject(session, a.requester)

    # The requester's free text is gone from record history; codes and IDs stay.
    values = await world.sql(
        "SELECT record_id, field, old_value, new_value FROM field_changes"
        " WHERE tenant_id = $1 AND record_id = ANY($2::uuid[])",
        a.tenant,
        [uuid.UUID(erased["id"]), uuid.UUID(other["id"])],
    )
    mine = [v for v in values if str(v["record_id"]) == erased["id"]]
    theirs = [v for v in values if str(v["record_id"]) == other["id"]]
    assert {v["field"] for v in mine if v["field"] in {"subject", "description"}}
    for v in mine:
        if v["field"] in {"subject", "description"}:
            assert (v["old_value"], v["new_value"]) == (None, None)
    assert any(v["field"] == "priority" and v["new_value"] is not None for v in mine)
    assert any(SECRET in (v["new_value"] or "") for v in theirs)
    salt = await _salt(world, a, a.requester)
    assert salt["salt"] is None
    assert salt["erased_at"] is not None

    for entry in await _saves(world, a, erased["id"]):
        assert (await _detail(world, a, entry["id"]))["fingerprint_status"] == "erased_on_request"
    for entry in await _saves(world, a, other["id"]):
        assert (await _detail(world, a, entry["id"]))["fingerprint_status"] == "verified"
    result = await _verified(world, a)
    assert result.status == "passed", result
    run = await _run(world, a, result.run_id)
    assert run["fingerprints_erased"] == len(await _saves(world, a, erased["id"]))
    assert run["fingerprints_verified"] >= len(await _saves(world, a, other["id"]))
    assert run["fingerprint_mismatches"] == 0
    (logged,) = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'audit.subject_erased' AND object_id = $2",
        a.tenant,
        str(a.requester),
    )
    details = json.loads(logged["details"])
    assert details["history_values_erased"] > 0
    assert details["salt_erased"] == 1

    # A later save on the erased person's ticket gets no fresh salt for them.
    later = await world.patch(a, a.admin, await world.fresh(a, erased), subject="Renamed")
    assert later.status_code == 200, later.text
    newest = (await _saves(world, a, erased["id"]))[-1]
    assert list(newest["personal_subjects"]) == []
    assert (await _detail(world, a, newest["id"]))["fingerprint_status"] == "verified"


async def test_an_ordinary_value_changed_before_an_erasure_is_still_a_mismatch(
    world: World,
) -> None:
    """The attack ADR-046 closes: change an ordinary value, then erase the subject."""
    a = world.a
    tampered = await _incident(world, a, a.requester)
    first = (await _saves(world, a, tampered["id"]))[0]
    assert first["personal_subjects"]  # the save lists the requester
    await world.sql(
        "UPDATE field_changes SET new_value = '\"p1\"'::jsonb"
        " WHERE tenant_id = $1 AND change_id = $2 AND field = 'priority'",
        a.tenant,
        first["fingerprint_saves"][0],
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await erase_subject(session, a.requester)
    # The erasure is logged and the salt is gone, yet the changed priority is still caught.
    assert (await _detail(world, a, first["id"]))["fingerprint_status"] == "mismatch"
    for entry in (await _saves(world, a, tampered["id"]))[1:]:
        assert (await _detail(world, a, entry["id"]))["fingerprint_status"] == "erased_on_request"
    result = await _verified(world, a)
    assert result.status == "failed"
    run = await _run(world, a, result.run_id)
    assert run["problem"] == "fingerprint_mismatch"
    assert run["first_broken_entry_id"] == str(first["id"])


async def test_an_ordinary_row_blanked_through_the_definer_is_a_mismatch(world: World) -> None:
    """The definer blanks any row of the person's saves it is given; blanking an ordinary one
    (the app passes personal rows only) shows as a mismatch, since that half has no salt."""
    b = world.b
    item = await _incident(world, b, b.requester)
    first = (await _saves(world, b, item["id"]))[0]
    rows = await world.sql(
        "SELECT id FROM field_changes"
        " WHERE tenant_id = $1 AND change_id = $2 AND field = 'priority'",
        b.tenant,
        first["fingerprint_saves"][0],
    )
    conn = await asyncpg.connect(world.db.app_direct_url)
    try:
        (result,) = await _in_tenant(
            conn,
            b.tenant,
            "SELECT audit_erase_subject($1, $2::uuid[]) AS r",
            b.requester,
            [r["id"] for r in rows],
        )
    finally:
        await conn.close()
    assert json.loads(result["r"])["history_values"] == 1
    assert (await _detail(world, b, first["id"]))["fingerprint_status"] == "mismatch"


REASON = "Ahmed Raza is on medical leave"


async def _worker_save(
    world: World,
    org: Org,
    record_type: str,
    record_id: str,
    changes: list[Change],
    reason: str | None,
) -> None:
    """A save from a worker (no route), with a free-text reason, as an SLA or rule save is."""
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await record_changes(
            session,
            record_type=record_type,
            record_id=uuid.UUID(record_id),
            version=9,
            kind="updated",
            changes=changes,
            source="system",
            reason=reason,
        )


async def _last_entry(world: World, org: Org, record_id: str) -> Any:  # noqa: ANN401 - a row
    return (await _saves(world, org, record_id))[-1]


async def _reasons(world: World, org: Org, change_id: uuid.UUID) -> list[Any]:
    rows = await world.sql(
        "SELECT reason FROM field_changes WHERE tenant_id = $1 AND change_id = $2",
        org.tenant,
        change_id,
    )
    return [r["reason"] for r in rows]


async def test_a_changed_reason_is_a_mismatch(world: World) -> None:
    a = world.a
    item = await world.create(a, a.admin, requester_id=str(a.requester))
    await _worker_save(world, a, "work_item", item["id"], [Change("priority", "p3", "p2")], REASON)
    last = await _last_entry(world, a, item["id"])
    # A work item's reason is personal: it makes a salted half even with no personal field.
    assert last["personal_fingerprint"] is not None
    assert list(last["personal_subjects"]) == [a.requester]
    assert "Ahmed" not in last["raw"]
    assert (await _detail(world, a, last["id"]))["fingerprint_status"] == "verified"
    await world.sql(
        "UPDATE field_changes SET reason = 'Nothing to see'"
        " WHERE tenant_id = $1 AND change_id = $2",
        a.tenant,
        last["fingerprint_saves"][-1],
    )
    assert (await _detail(world, a, last["id"]))["fingerprint_status"] == "mismatch"


async def test_an_erased_subjects_reason_is_blanked_and_reads_erased_on_request(
    world: World,
) -> None:
    b = world.b
    item = await world.create(b, b.admin, requester_id=str(b.requester))
    await _worker_save(world, b, "work_item", item["id"], [Change("priority", "p3", "p2")], REASON)
    last = await _last_entry(world, b, item["id"])
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        await erase_subject(session, b.requester)
    assert await _reasons(world, b, last["fingerprint_saves"][-1]) == [None]
    assert (await _detail(world, b, last["id"]))["fingerprint_status"] == "erased_on_request"
    (logged,) = await world.sql(
        "SELECT details FROM audit_entries WHERE tenant_id = $1"
        " AND action = 'audit.subject_erased' AND object_id = $2",
        b.tenant,
        str(b.requester),
    )
    assert json.loads(logged["details"])["history_reasons_erased"] >= 1


async def test_an_asset_saves_reason_is_ordinary_and_stays_verifiable(world: World) -> None:
    a = world.a
    asset = str(uuid.uuid4())
    await _worker_save(world, a, "asset", asset, [Change("location", "F1", "F2")], "Audit move")
    last = await _last_entry(world, a, asset)
    assert last["personal_fingerprint"] is None  # assets have no data subjects
    assert list(last["personal_subjects"]) == []
    # Someone else's erasure leaves it alone; it still verifies.
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await erase_subject(session, a.requester2)
    assert await _reasons(world, a, last["fingerprint_saves"][-1]) == ["Audit move"]
    assert (await _detail(world, a, last["id"]))["fingerprint_status"] == "verified"
    # And its reason is covered by the unsalted half.
    await world.sql(
        "UPDATE field_changes SET reason = 'Lost' WHERE tenant_id = $1 AND change_id = $2",
        a.tenant,
        last["fingerprint_saves"][-1],
    )
    assert (await _detail(world, a, last["id"]))["fingerprint_status"] == "mismatch"


async def test_the_previous_requester_is_a_subject_of_the_save_that_replaces_them(
    world: World,
) -> None:
    """Lane A: a save moving the requester may hold the old one's free text."""
    b = world.b
    item = await world.create(
        b, b.admin, subject=SECRET, requester_id=str(b.requester), description="<p>Mine</p>"
    )
    moved = await world.patch(
        b, b.admin, item, requester_id=str(b.requester2), subject=f"{SECRET} (handed over)"
    )
    assert moved.status_code == 200, moved.text
    last = await _last_entry(world, b, item["id"])
    assert set(last["personal_subjects"]) == {b.requester, b.requester2}
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        await erase_subject(session, b.requester)  # the previous requester
    assert (await _detail(world, b, last["id"]))["fingerprint_status"] == "erased_on_request"
    values = await world.sql(
        "SELECT field, old_value, new_value FROM field_changes"
        " WHERE tenant_id = $1 AND change_id = $2",
        b.tenant,
        last["fingerprint_saves"][-1],
    )
    subject = next(v for v in values if v["field"] == "subject")
    assert (subject["old_value"], subject["new_value"]) == (None, None)
    requester = next(v for v in values if v["field"] == "requester_id")
    assert requester["new_value"] is not None  # IDs are not personal: kept


async def test_a_missing_salt_without_a_logged_erasure_is_a_mismatch(world: World) -> None:
    b = world.b
    item = await _incident(world, b, b.requester2)
    # The salt is destroyed behind the audit log's back: no audit.subject_erased entry.
    await world.sql(
        "UPDATE audit_subject_salts SET salt = NULL, erased_at = now()"
        " WHERE tenant_id = $1 AND subject_id = $2",
        b.tenant,
        b.requester2,
    )
    for entry in await _saves(world, b, item["id"]):
        assert (await _detail(world, b, entry["id"]))["fingerprint_status"] == "mismatch"
    result = await _verified(world, b)
    assert result.status == "failed"
    assert (await _run(world, b, result.run_id))["problem"] == "fingerprint_mismatch"


# --- older entries ------------------------------------------------------------------------------


async def test_entries_without_a_fingerprint_verify_as_before(world: World) -> None:
    """Entries written before 0129 (S1 save entries, everything else) have no fingerprint."""
    b = world.b
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        await record(
            session,
            action_code="incident.updated",
            facts=WORKER,
            object_type="incident",
            object_id=uuid.uuid4(),
            details={"record_version": 2, "source": "ui"},
            events=["incident.updated"],
        )
        await record(session, action_code="audit.settings_changed", facts=WORKER, details={"x": 1})
    rows = await world.sql(
        "SELECT count(*) AS n FROM audit_entries WHERE tenant_id = $1 AND fingerprint IS NOT NULL",
        b.tenant,
    )
    assert rows[0]["n"] == 0
    result = await _verified(world, b)
    assert result.status == "passed", result
    run = await _run(world, b, result.run_id)
    assert (run["fingerprints_verified"], run["fingerprints_erased"]) == (0, 0)
    assert run["fingerprint_mismatches"] == 0


# --- the salts table: no app access, tenant isolation -------------------------------------------


async def _in_tenant(conn: asyncpg.Connection, tenant: uuid.UUID, query: str, *args: Any) -> Any:  # noqa: ANN401 - asyncpg
    async with conn.transaction():
        await conn.execute(f"SET LOCAL app.tenant_id = '{tenant}'")
        return await conn.fetch(query, *args)


async def test_the_app_role_cannot_touch_the_salts_table(world: World) -> None:
    a = world.a
    await _incident(world, a, a.requester)  # a salt exists
    conn = await asyncpg.connect(world.db.app_direct_url)
    try:
        for statement in (
            "SELECT * FROM audit_subject_salts",
            "SELECT count(*) FROM audit_subject_salts",
            (
                "INSERT INTO audit_subject_salts (tenant_id, subject_id, salt)"
                " VALUES (current_setting('app.tenant_id')::uuid, gen_random_uuid(), '\\x00')"
            ),
            "UPDATE audit_subject_salts SET salt = NULL",
            "DELETE FROM audit_subject_salts",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await _in_tenant(conn, a.tenant, statement)
    finally:
        await conn.close()


async def test_salts_are_per_tenant_and_never_replaced(world: World) -> None:
    a, b = world.a, world.b
    person = uuid.uuid4()
    salt_a, salt_b, other = os.urandom(16), os.urandom(16), os.urandom(16)
    ensure = "SELECT * FROM audit_subject_salts_ensure($1::uuid[], $2::bytea[])"
    read = "SELECT * FROM audit_subject_salts_of($1::uuid[])"
    conn = await asyncpg.connect(world.db.app_direct_url)
    try:
        assert [
            r["salt_bytes"] for r in await _in_tenant(conn, a.tenant, ensure, [person], [salt_a])
        ] == [salt_a]
        assert [
            r["salt_bytes"] for r in await _in_tenant(conn, b.tenant, ensure, [person], [salt_b])
        ] == [salt_b]
        # Never replaced; each tenant sees only its own.
        again = await _in_tenant(conn, a.tenant, ensure, [person], [other])
        assert [r["salt_bytes"] for r in again] == [salt_a]
        assert [r["salt_bytes"] for r in await _in_tenant(conn, a.tenant, read, [person])] == [
            salt_a
        ]
        assert [r["salt_bytes"] for r in await _in_tenant(conn, b.tenant, read, [person])] == [
            salt_b
        ]
        # Without a tenant: refused, and nothing to read.
        with pytest.raises(asyncpg.RaiseError):
            await conn.fetch(ensure, [person], [other])
        assert await conn.fetch(read, [person]) == []
        # Erasing in tenant A leaves tenant B's salt alone.
        await _in_tenant(conn, a.tenant, "SELECT audit_erase_subject($1, '{}'::uuid[])", person)
        assert await _in_tenant(conn, a.tenant, read, [person]) == []
        assert await _in_tenant(conn, a.tenant, ensure, [person], [other]) == []  # no fresh one
        assert [r["salt_bytes"] for r in await _in_tenant(conn, b.tenant, read, [person])] == [
            salt_b
        ]
    finally:
        await conn.close()
    # RLS is forced: even the table owner sees and writes only the tenant in app.tenant_id.
    owner = await asyncpg.connect(world.db.migrator_url)
    try:
        rows = await _in_tenant(
            owner,
            a.tenant,
            "SELECT tenant_id FROM audit_subject_salts WHERE subject_id = $1",
            person,
        )
        assert [r["tenant_id"] for r in rows] == [a.tenant]
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await _in_tenant(
                owner,
                a.tenant,
                "INSERT INTO audit_subject_salts (tenant_id, subject_id, salt) VALUES ($1, $2, $3)",
                b.tenant,
                uuid.uuid4(),
                salt_b,
            )
    finally:
        await owner.close()


async def test_erasure_blanks_only_rows_of_the_persons_saves(world: World) -> None:
    """The definer refuses to blank history rows of saves that do not list the person."""
    a = world.a
    theirs = await _incident(world, a, a.requester2)
    rows = await world.sql(
        "SELECT id FROM field_changes WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        uuid.UUID(theirs["id"]),
    )
    conn = await asyncpg.connect(world.db.app_direct_url)
    try:
        (result,) = await _in_tenant(
            conn,
            a.tenant,
            "SELECT audit_erase_subject($1, $2::uuid[]) AS r",
            a.requester,
            [r["id"] for r in rows],
        )
    finally:
        await conn.close()
    assert json.loads(result["r"])["history_values"] == 0
    for entry in await _saves(world, a, theirs["id"]):
        assert (await _detail(world, a, entry["id"]))["fingerprint_status"] == "verified"


# --- migration 0129 -----------------------------------------------------------------------------


@pytest.fixture
def own_db(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A database of its own: these tests migrate it down."""
    database = db_testing.create(db_config, migrate_to="head")
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


@pytest_asyncio.fixture
async def own_world(own_db: db_testing.ThrowawayDatabase) -> AsyncIterator[World]:
    async with incidents_world(own_db) as built:
        yield built


async def _functions(url: str) -> set[str]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT p.oid::regprocedure::text AS f FROM pg_proc p"
            " WHERE p.proname LIKE 'audit_%' AND p.pronamespace = 'public'::regnamespace"
        )
    finally:
        await conn.close()
    return {r["f"] for r in rows}


async def test_the_downgrade_refuses_while_fingerprinted_entries_exist(own_world: World) -> None:
    org = own_world.a
    await _incident(own_world, org, org.requester)
    with pytest.raises(Exception, match="downgrade refused"):
        await asyncio.to_thread(db_testing.downgrade, own_world.db.migrator_url, "0126")
    assert "audit_erase_subject(uuid,uuid[])" in await _functions(own_world.db.admin_url)


@pytest_asyncio.fixture
async def own_world_without_sink(
    own_db: db_testing.ThrowawayDatabase, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[World]:
    # Saves without the lifecycle sink write no fingerprinted entry, so the downgrade may run.
    monkeypatch.setattr(history, "_audit_sink", None)
    async with incidents_world(own_db) as built:
        yield built


async def test_the_migration_goes_down_and_up_without_fingerprints(
    own_world_without_sink: World,
) -> None:
    world = own_world_without_sink
    await world.create(world.a, world.a.admin, subject="No sink, no entry")
    url, admin = world.db.migrator_url, world.db.admin_url
    await asyncio.to_thread(db_testing.downgrade, url, "0126")
    functions = await _functions(admin)
    assert "audit_erase_subject(uuid)" in functions  # 0014's version is back
    assert not {f for f in functions if "salts" in f or f == "audit_erase_subject(uuid,uuid[])"}
    await asyncio.to_thread(db_testing.migrate, url)
    functions = await _functions(admin)
    assert "audit_erase_subject(uuid)" not in functions
    assert {
        "audit_erase_subject(uuid,uuid[])",
        "audit_subject_salts_ensure(uuid[],bytea[])",
        "audit_subject_salts_of(uuid[])",
    } <= functions
