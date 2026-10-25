"""The audit log at volume (WP-018, D-076 item 11): sealing, verification, search, tampering.

Opt-in: SUPPORTX_AUDIT_SCALE_ROWS sets the number of entries (CI: 100,000 on every run; the
nightly workflow: 10,000,000). Without it the test is skipped. Rows are generated in Python and
loaded with COPY as the admin role into a fresh tenant of the throwaway database (COPY cannot
run under RLS); everything measured after that runs as the application role. Timings go to
SUPPORTX_AUDIT_SCALE_REPORT (JSON) when set, and to the test output.
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
from app.modules.audit.service.integrity import verify
from conftest import create_tenant
from tooling.db_testing import ThrowawayDatabase

pytestmark = [pytest.mark.db, pytest.mark.scale]

ROWS = int(os.environ.get("SUPPORTX_AUDIT_SCALE_ROWS", "0"))
CHUNK = 50_000
SEAL_BATCH = 5000  # the most audit_seal() takes per call
SEALS_PER_TRANSACTION = 10
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


def _rows(tenant: uuid.UUID, start: datetime, count: int, people: list[uuid.UUID]) -> Any:  # noqa: ANN401 - a generator of COPY records
    step = timedelta(days=30) / max(count, 1)
    rng = random.Random(18)  # noqa: S311 - test data, not security
    for i in range(count):
        action = ACTIONS[i % len(ACTIONS)]
        category, module = CATEGORY[action]
        row = {
            "id": uuid.uuid4(),
            "tenant_id": tenant,
            "occurred_at": start + step * i,
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


async def _load(db: ThrowawayDatabase, tenant: uuid.UUID, people: list[uuid.UUID]) -> datetime:
    start = datetime.now(UTC) - timedelta(days=30, hours=1)
    conn = await asyncpg.connect(db.admin_url)
    try:
        batch: list[tuple[Any, ...]] = []
        for record in _rows(tenant, start, ROWS, people):
            batch.append(record)
            if len(batch) == CHUNK:
                await _copy(conn, batch)
                batch = []
        if batch:
            await _copy(conn, batch)
    finally:
        await conn.close()
    return start


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


@pytest.mark.skipif(ROWS <= 0, reason="set SUPPORTX_AUDIT_SCALE_ROWS to run the volume test")
async def test_audit_log_at_volume(migrated_db: ThrowawayDatabase, app_db: Database) -> None:
    timings: dict[str, Any] = {"rows": ROWS}
    tenant = await create_tenant(migrated_db.migrator_url, "Scale")
    people = [uuid.uuid4() for _ in range(200)]

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

    # The screen's search: one person, the last 7 days, newest first, first page.
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        began = time.perf_counter()
        found = (
            await session.execute(
                text(
                    "SELECT id FROM audit_entries WHERE actor_id = :a"
                    " AND occurred_at >= now() - interval '7 days'"
                    " ORDER BY occurred_at DESC LIMIT 50"
                ),
                {"a": people[0]},
            )
        ).all()
        search_seconds = time.perf_counter() - began
    timings["search_ms"] = round(search_seconds * 1000, 1)
    assert found
    assert search_seconds < SEARCH_LIMIT_SECONDS

    # Change one entry in the middle behind the app's back: verification names its position.
    target = ROWS // 2
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
