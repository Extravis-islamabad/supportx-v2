"""The audit module's periodic jobs and the schedule runner (WP-018; REQ-AUD-010).

Real PostgreSQL; each test makes its own tenants in the session's throwaway database.
"""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.audit.domain.catalogue import AuditActorType
from app.modules.audit.infra.models import AuditAnchor, AuditVerificationRun
from app.modules.audit.infra.signing import new_key_config
from app.modules.audit.service.jobs import (
    anchor_all,
    ensure_partitions,
    seal_sweep,
    signer_from,
    verify_due,
)
from app.modules.audit.service.queries import integrity_status
from app.modules.audit.service.recording import WORKER, record
from app.shared.schedules import ScheduleRegistrationError, ScheduleSpec
from conftest import create_tenant, make_settings
from tooling.db_testing import ThrowawayDatabase
from workers.consumers.schedules import run_once, schedules_from_modules

pytestmark = pytest.mark.db


async def _entry(database: Database, tenant: uuid.UUID) -> None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        await record(
            session,
            action_code="audit.settings_changed",
            facts=WORKER,
            actor=(AuditActorType.SYSTEM, None),
        )


async def _count(database: Database, tenant: uuid.UUID, model: type) -> int:
    async with database.tenant_session(TenantContext(tenant)) as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_jobs_seal_anchor_and_verify_each_tenant_once_when_due(
    migrated_db: ThrowawayDatabase, app_db: Database
) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "Jobs")
    settings = make_settings(
        database_url=migrated_db.app_url,
        audit_signing_key=new_key_config("jobs-key"),
        audit_anchor_interval_seconds=60,
    )
    await _entry(app_db, tenant)
    await seal_sweep(app_db, settings)
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        assert await session.scalar(text("SELECT count(*) FROM audit_queue")) == 0
    await anchor_all(app_db, settings)
    await anchor_all(app_db, settings)  # nothing new to anchor, and the interval has not passed
    assert await _count(app_db, tenant, AuditAnchor) == 1
    await verify_due(app_db, settings)
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        runs = (await session.scalars(select(AuditVerificationRun))).all()
    assert sorted(r.kind for r in runs) == ["daily", "weekly"]
    assert all(r.status == "passed" for r in runs)
    await verify_due(app_db, settings)  # not due again
    assert await _count(app_db, tenant, AuditVerificationRun) == 2


async def test_anchoring_without_a_key_is_off_not_silent(
    migrated_db: ThrowawayDatabase, app_db: Database
) -> None:
    tenant = await create_tenant(migrated_db.migrator_url, "No key")
    await _entry(app_db, tenant)
    settings = make_settings(database_url=migrated_db.app_url)
    await seal_sweep(app_db, settings)
    await anchor_all(app_db, settings)
    assert await _count(app_db, tenant, AuditAnchor) == 0
    # The integrity panel says anchoring is off (never silently).
    assert signer_from(settings) is None
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        status = await integrity_status(
            session, anchoring_configured=False, unsealed_limit=timedelta(minutes=5)
        )
    assert (status.anchoring_configured, status.last_anchor_at) == (False, None)


async def test_partitions_are_created_ahead_and_only_once(app_db: Database) -> None:
    settings = make_settings()
    await ensure_partitions(app_db, settings)
    async with app_db.platform_session() as session:
        assert await session.scalar(text("SELECT audit_ensure_partitions(24)")) == 0
        months = await session.scalar(
            text("SELECT count(*) FROM pg_inherits WHERE inhparent = 'audit_entries'::regclass")
        )
    assert months >= 26  # last month, this month, 24 ahead (+ the default partition)


async def test_a_schedule_runs_on_one_worker_at_a_time(app_db: Database) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def slow(database: Database, settings: object) -> None:
        nonlocal calls
        del database, settings
        calls += 1
        started.set()
        await release.wait()

    spec = ScheduleSpec("audit__test_lock", 60, slow)
    first = asyncio.create_task(run_once(spec, app_db, make_settings()))
    await started.wait()
    assert await run_once(spec, app_db, make_settings()) is False  # the other "replica" skips
    release.set()
    assert await first is True
    assert calls == 1


def test_schedule_declarations_are_checked() -> None:
    with pytest.raises(ScheduleRegistrationError):
        ScheduleSpec("no-prefix", 60, lambda *_: asyncio.sleep(0))
    from app.core.modules import ModuleSpec  # noqa: PLC0415

    async def handler(database: Database, settings: object) -> None:
        del database, settings

    wrong = ModuleSpec(name="audit", schedules=[ScheduleSpec("other__job", 1, handler)])
    with pytest.raises(ScheduleRegistrationError):
        schedules_from_modules([wrong])


async def test_sealing_takes_the_batch_from_the_queue_without_jit(app_db: Database) -> None:
    """Migration 0016: the 10M run sealed at 875/s because each batch read the tenant's whole log
    and was JIT-compiled on every call (about 2 s for 98 partitions). Keep both fixes in place."""
    async with app_db.platform_session() as session:
        config, source = (
            await session.execute(
                text("SELECT proconfig, prosrc FROM pg_proc WHERE proname = 'audit_seal'")
            )
        ).one()
    assert "jit=off" in config
    assert "WITH batch AS MATERIALIZED" in source
    assert "CROSS JOIN LATERAL" in source
