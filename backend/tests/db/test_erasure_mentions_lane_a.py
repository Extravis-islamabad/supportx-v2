"""Lane A's mentions ports (ADR-052 S2, D-171 a; lane B's six conditions).

Work items: the record's own text, its conversation, tasks and worklogs; integrations: the subject
of fetched mail. Each test runs the port as the registry runs it (cursor after cursor), then
redacts, checks the history row names the field only, search no longer finds the name, a second
redaction is a no-op, and the passage follows the reader's rights.
"""

import statistics
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest

from app.core.tenancy import TenantContext
from app.modules.identity_access import Mention, MentionMatchKind, MentionTerms, PersonMentions
from app.modules.integrations.service import person_mentions as mail_mentions
from app.modules.work_items.service import person_mentions
from tests.db.test_incidents_api import (  # noqa: F401 - the fixture
    BASE,
    CONSOLE,
    ROWS,
    SEED,
    World,
    make_org,
    world,
)
from tooling import timing

NAME = "Zara Quillfeather"
TERMS = MentionTerms(names=(NAME,))
MARKER = "erased_on_request"


async def _found(
    world: World,  # noqa: F811 - the fixture's name
    tenant: uuid.UUID,
    port: PersonMentions,
    person: uuid.UUID,
) -> list[Mention]:
    """Every mention the port finds, batch after batch (bounded: a port that never ends fails)."""
    found: list[Mention] = []
    cursor: str | None = None
    for _ in range(50):
        async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
            batch = await port.find_mentions(session, person, terms=TERMS, cursor=cursor)
        found += batch.mentions
        cursor = batch.cursor
        if cursor is None:
            return found
    msg = "the port never finished"
    raise AssertionError(msg)


async def _redact(world: World, tenant: uuid.UUID, port: PersonMentions, mention: Mention) -> bool:  # noqa: F811
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        return await port.redact_mention(
            session, mention, terms=TERMS, marker=MARKER, now=datetime.now(UTC)
        )


async def _passage(
    world: World,  # noqa: F811
    tenant: uuid.UUID,
    port: PersonMentions,
    user: uuid.UUID,
    mention: Mention,
) -> str | None:
    subject = await world.app.state.policy.subject(tenant, user)
    async with world.app.state.db.tenant_session(TenantContext(tenant)) as session:
        return await port.passage(session, subject, mention)


def _at(found: list[Mention], record_type: str, record_id: Any, field: str) -> Mention:  # noqa: ANN401
    matches = [
        m
        for m in found
        if m.record_type == record_type and str(m.record_id) == str(record_id) and m.field == field
    ]
    assert len(matches) == 1, found
    return matches[0]


async def test_a_name_in_a_record_s_text_is_found_redacted_and_no_longer_searchable(
    world: World,  # noqa: F811
) -> None:
    a = world.a
    made = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={"entity": "incident", "field_type": "text", "labels": {"en": "Caller"}},
        headers=CONSOLE,
    )
    key = made.json()["key"]
    item = await world.create(
        a,
        a.admin,
        group_id=str(a.ga),
        subject="Laptop will not start",
        description=f"<p>Reported by {NAME} at reception.</p>",
        custom={key: f"{NAME} (ext 42)"},
    )
    person = uuid.uuid4()  # someone else's text about them: not their own record
    found = await _found(world, a.tenant, person_mentions.PORT, person)
    described = _at(found, "incident", item["id"], "description")
    assert described.match_kind == MentionMatchKind.NAME
    assert described.occurrences == 1
    custom = _at(found, "incident", item["id"], f"custom.{key}")

    # The passage: the record's own read; someone who may not view the record gets nothing.
    assert NAME in (await _passage(world, a.tenant, person_mentions.PORT, a.admin, described) or "")
    assert await _passage(world, a.tenant, person_mentions.PORT, a.tech_b, described) is None

    assert await _redact(world, a.tenant, person_mentions.PORT, described) is True
    assert await _redact(world, a.tenant, person_mentions.PORT, custom) is True
    assert await _redact(world, a.tenant, person_mentions.PORT, described) is False  # idempotent
    (row,) = await world.sql(
        "SELECT description, custom, custom_text, version FROM work_items"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(item["id"]),
    )
    assert NAME not in row["description"]
    assert MARKER in row["description"]
    assert NAME not in str(row["custom"])
    assert NAME not in str(row["custom_text"])
    assert row["version"] == item["version"] + 2
    entries = await world.history(a, item)
    redacted = [
        c for e in entries for c in e["changes"] if c["field"] in {"description", f"custom.{key}"}
    ]
    assert {c["field"] for c in redacted} >= {"description", f"custom.{key}"}
    for change in redacted[:2]:
        assert change["old"] is None  # the field named, never the text
        assert change["new"] is None
    hits = await world.call("GET", f"{BASE}/search", a, a.admin, params={"q": "Quillfeather"})
    assert item["id"] not in [r["id"] for r in hits.json()["items"]]
    # The ordinary update event fired (lists, search and the AI re-embedding follow it).
    events = await world.sql(
        "SELECT envelope FROM outbox_events WHERE tenant_id = $1"
        " AND event_type = 'work_items.work_item.updated' AND aggregate_id = $2",
        a.tenant,
        item["id"],
    )
    assert any("description" in str(e["envelope"]) for e in events)


