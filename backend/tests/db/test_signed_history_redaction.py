"""Signed history redaction (ADR-046 addendum; D-171, ADR-052 S1b follow-up; migration 0167).

A mention's redaction blanks history rows a fingerprinted audit entry commits to as well, keeping
the field's digests; the verifier then reports those saves `redacted_on_request` (never
`verified`), and only because the redaction is logged in the chain. A changed digest, a missing
log entry, a closed erasure, another tenant, and app-role writes all fail closed.
"""

import uuid
from typing import Any, ClassVar

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules.audit import redact_signed_history
from app.modules.identity_access.service.person_data import (
    MentionBatch,
    register_mentions,
    unregister_mentions,
)
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_audit_api import run_verify, seal_all
from tests.db.test_incidents_api import Org, World
from tests.db.test_person_erasure_mentions import _get, _redact, _requested

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, re-used

SECRET = "Zainab Qureshi's tablet"


async def _incident(world: World, org: Org) -> dict[str, Any]:
    """Created and renamed: two signed saves whose subject names the person."""
    item = await world.create(
        org,
        org.admin,
        subject=SECRET,
        description="<p>It does not charge.</p>",
        requester_id=str(org.requester),
    )
    changed = await world.patch(org, org.admin, item, subject=f"{SECRET} still fails")
    assert changed.status_code == 200, changed.text
    return dict(changed.json())


async def _subject_rows(world: World, org: Org, item_id: str) -> list[Any]:
    return await world.sql(
        "SELECT id, old_value, new_value FROM field_changes WHERE tenant_id = $1"
        " AND record_type = 'work_item' AND record_id = $2 AND field = 'subject'"
        " AND change_id IN (SELECT unnest(fingerprint_saves) FROM audit_entries"
        " WHERE tenant_id = $1 AND object_id = $3 AND fingerprint IS NOT NULL)",
        org.tenant,
        uuid.UUID(item_id),
        item_id,
    )


async def _signed(world: World, org: Org, item_id: str) -> list[Any]:
    return await world.sql(
        "SELECT id FROM audit_entries WHERE tenant_id = $1 AND object_id = $2"
        " AND fingerprint IS NOT NULL ORDER BY occurred_at, id",
        org.tenant,
        item_id,
    )


async def _status(world: World, org: Org, entry_id: uuid.UUID) -> str:
    response = await world.call("GET", f"/audit/entries/{entry_id}", org, org.admin)
    assert response.status_code == 200, response.text
    return str(response.json()["fingerprint_status"])


async def _mention(
    world: World,
    org: Org,
    erasure_id: uuid.UUID,
    item_id: str,
    *,
    module: str = "probe",
    state: str = "found",
    redacted_by: uuid.UUID | None = None,
) -> uuid.UUID:
    mention_id = uuid.uuid4()
    await world.sql(
        "INSERT INTO person_erasure_mentions (tenant_id, id, erasure_id, module_key,"
        " record_type, record_id, field, match_kind, occurrences, state, redacted_by,"
        " redacted_at) VALUES ($1, $2, $3, $4, 'work_item', $5, 'subject', 'name', 1, $6, $7,"
        " CASE WHEN $7::uuid IS NULL THEN NULL ELSE now() END)",
        org.tenant,
        mention_id,
        erasure_id,
        module,
        uuid.UUID(item_id),
        state,
        redacted_by,
    )
    return mention_id


class Probe:
    """A stand-in work-item mention port: the record's text is the test's own."""

    module: ClassVar[str] = "probe"

    async def find_mentions(self, *_a: object, **_k: object) -> MentionBatch:
        return MentionBatch(())

    async def redact_mention(self, *_a: object, **_k: object) -> bool:
        return True

    async def passage(self, *_a: object, **_k: object) -> str | None:
        return SECRET


