"""Background work of the audit module: the sealing consumer and the periodic jobs (ADR-027).

* `audit__seal` (consumer of `audit.entry.recorded`): seals the tenant's queue at once.
* `audit__seal_sweep` (every tick): seals anything left behind and raises an alert for entries
  unsealed longer than the limit (5 minutes by default, D-075).
* `audit__anchor` (every tick): signs each tenant's newest position at most once per interval.
* `audit__verify` (every tick): a daily run for the previous day and a weekly full run per
  tenant, when they are due (file 11 Appendix A).
* `audit__partitions` (every tick, cheap when nothing is missing): monthly partitions 24 months
  ahead.

The schedules visit every tenant through `audit_tenant_ids()` (migration 0013).
"""

import uuid
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit.domain.catalogue import AuditActorType, AuditOutcome
from app.modules.audit.events import AuditAlertRaised
from app.modules.audit.infra.models import AuditEntry, AuditVerificationRun
from app.modules.audit.infra.signing import AnchorSigner, LocalSigner, trusted_keys
from app.modules.audit.service.exports import build_export, expire_exports
from app.modules.audit.service.integrity import anchor, seal, unsealed_overdue, verify
from app.modules.audit.service.recording import WORKER, record
from app.shared.clock import system_clock
from app.shared.events import EventEnvelope, record_event
from app.shared.storage import ObjectStorage, StorageNotConfigured, storage_from

log = get_logger(__name__)
PARTITION_MONTHS_AHEAD = 24
DAILY_EVERY = timedelta(days=1)
WEEKLY_EVERY = timedelta(days=7)
OVERDUE_ALERT_EVERY = timedelta(hours=1)


@lru_cache(maxsize=4)
def _signer(value: str) -> LocalSigner:
    return LocalSigner.from_config(value)


def signer_from(settings: Settings) -> AnchorSigner | None:
    """The installation's anchor signer, or None when no key is configured."""
    if settings.audit_signing_key is None:
        return None
    return _signer(settings.audit_signing_key.get_secret_value())


def trusted_from(settings: Settings) -> dict[str, bytes]:
    """Public keys a verification accepts: the active key and every retired one."""
    return trusted_keys(settings.audit_trusted_keys, signer_from(settings))


def storage_or_none(settings: Settings) -> ObjectStorage | None:
    """The configured object store, or None (exports then fail visibly)."""
    try:
        return storage_from(settings)
    except StorageNotConfigured:
        return None


async def tenant_ids(database: Database) -> list[uuid.UUID]:
    """Every tenant (the schedules visit each one in its own transaction)."""
    async with database.platform_session() as session:
        return list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())


