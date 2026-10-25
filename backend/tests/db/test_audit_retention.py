"""Retention of the audit log (WP-018; D-076 items 4 and 10): archive, cut-off, partitions, restore.

Real PostgreSQL and real S3-compatible storage (fixtures from test_audit_exports). Entries are
written with a frozen clock years in the past, into partitions created for the test.
"""

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import TenantContext
from app.modules.audit.domain.catalogue import AuditActorType, AuditClient
from app.modules.audit.infra.models import (
    AuditArchive,
    AuditCutoff,
    AuditEntry,
    AuditPersonal,
    AuditRestored,
)
from app.modules.audit.service.integrity import archived_through, seal, verify
from app.modules.audit.service.queries import integrity_status
from app.modules.audit.service.recording import RequestFacts, record
from app.modules.audit.service.retention import (
    archive_next,
    drop_expired_partitions,
    expire_restored,
    month_start,
    next_month,
    request_restore,
    restore,
    restored_entries,
)
from app.modules.audit.tools.verify_export import verify as verify_zip
from app.shared.clock import FrozenClock
from app.shared.storage import S3Storage
from tests.db.test_audit_api import auditor
from tests.db.test_audit_exports import SIGNER, TRUSTED, storage, world
from tests.db.test_incidents_api import World

pytestmark = [pytest.mark.db, pytest.mark.valkey]
__all__ = ["storage", "world"]  # fixtures used by the tests below

NOW = datetime.now(UTC)
OLD = month_start(NOW - timedelta(days=4 * 365)) + timedelta(days=3, hours=10)
FIVE_YEARS = month_start(NOW - timedelta(days=5 * 365)) + timedelta(days=3, hours=10)
PERSON = RequestFacts(AuditClient.API, "req-old", "10.9.8.7", "Test")


async def _old_entries(world: World, org: Any, *batches: tuple[datetime, int]) -> None:  # noqa: ANN401 - Org
    """Entries back in time, sealed together (sealing orders by time, as it does live)."""
    async with world.app.state.db.platform_session() as session:
        await session.execute(text("SELECT audit_ensure_partitions(1, 60)"))
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        for when, count in batches:
            for i in range(count):
                await record(
                    session,
                    action_code="audit.settings_changed",
                    facts=PERSON,
                    details={"n": i},
                    actor=(AuditActorType.PERSON, org.admin),
                    clock=FrozenClock(when + timedelta(minutes=i)),
                )
        await seal(session, 500)


async def _archive_all(world: World, org: Any, store: S3Storage | None) -> list[AuditArchive]:  # noqa: ANN401 - Org
    done: list[AuditArchive] = []
    for _ in range(80):
        async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
            row = await archive_next(session, storage=store, signer=SIGNER, trusted_keys=TRUSTED)
        if row is None:
            break
        done.append(row)
        if row.status != "ready":
            break
    return done


async def _visible(world: World, org: Any, model: type, before: datetime) -> int:  # noqa: ANN401 - Org
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(model).where(model.occurred_at < before)  # type: ignore[attr-defined]  # both models have it
            )
            or 0
        )