async def test_the_requester_s_own_record_skips_what_their_erasure_blanks_but_not_replies(
    world: World,  # noqa: F811
) -> None:
    """Lane B's condition 5: technicians' replies on their records stay and can name them."""
    a = world.a
    item = await world.create(
        a,
        a.admin,
        group_id=str(a.ga),
        requester_id=str(a.requester),
        description=f"<p>I am {NAME}.</p>",
    )
    noted = await world.call(
        "POST",
        f"{BASE}/{item['id']}/conversation",
        a,
        a.admin,
        json={"kind": "note", "body": f"<p>Called {NAME} back.</p>"},
        headers={"Idempotency-Key": str(uuid.uuid4()), **CONSOLE},
    )
    assert noted.status_code == 201, noted.text
    entry = noted.json()["entry"]["id"]
    found = await _found(world, a.tenant, person_mentions.PORT, a.requester)
    assert not [m for m in found if str(m.record_id) == item["id"]]  # blanked with them anyway
    note = _at(found, person_mentions.CONVERSATION, entry, "body")
    assert NAME in (await _passage(world, a.tenant, person_mentions.PORT, a.admin, note) or "")
    assert await _passage(world, a.tenant, person_mentions.PORT, a.tech_b, note) is None
    assert await _redact(world, a.tenant, person_mentions.PORT, note) is True
    (row,) = await world.sql(
        "SELECT body FROM work_item_conversations WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(entry),
    )
    assert NAME not in row["body"]
    assert await _redact(world, a.tenant, person_mentions.PORT, note) is False


async def test_tasks_and_worklogs_are_searched_and_redacted(world: World) -> None:  # noqa: F811
    """Lane B's condition 1: worklog descriptions are other people's text too."""
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga))
    task = await world.call(
        "POST",
        f"{BASE}/{item['id']}/tasks",
        a,
        a.admin,
        json={"title": f"Ring {NAME}", "description": f"{NAME} prefers mornings"},
        headers=CONSOLE,
    )
    assert task.status_code == 201, task.text
    logged = await world.call(
        "POST",
        f"{BASE}/{item['id']}/worklogs",
        a,
        a.tech_a,
        json={
            "worklog_type": "fix",
            "started_at": "2026-11-14T10:00:00Z",
            "minutes": 30,
            "description": f"Met {NAME} on site",
        },
    )
    assert logged.status_code == 201, logged.text
    found = await _found(world, a.tenant, person_mentions.PORT, uuid.uuid4())
    title = _at(found, person_mentions.TASK, task.json()["id"], "title")
    _at(found, person_mentions.TASK, task.json()["id"], "description")
    worklog = _at(found, person_mentions.WORKLOG, logged.json()["id"], "description")
    assert await _redact(world, a.tenant, person_mentions.PORT, title) is True
    assert await _redact(world, a.tenant, person_mentions.PORT, worklog) is True
    (task_row,) = await world.sql(
        "SELECT title FROM work_item_tasks WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(task.json()["id"]),
    )
    assert NAME not in task_row["title"]
    (log_row,) = await world.sql(
        "SELECT description FROM work_item_worklogs WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        uuid.UUID(logged.json()["id"]),
    )
    assert NAME not in log_row["description"]
    assert await _passage(world, a.tenant, person_mentions.PORT, a.tech_b, worklog) is None


async def test_a_field_the_reader_may_not_see_has_no_passage(world: World) -> None:  # noqa: F811
    """ADR-047: the record's own field rules apply to the passage, as to any read."""
    a = world.a
    item = await world.create(a, a.admin, group_id=str(a.ga), impact_details=f"{NAME} cannot work")
    (role,) = await world.sql(
        "SELECT id FROM roles WHERE tenant_id = $1 AND key = 'technician'", a.tenant
    )
    await world.sql(
        "INSERT INTO role_field_access (id, tenant_id, role_id, record_type, field, mode)"
        " VALUES (gen_random_uuid(), $1, $2, 'incident', 'impact_details', 'hidden')",
        a.tenant,
        role["id"],
    )
    await world.app.state.policy.invalidate(a.tenant)
    found = await _found(world, a.tenant, person_mentions.PORT, uuid.uuid4())
    impact = _at(found, "incident", item["id"], "impact_details")
    assert await _passage(world, a.tenant, person_mentions.PORT, a.tech_a, impact) is None


