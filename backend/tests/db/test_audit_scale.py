"""The audit log at volume (WP-018, D-076 item 11): seal, verify, retention, search, tampering.

Opt-in: SUPPORTX_AUDIT_SCALE_ROWS sets the number of entries (CI: 100,000 on every run; the
nightly workflow: 10,000,000). Without it the test is skipped. Rows are generated in Python and
loaded with COPY as the admin role into a fresh tenant of the throwaway database (COPY cannot
run under RLS); everything measured after that runs as the application role, and retention
writes its archives to real S3-compatible storage (a fresh bucket).

80 % of the entries are spread over twelve months five years ago (past the 3-year retention),
the rest over the last 30 days. Timings go to SUPPORTX_AUDIT_SCALE_REPORT (JSON) when set, and
to the test output.
"""

import asyncio
import json
import os
import random
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.audit.domain.integrity import Problem, entry_hash
from app.modules.audit.infra.signing import LocalSigner, new_key_config, trusted_keys
from app.modules.audit.service.integrity import verify
from app.modules.audit.service.retention import (
    archive_next,
    drop_expired_partitions,
    month_start,
    next_month,
)
from app.shared.storage import S3Storage
from conftest import create_tenant
from tests.db.test_audit_exports import storage
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.scale]
__all__ = ["storage"]  # the fixture used below

SIGNER = LocalSigner.from_config(new_key_config("scale-key"))

ROWS = int(os.environ.get("SUPPORTX_AUDIT_SCALE_ROWS", "0"))
CHUNK = 50_000
SEAL_BATCH = 5000  # the most audit_seal() takes per call
SEALS_PER_TRANSACTION = 10
OLD_SHARE = 80  # percent of the entries past retention
SEARCH_LIMIT_SECONDS = 1.0  # the screen's first page, filtered by person and the last 7 days
ACTIONS = ("role.updated", "user.role_assigned", "incident.deleted", "read.audit_log")
COLUMNS = (
    "tenant_id",
    "occurred_at",
    "id",
    "action",
    "category",
    "module",
    "outcome",
    "reason_code",
    "actor_type",
    "actor_id",
    "on_behalf_id",
    "object_type",
    "object_id",
    "details",
    "client",
    "request_id",
    "change_id",
    "personal_commitments",
    "entry_hash",
)
CATEGORY = {
    "role.updated": ("access", "identity_access"),
    "user.role_assigned": ("access", "identity_access"),
    "incident.deleted": ("records", "work_items"),
    "read.audit_log": ("reads", "audit"),
}


def _times(count: int) -> Any:  # noqa: ANN401 - a generator of datetimes
    """`count` increasing times: OLD_SHARE % in twelve months five years ago, then 30 days."""
    old = count * OLD_SHARE // 100
    start = month_start(datetime.now(UTC) - timedelta(days=5 * 365))
    step = (next_month(start) - start) * 12 / max(old, 1)
    for i in range(old):
        yield start + step * i
    recent = datetime.now(UTC) - timedelta(days=30, hours=1)
    step = timedelta(days=30) / max(count - old, 1)
    for i in range(count - old):
        yield recent + step * i


def _rows(tenant: uuid.UUID, count: int, people: list[uuid.UUID]) -> Any:  # noqa: ANN401 - a generator of COPY records
    rng = random.Random(18)  # noqa: S311 - test data, not security
    for i, occurred_at in enumerate(_times(count)):
        action = ACTIONS[i % len(ACTIONS)]
        category, module = CATEGORY[action]
        row = {
            "id": uuid.uuid4(),
            "tenant_id": tenant,
            "occurred_at": occurred_at,
            "action": action,
            "category": category,
            "module": module,
            "outcome": "done",
            "reason_code": None,
            "actor_type": "person",
            "actor_id": rng.choice(people),
            "on_behalf_id": None,
            "object_type": "role",
            "object_id": f"obj-{i % 5000}",
            "details": {"n": i},
            "client": "console",
            "request_id": f"req-{i}",
            "change_id": None,
            "personal_commitments": {},
        }
        row["entry_hash"] = entry_hash(row)
        yield tuple(
            json.dumps(row[c], separators=(",", ":"))
            if c in {"details", "personal_commitments"}
            # asyncpg's jsonb codec takes text
            else row[c]
            for c in COLUMNS
        )


async def _load(db: ThrowawayDatabase, tenant: uuid.UUID, people: list[uuid.UUID]) -> None:
    conn = await asyncpg.connect(db.admin_url)
    try:
        await conn.execute("SELECT audit_ensure_partitions(1, 72)")  # months back to the old data
        batch: list[tuple[Any, ...]] = []
        for record in _rows(tenant, ROWS, people):
            batch.append(record)
            if len(batch) == CHUNK:
                await _copy(conn, batch)
                batch = []
        if batch:
            await _copy(conn, batch)
    finally:
        await conn.close()


async def _copy(conn: asyncpg.Connection, batch: list[tuple[Any, ...]]) -> None:
    await conn.copy_records_to_table("audit_entries", records=batch, columns=list(COLUMNS))
    await conn.copy_records_to_table(
        "audit_queue",
        records=[(r[0], r[2], r[1]) for r in batch],
        columns=["tenant_id", "entry_id", "occurred_at"],
    )