async def on_entry_recorded(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: seal the tenant's queue right away (the event is only a wake-up)."""
    del envelope
    assert session is not None  # noqa: S101 - transactional consumer
    await seal(session, 500)


async def on_verification_requested(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: run an on-demand verification requested through the API."""
    assert session is not None  # noqa: S101 - transactional consumer
    from app.core.config import get_settings  # noqa: PLC0415 - the worker's own settings

    settings = get_settings()
    await verify(
        session,
        kind="on_demand",
        trusted_keys=trusted_from(settings),
        run_id=uuid.UUID(str(envelope.payload["run_id"])),
        unsealed_limit=timedelta(seconds=settings.audit_unsealed_alert_seconds),
    )


async def on_export_requested(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: build an export requested through the API."""
    assert session is not None  # noqa: S101 - transactional consumer
    from app.core.config import get_settings  # noqa: PLC0415 - the worker's own settings

    settings = get_settings()
    await build_export(
        session,
        uuid.UUID(str(envelope.payload["export_id"])),
        storage=storage_or_none(settings),
        signer=signer_from(settings),
        trusted_keys=trusted_from(settings),
    )


async def expire_all_exports(database: Database, settings: Settings) -> None:
    """Delete export files older than 7 days, every tenant."""
    storage = storage_or_none(settings)
    for tenant in await tenant_ids(database):
        async with database.tenant_session(TenantContext(tenant)) as session:
            await expire_exports(session, storage)


async def seal_sweep(database: Database, settings: Settings) -> None:
    """Seal leftovers; alert once an hour per tenant while entries stay unsealed too long."""
    limit = timedelta(seconds=settings.audit_unsealed_alert_seconds)
    for tenant in await tenant_ids(database):
        async with database.tenant_session(TenantContext(tenant)) as session:
            await seal(session, settings.audit_seal_batch_size)
            overdue = await unsealed_overdue(session, limit, system_clock)
            if overdue and not await _alerted_recently(session):
                entry_id = await record(
                    session,
                    action_code="audit.verification_failed",
                    facts=WORKER,
                    outcome=AuditOutcome.DONE,
                    reason_code="unsealed_overdue",
                    details={"unsealed_overdue": overdue},
                    actor=(AuditActorType.SYSTEM, None),
                )
                await record_event(
                    session,
                    AuditAlertRaised(alert="unsealed_overdue", entry_id=entry_id),
                    aggregate_id=entry_id,
                )
                log.error("audit_unsealed_overdue", tenant_id=str(tenant), entries=overdue)


async def _alerted_recently(session: AsyncSession) -> bool:
    since = system_clock.now() - OVERDUE_ALERT_EVERY
    found = await session.scalar(
        select(AuditEntry.id)
        .where(
            AuditEntry.action == "audit.verification_failed",
            AuditEntry.reason_code == "unsealed_overdue",
            AuditEntry.occurred_at >= since,
        )
        .limit(1)
    )
    return found is not None


async def anchor_all(database: Database, settings: Settings) -> None:
    """Sign each tenant's newest chain position (at most once per interval)."""
    signer = signer_from(settings)
    if signer is None:
        log.warning("audit_anchoring_off", reason="no SUPPORTX_AUDIT_SIGNING_KEY")
        return
    every = timedelta(seconds=settings.audit_anchor_interval_seconds)
    for tenant in await tenant_ids(database):
        async with database.tenant_session(TenantContext(tenant)) as session:
            await anchor(session, signer, every=every)


async def _due(session: AsyncSession, kind: str, every: timedelta) -> bool:
    last = await session.scalar(
        select(AuditVerificationRun.started_at)
        .where(AuditVerificationRun.kind == kind)
        .order_by(AuditVerificationRun.started_at.desc())
        .limit(1)
    )
    return last is None or system_clock.now() - last >= every


async def verify_due(database: Database, settings: Settings) -> None:
    """Daily (previous day) and weekly (full chain) verification per tenant, when due."""
    trusted = trusted_from(settings)
    limit = timedelta(seconds=settings.audit_unsealed_alert_seconds)
    today = datetime.combine(system_clock.now().date(), time(0), tzinfo=UTC)
    for tenant in await tenant_ids(database):
        async with database.tenant_session(TenantContext(tenant)) as session:
            if await _due(session, "daily", DAILY_EVERY):
                await verify(
                    session,
                    kind="daily",
                    trusted_keys=trusted,
                    range_from=today - DAILY_EVERY,
                    range_to=today,
                    unsealed_limit=limit,
                )
        async with database.tenant_session(TenantContext(tenant)) as session:
            if await _due(session, "weekly", WEEKLY_EVERY):
                await verify(session, kind="weekly", trusted_keys=trusted, unsealed_limit=limit)


async def ensure_partitions(database: Database, settings: Settings) -> None:
    """Monthly partitions ahead of time (created by the migrator-owned function)."""
    del settings
    async with database.platform_session() as session:
        created = await session.scalar(
            text("SELECT audit_ensure_partitions(:m)"), {"m": PARTITION_MONTHS_AHEAD}
        )
    if created:
        log.info("audit_partitions_created", count=created)