async def test_months_past_retention_are_archived_verified_hidden_and_dropped(
    world: World, storage: S3Storage
) -> None:
    # Only this test writes five years back, so it alone decides whether that partition can go.
    org = world.a
    await _old_entries(
        world, org, (FIVE_YEARS, 3), (next_month(month_start(FIVE_YEARS)) + timedelta(days=2), 2)
    )
    archives = await _archive_all(world, org, storage)

    first, second = archives[0], archives[1]
    assert [a.status for a in archives] == ["ready"] * len(archives)
    assert (first.range_from, first.entries, second.entries) == (month_start(FIVE_YEARS), 3, 2)
    assert second.first_seq == (first.last_seq or 0) + 1  # one contiguous chain
    assert archives[-1].range_to <= NOW - timedelta(days=1095)  # never inside retention

    # The archive in storage verifies offline and holds no personal data.
    payload = await storage.get(first.object_key or "")
    assert payload is not None
    assert "verified 3 entries (complete)" in verify_zip(io.BytesIO(payload))
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        lines = archive.read("audit.jsonl").decode().splitlines()
    assert (manifest["kind"], manifest["archive_id"]) == ("archive", str(first.id))
    assert all(json.loads(line)["personal"] == {} for line in lines)
    assert "10.9.8.7" not in payload.decode("latin-1")

    # Hidden from every app query, personal rows gone; the live chain still verifies.
    cutoff = archives[-1].range_to
    assert await _visible(world, org, AuditEntry, cutoff) == 0
    assert await _visible(world, org, AuditPersonal, cutoff) == 0
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        assert await session.scalar(select(AuditCutoff.hidden_before)) == cutoff
        assert await archived_through(session) == second.last_seq
        result = await verify(session, kind="weekly", trusted_keys=TRUSTED)
        assert result.status == "passed", result.finding
        archived = await session.scalar(
            select(func.count())
            .select_from(AuditEntry)
            .where(AuditEntry.action == "audit.entries_archived")
        )
        assert archived == len(archives)

    # The month's partition goes once no tenant has visible rows in it.
    async with world.app.state.db.platform_session() as session:
        assert await drop_expired_partitions(session) >= 1
        name = f"audit_entries_p{month_start(FIVE_YEARS):%Y%m}"
        assert await session.scalar(text(f"SELECT to_regclass('public.{name}')")) is None

    # Running again finds nothing new to archive.
    assert await _archive_all(world, org, storage) == []


async def test_archiving_fails_visibly_and_hides_nothing(world: World) -> None:
    org = world.b
    await _old_entries(world, org, (OLD, 2))
    (failed,) = await _archive_all(world, org, None)

    assert (failed.status, failed.problem) == ("failed", "storage_not_configured")
    assert await _visible(world, org, AuditEntry, failed.range_to) == 2
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        assert await session.scalar(select(AuditCutoff.hidden_before)) is None
        status = await integrity_status(
            session, anchoring_configured=True, unsealed_limit=timedelta(minutes=5)
        )
        assert status.alert == "archive_failed"
        logged = await session.scalar(
            select(AuditEntry.reason_code).where(AuditEntry.action == "audit.archive_failed")
        )
        assert logged == "storage_not_configured"


async def test_restore_for_investigation_verifies_and_expires(
    world: World, storage: S3Storage
) -> None:
    org = world.a
    await _old_entries(world, org, (OLD, 3))
    first = (await _archive_all(world, org, storage))[0]

    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await request_restore(session, first.id, storage_ready=True)
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        restored = await restore(session, first.id, storage)
        assert restored is not None
        assert restored.restore_status == "ready"
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        _, rows = await restored_entries(session, first.id, after_seq=0, limit=50)
        assert [r.entry["details"]["n"] for r in rows] == [0, 1, 2]
        assert [r.seq for r in rows] == list(range(first.first_seq or 0, (first.last_seq or 0) + 1))
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        assert await expire_restored(session, FrozenClock(NOW + timedelta(days=8))) == 1
        assert await session.scalar(select(func.count()).select_from(AuditRestored)) == 0


def _tampered(payload: bytes) -> bytes:
    """The same zip with one detail of one entry changed (the manifest left as it was)."""
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(payload)) as source,
        zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as target,
    ):
        for name in source.namelist():
            data = source.read(name)
            if name == "audit.jsonl":
                data = data.replace(b'"n": 1', b'"n": 7')
                assert b'"n": 7' in data
            target.writestr(name, data)
    return out.getvalue()