async def _seal_all(app_db: Database, tenant: uuid.UUID) -> int:
    sealed, done = 0, SEAL_BATCH
    while done == SEAL_BATCH:
        async with app_db.tenant_session(TenantContext(tenant)) as session:
            for _ in range(SEALS_PER_TRANSACTION):
                done = int(
                    await session.scalar(text("SELECT audit_seal(:n)"), {"n": SEAL_BATCH}) or 0
                )
                sealed += done
                if done < SEAL_BATCH:
                    break
    return sealed


async def _change_behind_the_apps_back(db: ThrowawayDatabase, tenant: uuid.UUID, seq: int) -> None:
    conn = await asyncpg.connect(db.admin_url)
    try:
        await conn.execute(
            "UPDATE audit_entries e SET details = '{\"n\": -1}'::jsonb FROM audit_chain c"
            " WHERE c.tenant_id = $1 AND c.seq = $2 AND e.id = c.entry_id"
            " AND e.occurred_at = c.entry_occurred_at",
            tenant,
            seq,
        )
    finally:
        await conn.close()


async def _retention(
    app_db: Database, tenant: uuid.UUID, store: S3Storage, old: int
) -> dict[str, Any]:
    """Archive every month past 3 years (read back, verified), cut off, drop; then re-verify."""
    timings: dict[str, Any] = {}
    archived = 0
    began = time.perf_counter()
    while True:
        async with app_db.tenant_session(TenantContext(tenant)) as session:
            row = await archive_next(
                session, storage=store, signer=SIGNER, trusted_keys=trusted_keys("", SIGNER)
            )
        if row is None:
            break
        assert row.status == "ready", row.problem
        archived += row.entries
        timings["archives"] = timings.get("archives", 0) + 1
    timings["archive_seconds"] = round(time.perf_counter() - began, 1)
    timings["archive_per_second"] = round(old / max(time.perf_counter() - began, 1e-9))
    assert archived == old
    async with app_db.platform_session() as session:
        began = time.perf_counter()
        timings["partitions_dropped"] = await drop_expired_partitions(session)
        timings["drop_seconds"] = round(time.perf_counter() - began, 1)
    assert timings["partitions_dropped"] >= 12  # the twelve old months
    # Archiving writes one audit entry per month; seal them so the run below is not "overdue".
    written = await _seal_all(app_db, tenant)
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        visible = await session.scalar(
            text("SELECT count(*) FROM audit_entries WHERE action <> 'audit.entries_archived'")
        )
        began = time.perf_counter()
        live = await verify(session, kind="weekly", trusted_keys={})
        timings["verify_after_retention_seconds"] = round(time.perf_counter() - began, 1)
    assert visible == ROWS - old
    assert live.status == "passed", live.finding
    assert live.entries_checked == ROWS - old + written
    return timings


async def _search(app_db: Database, tenant: uuid.UUID, person: uuid.UUID) -> float:
    """The screen's search: one person, the last 7 days, newest first, first page."""
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        began = time.perf_counter()
        found = (
            await session.execute(
                text(
                    "SELECT id FROM audit_entries WHERE actor_id = :a"
                    " AND occurred_at >= now() - interval '7 days'"
                    " ORDER BY occurred_at DESC LIMIT 50"
                ),
                {"a": person},
            )
        ).all()
        seconds = time.perf_counter() - began
    assert found
    return seconds


@pytest.mark.skipif(ROWS <= 0, reason="set SUPPORTX_AUDIT_SCALE_ROWS to run the volume test")
async def test_audit_log_at_volume(
    migrated_db: ThrowawayDatabase, app_db: Database, storage: S3Storage
) -> None:
    timings: dict[str, Any] = {"rows": ROWS}
    tenant = await create_tenant(migrated_db.migrator_url, "Scale")
    people = [uuid.uuid4() for _ in range(200)]
    old = ROWS * OLD_SHARE // 100

    began = time.perf_counter()
    await _load(migrated_db, tenant, people)
    timings["load_seconds"] = round(time.perf_counter() - began, 1)

    began = time.perf_counter()
    sealed = await _seal_all(app_db, tenant)
    seal_seconds = time.perf_counter() - began
    timings["seal_seconds"] = round(seal_seconds, 1)
    timings["seal_per_second"] = round(sealed / max(seal_seconds, 1e-9))
    assert sealed == ROWS

    began = time.perf_counter()
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        clean = await verify(session, kind="weekly", trusted_keys={})
    verify_seconds = time.perf_counter() - began
    timings["verify_seconds"] = round(verify_seconds, 1)
    timings["verify_per_second"] = round(ROWS / max(verify_seconds, 1e-9))
    assert clean.status == "passed", clean.finding
    assert clean.entries_checked == ROWS

    timings.update(await _retention(app_db, tenant, storage, old))
    search_seconds = await _search(app_db, tenant, people[0])
    timings["search_ms"] = round(search_seconds * 1000, 1)
    assert search_seconds < SEARCH_LIMIT_SECONDS

    # Change one entry in the middle behind the app's back: verification names its position.
    target = old + (ROWS - old) // 2
    await _change_behind_the_apps_back(migrated_db, tenant, target)
    began = time.perf_counter()
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        broken = await verify(session, kind="on_demand", trusted_keys={})
    timings["detect_seconds"] = round(time.perf_counter() - began, 1)
    assert broken.status == "failed"
    assert broken.finding is not None
    assert (broken.finding.seq, broken.finding.problem) == (target, Problem.ENTRY_CHANGED)

    print(json.dumps(timings))  # noqa: T201 - the measurements are the point of this test
    if report := os.environ.get("SUPPORTX_AUDIT_SCALE_REPORT"):
        await asyncio.to_thread(Path(report).write_text, json.dumps(timings, indent=2))