async def test_a_redaction_blanks_signed_history_and_verifies_as_redacted_on_request(
    world: World,
) -> None:
    a = world.a
    item = await _incident(world, a)
    rows = await _subject_rows(world, a, item["id"])
    assert len(rows) == 2
    assert all(r["new_value"] is not None for r in rows)
    erasure = await _requested(world, a)
    mention = await _mention(world, a, uuid.UUID(erasure["id"]), item["id"])
    version = (await _get(world, a, erasure))["version"]
    register_mentions(Probe())
    try:
        done = await _redact(world, a, erasure["id"], [str(mention)], version)
    finally:
        unregister_mentions("probe")
    assert done.status_code == 200, done.text
    assert [m["history_kept"] for m in done.json()["redacted"]] == [0]
    after = await _subject_rows(world, a, item["id"])
    assert all((r["old_value"], r["new_value"]) == (None, None) for r in after)
    kept = await world.sql(
        "SELECT field_change_id, salted, mention_id FROM field_change_redactions"
        " WHERE tenant_id = $1 AND record_id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert {r["field_change_id"] for r in kept} == {r["id"] for r in rows}
    assert {(r["salted"], r["mention_id"]) for r in kept} == {(True, mention)}  # subject: personal
    # The verifier: never "verified", never a mismatch; the run counts them.
    for entry in await _signed(world, a, item["id"]):
        assert await _status(world, a, entry["id"]) == "redacted_on_request"
    await seal_all(world, a)
    result = await run_verify(world, a)
    runs = await world.call("GET", "/audit/verification-runs", a, a.admin)
    run = next(r for r in runs.json() if r["id"] == str(result.run_id))
    assert run["fingerprints_redacted"] >= 2
    assert run["fingerprint_mismatches"] == 0
    # The erasure may now be approved as far as signed history goes (nothing kept).
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        from app.modules.identity_access.service import erasure_mentions  # noqa: PLC0415

        assert (
            await erasure_mentions.signed_history_kept(session, uuid.UUID(erasure["id"])) is False
        )


async def test_a_changed_digest_or_an_unlogged_redaction_is_a_mismatch(world: World) -> None:
    b = world.b
    erasure = await _requested(world, b)
    erasure_id = uuid.UUID(erasure["id"])
    # Not logged: the definer is called directly, with no `person.erasure_mention_redacted`.
    unlogged = await _incident(world, b)
    mention = await _mention(
        world, b, erasure_id, unlogged["id"], module="identity_access", state="redacted",
        redacted_by=b.admin,
    )  # fmt: skip
    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        blanked = await redact_signed_history(
            session, mention, "work_item", uuid.UUID(unlogged["id"]), "subject"
        )
    assert blanked == 2
    for entry in await _signed(world, b, unlogged["id"]):
        assert await _status(world, b, entry["id"]) == "mismatch"
    # Logged, then a kept digest is changed by someone with database access: a mismatch.
    tampered = await _incident(world, b)
    other = await _mention(world, b, erasure_id, tampered["id"])
    version = (await _get(world, b, erasure))["version"]
    register_mentions(Probe())
    try:
        done = await _redact(world, b, erasure["id"], [str(other)], version)
    finally:
        unregister_mentions("probe")
    assert done.status_code == 200, done.text
    entries = await _signed(world, b, tampered["id"])
    assert {await _status(world, b, e["id"]) for e in entries} == {"redacted_on_request"}
    await world.sql(
        "UPDATE field_change_redactions SET new_digest = repeat('0', 64)"
        " WHERE tenant_id = $1 AND record_id = $2",
        b.tenant,
        uuid.UUID(tampered["id"]),
    )
    assert {await _status(world, b, e["id"]) for e in entries} == {"mismatch"}


async def test_the_function_is_bound_to_an_open_redacted_mention_and_its_own_rows(
    world: World,
) -> None:
    a = world.a
    item = await _incident(world, a)
    erasure_id = uuid.UUID((await _requested(world, a))["id"])
    rows = await _subject_rows(world, a, item["id"])
    ids = [r["id"] for r in rows]
    call = text(
        "SELECT history_redact_signed(:m, CAST(:r AS uuid[]), CAST(:o AS text[]),"
        " CAST(:n AS text[]), CAST(:s AS boolean[]))"
    )

    async def run(mention: uuid.UUID, row_ids: list[uuid.UUID]) -> Any:  # noqa: ANN401 - jsonb
        params = {
            "m": mention,
            "r": [str(i) for i in row_ids],
            "o": ["x"] * len(row_ids),
            "n": ["y"] * len(row_ids),
            "s": [False] * len(row_ids),
        }
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            return await session.scalar(call, params)

    zero = {"blanked": 0, "recorded": 0}
    # Not redacted, or redacted with no redactor: nothing.
    assert await run(await _mention(world, a, erasure_id, item["id"]), ids) == zero
    unsigned = await _mention(world, a, erasure_id, item["id"], module="x", state="redacted")
    assert await run(unsigned, ids) == zero
    # A closed erasure: nothing, even for a fully redacted mention.
    closed = await _mention(
        world, a, erasure_id, item["id"], module="y", state="redacted", redacted_by=a.admin
    )
    await world.sql(
        "UPDATE person_erasures SET state = 'rejected' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        erasure_id,
    )
    assert await run(closed, ids) == zero
    await world.sql(
        "UPDATE person_erasures SET state = 'requested' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        erasure_id,
    )
    # Open again, but a row of another field is refused whole: nothing blanked.
    description = await world.sql(
        "SELECT id FROM field_changes WHERE tenant_id = $1 AND record_id = $2"
        " AND field = 'description' LIMIT 1",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    with pytest.raises(DBAPIError, match="not a signed history row"):
        await run(closed, [*ids, description[0]["id"]])
    assert all(r["new_value"] is not None for r in await _subject_rows(world, a, item["id"]))
    # A digest is only ever the fingerprint's hex form: anything else is refused, nothing blanked.
    with pytest.raises(DBAPIError, match="digest_form"):
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            await session.scalar(
                call,
                {
                    "m": closed,
                    "r": [str(ids[0])],
                    "o": ["the old text"],
                    "n": ["0" * 64],
                    "s": [False],
                },
            )
    assert all(r["new_value"] is not None for r in await _subject_rows(world, a, item["id"]))
    with pytest.raises(DBAPIError, match="one digest pair"):
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            await session.scalar(call, {"m": closed, "r": [str(ids[0])], "o": [], "n": [], "s": []})


async def test_tenant_b_sees_none_and_the_app_role_writes_none(world: World) -> None:
    a, b = world.a, world.b
    item = await _incident(world, a)
    erasure_id = uuid.UUID((await _requested(world, a))["id"])
    mention = await _mention(
        world, a, erasure_id, item["id"], module="z", state="redacted", redacted_by=a.admin
    )
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        assert (
            await redact_signed_history(
                session, mention, "work_item", uuid.UUID(item["id"]), "subject"
            )
            == 2
        )
        mine = await session.scalar(text("SELECT count(*) FROM field_change_redactions"))
    assert mine >= 2
    db = world.app.state.db
    async with db.tenant_session(TenantContext(b.tenant)) as session:
        theirs = await session.scalar(
            text("SELECT count(*) FROM field_change_redactions WHERE record_id = :r"),
            {"r": uuid.UUID(item["id"])},
        )
        assert theirs == 0
        # Tenant B's session cannot redact tenant A's history through A's mention either.
        assert (
            await redact_signed_history(
                session, mention, "work_item", uuid.UUID(item["id"]), "subject"
            )
            == 0
        )
    for statement in (
        "UPDATE field_change_redactions SET old_digest = 'x'",
        "DELETE FROM field_change_redactions",
        (
            "INSERT INTO field_change_redactions (tenant_id, id, field_change_id, change_id,"
            " record_type, record_id, field, mention_id, old_digest, new_digest, salted,"
            " redacted_at) SELECT tenant_id, gen_random_uuid(), field_change_id, change_id,"
            " record_type, record_id, field, mention_id, old_digest, new_digest, salted, now()"
            " FROM field_change_redactions LIMIT 1"
        ),
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with db.tenant_session(TenantContext(a.tenant)) as session:
                await session.execute(text(statement))


async def _task_mention(
    world: World,
    org: Org,
    erasure_id: uuid.UUID,
    task_id: uuid.UUID,
    *,
    field: str = "title",
    record_type: str = "work_item_task",
    redacted_by: uuid.UUID | None,
) -> uuid.UUID:
    mention_id = uuid.uuid4()
    await world.sql(
        "INSERT INTO person_erasure_mentions (tenant_id, id, erasure_id, module_key,"
        " record_type, record_id, field, match_kind, occurrences, state, redacted_by,"
        " redacted_at) VALUES ($1, $2, $3, $4, $5, $6, $7, 'name', 1, 'redacted', $8,"
        " CASE WHEN $8::uuid IS NULL THEN NULL ELSE now() END)",
        org.tenant,
        mention_id,
        erasure_id,
        f"probe-{mention_id.hex[:6]}",
        record_type,
        task_id,
        field,
        redacted_by,
    )
    return mention_id


async def _task_rows(world: World, org: Org, item_id: str) -> dict[uuid.UUID, tuple[Any, Any]]:
    rows = await world.sql(
        "SELECT id, old_value, new_value FROM field_changes WHERE tenant_id = $1"
        " AND record_type = 'work_item' AND record_id = $2 AND field LIKE 'task%'",
        org.tenant,
        uuid.UUID(item_id),
    )
    return {r["id"]: (r["old_value"], r["new_value"]) for r in rows}


async def test_a_task_mention_blanks_its_parent_s_task_history_naming_the_person(
    world: World,
) -> None:
    """Task text lives in the parent record's history; only rows naming the person go (0167).

    The person is read by the functions from the mention's own erasure: no caller passes terms.
    Unsigned rows are blanked by `history_redact_child`; signed ones are kept by it and blanked
    with their digests by `redact_signed_history`.
    """
    a = world.a
    name = (await world.sql("SELECT display_name FROM users WHERE id = $1", a.tech_a))[0][0]
    erasure_id = uuid.UUID((await _requested(world, a))["id"])
    item = await world.create(a, a.admin, group_id=str(a.ga))
    base = f"/incidents/{item['id']}/tasks"
    named = await world.call("POST", base, a, a.admin, json={"title": f"Call {name} back"})
    assert named.status_code == 201, named.text
    other = await world.call("POST", base, a, a.admin, json={"title": "Order a cable"})
    assert other.status_code == 201, other.text
    before = await _task_rows(world, a, item["id"])
    naming = {i for i, (o, n) in before.items() if name in f"{o} {n}"}
    assert naming
    assert len(naming) < len(before)
    task_id = uuid.UUID(named.json()["id"])
    call = text("SELECT history_redact_child(:m)")

    async def run(mention_id: uuid.UUID) -> Any:  # noqa: ANN401 - the function's jsonb
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            return await session.scalar(call, {"m": mention_id})

    zero = {"blanked": 0, "kept_fingerprinted": 0}
    # Not redacted by anyone, or not a task mention: nothing.
    assert await run(await _task_mention(world, a, erasure_id, task_id, redacted_by=None)) == zero
    not_task = await _task_mention(
        world, a, erasure_id, uuid.UUID(item["id"]), record_type="work_item", redacted_by=a.admin
    )
    assert await run(not_task) == zero
    assert await _task_rows(world, a, item["id"]) == before
    # The real one: every row naming the person is blanked or (signed) kept, nothing else.
    mention = await _task_mention(world, a, erasure_id, task_id, redacted_by=a.admin)
    first = await run(mention)
    assert first["blanked"] + first["kept_fingerprinted"] == len(naming)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await redact_signed_history(session, mention, "work_item_task", task_id, "title")
    after = await _task_rows(world, a, item["id"])
    for row_id, values in after.items():
        if row_id in naming:
            assert values == (None, None)
        else:
            assert values == before[row_id]  # the other task's history is untouched
    assert await run(mention) == zero  # idempotent: nothing named is left
    # A closed erasure blanks nothing (the other task's rows stay as they are).
    await world.sql(
        "UPDATE person_erasures SET state = 'rejected' WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        erasure_id,
    )
    assert await run(mention) == zero


async def test_task_history_matches_a_phone_per_run_and_skips_a_short_one_word_name(
    world: World,
) -> None:
    """0170: two numbers side by side are no phone; a short one-word display name is not
    searched on its own, while the full first + last name always is (lane C's #511 notes)."""
    a = world.a
    person = (
        await world.sql(
            "SELECT display_name, first_name, last_name, phone FROM users WHERE id = $1",
            a.tech_a,
        )
    )[0]
    await world.sql(
        "UPDATE users SET display_name = 'Ali', first_name = 'Ali', last_name = 'Raza',"
        " phone = '+92 300 1234567' WHERE id = $1",
        a.tech_a,
    )
    try:
        erasure_id = uuid.UUID((await _requested(world, a))["id"])
        item = await world.create(a, a.admin, group_id=str(a.ga))
        base = f"/incidents/{item['id']}/tasks"
        full = "Ali Raza"
        titles = {
            "phone": "Ring 0300-1234567 later",
            "joined": "IDs 0300 and 1234567",
            "short": "Ali to check the rack",
            "full": f"Thanks {full}",
        }
        made = {}
        for key, title in titles.items():
            created = await world.call("POST", base, a, a.admin, json={"title": title})
            assert created.status_code == 201, created.text
            made[key] = uuid.UUID(created.json()["id"])
        mention = await _task_mention(world, a, erasure_id, made["phone"], redacted_by=a.admin)
        async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
            ids = list(await session.scalars(text("SELECT history_child_rows(:m)"), {"m": mention}))
        rows = await _task_rows(world, a, item["id"])
        matched = " ".join(f"{rows[i][0]} {rows[i][1]}" for i in ids)
        assert titles["phone"] in matched
        assert titles["full"] in matched
        assert titles["joined"] not in matched
        assert titles["short"] not in matched
    finally:  # the shared world's person stays as it was
        await world.sql(
            "UPDATE users SET display_name = $2, first_name = $3, last_name = $4, phone = $5"
            " WHERE id = $1",
            a.tech_a,
            person["display_name"],
            person["first_name"],
            person["last_name"],
            person["phone"],
        )