async def test_a_changed_archive_is_refused_on_restore(world: World, storage: S3Storage) -> None:
    org = world.a
    await _old_entries(world, org, (OLD, 2))
    first = (await _archive_all(world, org, storage))[0]
    payload = await storage.get(first.object_key or "")
    assert payload is not None
    await storage.put(first.object_key or "", _tampered(payload), "application/zip")

    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await request_restore(session, first.id, storage_ready=True)
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        restored = await restore(session, first.id, storage)
        assert restored is not None
        assert (restored.restore_status, restored.restore_problem) == (
            "failed",
            "audit_archive_unverified",
        )
        assert await session.scalar(select(func.count()).select_from(AuditRestored)) == 0


async def test_the_cutoff_needs_an_archive_and_a_year(world: World) -> None:
    org = world.b
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        with pytest.raises(DBAPIError, match="not archived"):
            await session.execute(
                text("SELECT audit_advance_cutoff(:t)"), {"t": NOW - timedelta(days=800)}
            )
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        with pytest.raises(DBAPIError, match="at least one year"):
            await session.execute(
                text("SELECT audit_advance_cutoff(:t)"), {"t": NOW - timedelta(days=30)}
            )
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text("INSERT INTO audit_cutoffs VALUES (:t, now(), now())"), {"t": org.tenant}
            )


async def test_archive_tables_are_isolated_by_rls(world: World, storage: S3Storage) -> None:
    a, b = world.a, world.b
    await _old_entries(world, a, (OLD, 1))
    first = (await _archive_all(world, a, storage))[0]
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await request_restore(session, first.id, storage_ready=True)
    async with world.app.state.db.tenant_session(TenantContext(a.tenant)) as session:
        await restore(session, first.id, storage)

    async with world.app.state.db.tenant_session(TenantContext(b.tenant)) as session:
        for table in ("audit_archives", "audit_cutoffs", "audit_restored"):
            rows = (await session.execute(text(f"SELECT tenant_id FROM {table}"))).all()  # noqa: S608 - fixed names
            assert a.tenant not in {r[0] for r in rows}, table
        # Writing a row for tenant A from tenant B's transaction is refused by the policy.
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO audit_archives (id, tenant_id, range_from, range_to, status,"
                    " created_at) VALUES (:id, :t, now() - interval '2 days',"
                    " now() - interval '1 day', 'failed', now())"
                ),
                {"id": uuid.uuid4(), "t": a.tenant},
            )


async def test_archive_api_lists_restores_and_reads_back(world: World, storage: S3Storage) -> None:
    org = world.a
    await _old_entries(world, org, (OLD, 2))
    first = (await _archive_all(world, org, storage))[0]
    reader = await auditor(world, org)

    listed = await world.call("GET", "/audit/archives", org, reader)
    assert listed.status_code == 200, listed.text
    assert str(first.id) in {a["id"] for a in listed.json()}
    early = await world.call("GET", f"/audit/archives/{first.id}/entries", org, reader)
    assert early.status_code == 409
    assert early.json()["code"] == "audit_archive_not_restored"

    asked = await world.call("POST", f"/audit/archives/{first.id}/restore", org, reader)
    assert asked.status_code == 202, asked.text
    assert asked.json()["restore_status"] == "running"
    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        await restore(session, first.id, storage)

    page = await world.call("GET", f"/audit/archives/{first.id}/entries?limit=1", org, reader)
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["has_more"] is True
    assert body["items"][0]["action"] == "audit.settings_changed"
    assert body["items"][0]["seq"] == first.first_seq
    rest = await world.call(
        "GET", f"/audit/archives/{first.id}/entries?cursor={body['next_cursor']}", org, reader
    )
    assert [i["seq"] for i in rest.json()["items"]] == [first.last_seq]

    async with world.app.state.db.tenant_session(TenantContext(org.tenant)) as session:
        requested = await session.scalar(
            select(func.count())
            .select_from(AuditEntry)
            .where(
                AuditEntry.action == "audit.archive_restore_requested",
                AuditEntry.actor_id == reader,
            )
        )
        assert requested == 1
