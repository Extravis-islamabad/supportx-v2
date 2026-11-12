"""An import batch's rows written together (WP-049b S4c follow-up, step B; shared/db/deferred.py).

The batch savepoint buffers its rows' outbox events, field history, audit entries and new
valuations and writes them as one INSERT per table. These tests hold it to the conditions the
coordinator and lanes A and C set: the same history, events and audit entries as a row-by-row
import (a), a rolled-back savepoint's rows never written (b, lane C), reads and bypassing writes
refused while rows wait (c), statements chunked under the parameter limit (d), one lifecycle
entry per imported row (e), and a chain that seals and verifies (f).
"""

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import event, insert, select

from app.core.tenancy import TenantContext
from app.modules.assets.service import imports
from app.shared.db import deferred as deferred_module
from app.shared.db.deferred import deferred, deferred_writes
from app.shared.events.outbox import OutboxEvent
from app.shared.history import Change, FieldChange, record_changes
from tests.db import test_incidents_api
from tests.db.test_asset_import_batches import _checked, _counts, _run_for_real, _site
from tests.db.test_assets_api import _add, _product
from tests.db.test_audit_api import run_verify, seal_all
from tests.db.test_incidents_api import Org, World

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db
world = test_incidents_api.world  # the incident world fixture, reused

RECORD_TYPE = "deferred_test"  # no audit sink handles it: history rows only


def _session(world: World, org: Org) -> Any:  # noqa: ANN401 - the tenant session's context manager
    return world.app.state.db.tenant_session(TenantContext(org.tenant, org.admin))


async def _history_of(world: World, org: Org, record_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    rows = await world.sql(
        "SELECT DISTINCT record_id FROM field_changes WHERE tenant_id = $1 AND record_id = ANY($2)",
        org.tenant,
        record_ids,
    )
    return {r["record_id"] for r in rows}


async def _save(session: "AsyncSession", record_id: uuid.UUID) -> uuid.UUID:
    return await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record_id,
        version=1,
        kind="created",
        changes=[Change("name", None, "x"), Change("note", None, "y")],
        source="import",
    )


def _without_ids(payload: dict[str, Any]) -> dict[str, Any]:
    """An event's payload without the IDs that differ between two imports of one file."""
    return {k: v for k, v in payload.items() if k != "asset_id"}


# --- (a) the full matrix: the same outcome as row by row -----------------------------------------


def _file(tag: str, product: str, held_tag: str, here: str, there: str) -> bytes:
    lines = [
        "Name,Product,Serial number,Tag,Site,Location",
        f"Alpha,{product},D-{tag}-1,,{here},",
        f"Taken,{product},D-{tag}-2,{held_tag},,",  # refused when saved: the batch is redone
        f"Moved,{product},D-{tag}-0,,{there},Rack 9",  # an update with a site change
        f"Delta,{product},D-{tag}-4,,{here},",
        f"Nowhere,{product},D-{tag}-5,,No such site {tag},",  # refused when checked
        f"Echo,{product},D-{tag}-6,,,",
    ]
    return ("\n".join(lines) + "\n").encode()