async def test_mail_subjects_from_others_are_found_and_their_own_mail_is_skipped(
    world: World,  # noqa: F811
) -> None:
    """Lane B's condition 6: the subject only; mail the person sent is their erasure port's."""
    a = world.a
    mailbox = uuid.uuid4()
    await world.sql(
        "INSERT INTO mailboxes (id, tenant_id, address, protocol, host, port, username,"
        " trusted_servers) VALUES ($1, $2, 'help@acme.test', 'imap', 'imap.acme.test', 993,"
        " 'help', '{mx.acme.test}')",
        mailbox,
        a.tenant,
    )
    (person,) = await world.sql(
        "SELECT email FROM users WHERE tenant_id = $1 AND id = $2", a.tenant, a.requester
    )
    for message, sender, subject in (
        ("<m1@acme.test>", "boss@acme.test", f"About {NAME}"),
        ("<m2@acme.test>", person["email"], f"From {NAME} herself"),
    ):
        await world.sql(
            "INSERT INTO mail_fetched (tenant_id, mailbox_id, message_id, sender, subject,"
            " outcome) VALUES ($1, $2, $3, $4, $5, 'created')",
            a.tenant,
            mailbox,
            message,
            sender,
            subject,
        )
    found = await _found(world, a.tenant, mail_mentions.PORT, a.requester)
    assert [m.record_id for m in found] == [mail_mentions.row_ref(mailbox, "<m1@acme.test>")]
    mention = found[0]
    assert await _passage(world, a.tenant, mail_mentions.PORT, a.tech_a, mention) is None
    assert NAME in (await _passage(world, a.tenant, mail_mentions.PORT, a.admin, mention) or "")
    assert await _redact(world, a.tenant, mail_mentions.PORT, mention) is True
    assert await _redact(world, a.tenant, mail_mentions.PORT, mention) is False
    (row,) = await world.sql(
        "SELECT subject FROM mail_fetched WHERE tenant_id = $1 AND message_id = '<m1@acme.test>'",
        a.tenant,
    )
    assert NAME not in row["subject"]


@pytest.mark.timing
async def test_the_records_scan_keeps_each_batch_fast_on_100k_records(world: World) -> None:  # noqa: F811
    """Lane B's #506 condition: no pre-filter yet, so each batch of the ordered scan is timed.

    100,000 incidents nightly, 1,000 in PRs (timing.volume); one in a hundred names the person.
    Each find_mentions call reads at most MENTION_BATCH rows: its p95 stays under 500 ms.
    """
    org = await make_org(world, "Mentions perf")
    await world.create(org, org.admin)  # seeds the tenant's configuration
    conn = await asyncpg.connect(world.db.admin_url)
    try:
        await conn.execute(
            SEED, org.tenant, org.requester, org.s1, org.ga, org.gb, org.tech_a, ROWS
        )
        await conn.execute(
            "UPDATE work_items SET description = '<p>Seen by ' || $2 || '.</p>'"
            " WHERE tenant_id = $1 AND display_number % 100 = 0",
            org.tenant,
            NAME,
        )
        named = await conn.fetchval(
            "SELECT count(*) FROM work_items WHERE tenant_id = $1 AND description LIKE $2",
            org.tenant,
            f"%{NAME}%",
        )
        await conn.execute("ANALYZE work_items")
    finally:
        await conn.close()
    timings: list[float] = []
    found = 0
    cursor: str | None = None
    for _ in range(ROWS // 100 + 10):  # bounded: a scan that never ends fails
        async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
            started = time.perf_counter()
            batch = await person_mentions.PORT.find_mentions(
                session, uuid.uuid4(), terms=TERMS, cursor=cursor
            )
            timings.append((time.perf_counter() - started) * 1000)
        found += sum(1 for m in batch.mentions if m.field == "description")
        cursor = batch.cursor
        if cursor is None:
            break
    assert cursor is None
    assert found == named  # every exact match, none missed
    timings.sort()
    p95 = timings[max(int(len(timings) * 0.95) - 1, 0)]
    report = {"p50_ms": round(statistics.median(timings), 1), "p95_ms": round(p95, 1)}
    timing.record("erasure_mentions_work_items_batch", report)
    assert p95 < timing.limit(500), report