async def _import_once(
    world: World, org: Org, product: str, here: str, there: str, product_id: str
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """A dry run then the run of the matrix file, with fresh serials. Returns both jobs."""
    tag = uuid.uuid4().hex[:6]
    held = await _add(world, org, {"name": "Holder", "product_id": product_id})
    assert held.status_code == 201, held.text
    moved = await _add(
        world, org, {"name": "Moved", "product_id": product_id, "serial_number": f"D-{tag}-0"}
    )
    assert moved.status_code == 201, moved.text
    content = _file(tag, product, held.json()["tag"], here, there)
    marker = (await world.sql("SELECT clock_timestamp() AS at"))[0]["at"]
    checked = await _checked(world, org, content)
    done = await _run_for_real(world, org, checked, org.admin)
    return checked, done, tag, marker


async def _outcome(world: World, org: Org, tag: str, marker: Any) -> dict[str, Any]:  # noqa: ANN401 - a timestamp
    """Per serial: the import's history rows, outbox events and audit entries, made comparable."""
    assets = await world.sql(
        "SELECT id, serial_number, tag FROM assets WHERE tenant_id = $1 AND serial_number LIKE $2",
        org.tenant,
        f"D-{tag}-%",
    )
    found: dict[str, Any] = {}
    for asset in assets:
        key = asset["serial_number"].replace(tag, "T")
        history = await world.sql(
            "SELECT change_id, kind, field, old_value::text AS old, new_value::text AS new, source"
            " FROM field_changes WHERE tenant_id = $1 AND record_id = $2 AND source = 'import'"
            " ORDER BY field",
            org.tenant,
            asset["id"],
        )
        events = await world.sql(
            "SELECT event_type, envelope->'payload' AS payload FROM outbox_events"
            " WHERE tenant_id = $1 AND aggregate_id = $2 AND created_at >= $3",
            org.tenant,
            str(asset["id"]),
            marker,
        )
        entries = await world.sql(
            "SELECT id, action, events, change_id, fingerprint IS NOT NULL AS printed"
            " FROM audit_entries WHERE tenant_id = $1 AND object_id = $2 AND occurred_at >= $3",
            org.tenant,
            str(asset["id"]),
            marker,
        )

        recorded = await world.sql(
            "SELECT count(*) AS n FROM outbox_events WHERE tenant_id = $1"
            " AND event_type = 'audit.entry.recorded' AND aggregate_id = ANY($2)",
            org.tenant,
            [str(e["id"]) for e in entries],
        )
        valuations = await world.sql(
            "SELECT book_value, total_cost FROM asset_valuations"
            " WHERE tenant_id = $1 AND asset_id = $2",
            org.tenant,
            asset["id"],
        )

        def plain(value: str | None, asset: Any = asset) -> str | None:  # noqa: ANN401 - a row
            if value is None:
                return None
            return value.replace(tag, "T").replace(str(asset["tag"]), "<tag>")

        found[key] = {
            "history": sorted(
                (h["kind"], h["field"], plain(h["old"]), plain(h["new"]), h["source"])
                for h in history
            ),
            "events": sorted(
                (e["event_type"], json.dumps(_without_ids(json.loads(e["payload"]))))
                for e in events
            ),
            "entry_events": recorded[0]["n"],
            "valuations": [(v["book_value"], v["total_cost"]) for v in valuations],
            "entries": sorted(
                (e["action"], tuple(e["events"] or ()), e["printed"]) for e in entries
            ),
            "one_entry_per_save": len(entries) == len({h["change_id"] for h in history}),
            "entries_link_history": {e["change_id"] for e in entries}
            == {h["change_id"] for h in history},
        }
    return found


async def test_a_batch_writes_what_row_by_row_writes_and_the_dry_run_agrees(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = world.a
    tag = uuid.uuid4().hex[:6]
    product = f"Deferred laptop {tag}"
    product_id = await _product(world, a, "laptop", product)
    here, there = f"Deferred here {tag}", f"Deferred there {tag}"
    await _site(world, a, here)
    await _site(world, a, there)
    field = await world.call(
        "POST",
        "/custom-fields",
        a,
        a.admin,
        json={
            "entity": "asset",
            "field_type": "text",
            "labels": {"en": f"Cost centre {tag}"},
            "default": "CC-DEFAULT",
        },
    )
    assert field.status_code == 201, field.text

    # Count the rows each deferred block wrote, so the test knows the buffer was used.
    flushed: list[int] = []
    real_flush = deferred_module.flush_deferred

    async def counting(session: "AsyncSession") -> None:
        buffer = deferred(session)
        flushed.append(buffer.pending() if buffer is not None else 0)
        await real_flush(session)

    monkeypatch.setattr(deferred_module, "flush_deferred", counting)
    checked, done, batched_tag, marker = await _import_once(
        world, a, product, here, there, product_id
    )
    assert sum(flushed) > 0, "the batch path wrote nothing through the buffer"
    # The dry run agrees with the run: counts and the exact problems.
    assert (_counts(checked), checked["problems"]) == (_counts(done), done["problems"])
    assert _counts(done) == (3, 1, 2)
    assert [(p["row"], p["field"], p["code"]) for p in done["problems"]] == [
        (3, "tag", "asset_tag_taken"),
        (6, "site", "site_not_found"),
    ]
    batched = await _outcome(world, a, batched_tag, marker)

    # The same file row by row: every row in its own savepoint, no buffer.
    # The import's own redo path is the reference (private by design, so no public name).
    one_by_one = imports._one_by_one  # noqa: SLF001

    async def row_by_row(
        session: "AsyncSession",
        how: "imports._How",
        plans: "Sequence[imports.Plan]",
        tally: "imports._Tally",
    ) -> int:
        return await one_by_one(session, how, plans, tally)

    monkeypatch.setattr(imports, "_apply_chunk", row_by_row)
    flushed.clear()
    checked_rows, done_rows, rows_tag, rows_marker = await _import_once(
        world, a, product, here, there, product_id
    )
    assert flushed == []
    assert (_counts(checked_rows), checked_rows["problems"]) == (_counts(done), done["problems"])
    assert (_counts(done_rows), done_rows["problems"]) == (_counts(done), done["problems"])
    by_rows = await _outcome(world, a, rows_tag, rows_marker)

    assert set(batched) == {"D-T-0", "D-T-1", "D-T-4", "D-T-6"}
    assert batched == by_rows
    for key, outcome in batched.items():
        assert outcome["history"], key
        assert [e[0] for e in outcome["events"]] == ["assets.asset.changed"], key
        assert outcome["entry_events"] == 1, key  # the entry's audit.entry.recorded
        # (e) one lifecycle entry per imported row, with its events, linked to its history.
        assert len(outcome["entries"]) == 1, key
        action, events, printed = outcome["entries"][0]
        assert events, key
        assert events[0] == action, key
        assert printed, key
        assert outcome["one_entry_per_save"], key
        assert outcome["entries_link_history"], key
    assert ("updated", "site_id") in {(h[0], h[1]) for h in batched["D-T-0"]["history"]}
    assert any(h[1].startswith("custom.") for h in batched["D-T-1"]["history"])
    assert all(len(batched[k]["valuations"]) == 1 for k in ("D-T-1", "D-T-4", "D-T-6"))


# --- (e, f) a whole batch: one entry per row, and the chain verifies ----------------------------


async def test_a_batch_has_one_entry_per_row_and_its_chain_seals_and_verifies(
    world: World,
) -> None:
    a = world.b  # a tenant of its own: the chain holds only this test's entries and the world's
    tag = uuid.uuid4().hex[:6]
    product = f"Chain laptop {tag}"
    await _product(world, a, "laptop", product)
    rows = 150  # more than one batch
    lines = ["Name,Product,Serial number"]
    lines += [f"Chain {n},{product},C-{tag}-{n:04d}" for n in range(1, rows + 1)]
    checked = await _checked(world, a, ("\n".join(lines) + "\n").encode(), mode="add")
    done = await _run_for_real(world, a, checked, a.admin)
    assert _counts(done) == (rows, 0, 0)
    entries = await world.sql(
        "SELECT e.id, e.action, e.events, e.change_id FROM audit_entries e"
        " JOIN assets x ON x.tenant_id = e.tenant_id AND e.object_id = x.id::text"
        " WHERE e.tenant_id = $1 AND x.serial_number LIKE $2",
        a.tenant,
        f"C-{tag}-%",
    )
    assert len(entries) == rows
    assert all(e["events"] and e["events"][0] == e["action"] for e in entries)
    assert len({e["change_id"] for e in entries}) == rows
    queued = await world.sql(
        "SELECT count(*) AS n FROM audit_queue WHERE tenant_id = $1 AND entry_id = ANY($2)",
        a.tenant,
        [e["id"] for e in entries],
    )
    assert queued[0]["n"] == rows
    await seal_all(world, a)
    links = await world.sql(
        "SELECT entry_id, count(*) AS n FROM audit_chain WHERE tenant_id = $1"
        " AND entry_id = ANY($2) GROUP BY entry_id",
        a.tenant,
        [e["id"] for e in entries],
    )
    assert len(links) == rows
    assert all(link["n"] == 1 for link in links)
    result = await run_verify(world, a)
    assert (result.status, result.finding) == ("passed", None)
    run = await world.sql(
        "SELECT fingerprints_verified, fingerprint_mismatches FROM audit_verification_runs"
        " WHERE tenant_id = $1 AND id = $2",
        a.tenant,
        result.run_id,
    )
    assert run[0]["fingerprint_mismatches"] == 0
    assert run[0]["fingerprints_verified"] >= rows


# --- (b) a rolled-back savepoint inside the block (lane C) --------------------------------------


async def test_a_rolled_back_savepoint_in_the_block_writes_none_of_its_rows(world: World) -> None:
    a = world.a
    outer, dropped, inner_kept, after = (uuid.uuid4() for _ in range(4))
    async with _session(world, a) as session, deferred_writes(session):
        await _save(session, outer)
        savepoint = await session.begin_nested()
        await _save(session, dropped)
        nested = await session.begin_nested()  # a savepoint inside the rolled-back one
        await _save(session, uuid.uuid4())
        await nested.commit()
        await savepoint.rollback()
        kept = await session.begin_nested()
        await _save(session, inner_kept)
        await kept.commit()
        await _save(session, after)
        buffer = deferred(session)
        assert buffer is not None
        assert buffer.pending() == 6  # 2 rows each, 3 saves kept
    written = await _history_of(world, a, [outer, dropped, inner_kept, after])
    assert written == {outer, inner_kept, after}


async def _fail_inside(session: "AsyncSession", record_id: uuid.UUID) -> None:
    async with deferred_writes(session):
        await _save(session, record_id)
        raise LookupError


async def test_an_exception_in_the_block_writes_nothing(world: World) -> None:
    a = world.a
    record_id = uuid.uuid4()
    async with _session(world, a) as session:
        with pytest.raises(LookupError):
            await _fail_inside(session, record_id)
        assert deferred(session) is None
    assert await _history_of(world, a, [record_id]) == set()


async def test_a_dropped_block_writes_nothing(world: World) -> None:
    a = world.a
    record_id = uuid.uuid4()
    async with _session(world, a) as session, deferred_writes(session, write=False):
        await _save(session, record_id)
    assert await _history_of(world, a, [record_id]) == set()


# --- (c) the guard -------------------------------------------------------------------------------


async def test_reading_a_deferred_table_while_rows_wait_raises(world: World) -> None:
    a = world.a
    async with _session(world, a) as session:
        async with deferred_writes(session):
            await session.execute(select(FieldChange.id).limit(1))  # nothing waits yet: allowed
            await _save(session, uuid.uuid4())
            with pytest.raises(RuntimeError, match="field_changes read before flush"):
                await session.execute(select(FieldChange.id).limit(1))
            buffer = deferred(session)
            assert buffer is not None
            buffer.clear()  # leave the block cleanly; the test's transaction is rolled back
        await session.rollback()


async def test_an_immediate_insert_into_the_outbox_while_rows_wait_raises(world: World) -> None:
    """Only an existing asset's valuation may still be written at once (lane C's #449 review): a
    Core INSERT into the outbox (or any other guarded table) is refused while rows wait."""
    a = world.a
    async with _session(world, a) as session:
        async with deferred_writes(session):
            await _save(session, uuid.uuid4())
            with pytest.raises(RuntimeError, match="outbox_events written around the buffer"):
                await session.execute(
                    insert(OutboxEvent).values(
                        id=uuid.uuid4(), tenant_id=a.tenant, event_type="probe.probe"
                    )
                )
            buffer = deferred(session)
            assert buffer is not None
            buffer.clear()  # leave the block cleanly; the test's transaction is rolled back
        await session.rollback()


async def test_a_row_added_around_the_buffer_raises_at_flush(world: World) -> None:
    a = world.a
    async with _session(world, a) as session:
        async with deferred_writes(session):
            await _save(session, uuid.uuid4())
            session.add(
                FieldChange(
                    tenant_id=a.tenant,
                    record_type=RECORD_TYPE,
                    record_id=uuid.uuid4(),
                    record_version=1,
                    change_id=uuid.uuid4(),
                    kind="created",
                    field="name",
                    actor_type="system",
                    source="import",
                    occurred_at=datetime.now(UTC),
                )
            )
            with pytest.raises(RuntimeError, match="field_changes written around the buffer"):
                await session.flush()
            session.expunge_all()
            buffer = deferred(session)
            assert buffer is not None
            buffer.clear()
        await session.rollback()


# --- (d) chunks under the parameter limit ------------------------------------------------------


async def test_a_flush_larger_than_one_statement_is_chunked(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = world.a
    columns = len(FieldChange.__table__.columns)
    monkeypatch.setattr(deferred_module, "MAX_BIND_PARAMS", columns * 3)  # 3 rows a statement
    ids = [uuid.uuid4() for _ in range(5)]  # 2 rows each: 10 rows, 4 statements
    inserts: list[str] = []

    def count(_conn: "Connection", _cursor: object, statement: str, *_rest: object) -> None:
        if statement.lstrip().startswith("INSERT INTO field_changes"):
            inserts.append(statement)

    async with _session(world, a) as session:
        connection = (await session.connection()).sync_connection
        assert connection is not None
        event.listen(connection, "before_cursor_execute", count)
        try:
            async with deferred_writes(session):
                for record_id in ids:
                    await _save(session, record_id)
        finally:
            event.remove(connection, "before_cursor_execute", count)
    assert len(inserts) == 4
    assert await _history_of(world, a, ids) == set(ids)
    rows = await world.sql(
        "SELECT count(*) AS n, count(DISTINCT id) AS ids FROM field_changes"
        " WHERE tenant_id = $1 AND record_id = ANY($2)",
        a.tenant,
        ids,
    )
    assert (rows[0]["n"], rows[0]["ids"]) == (10, 10)
