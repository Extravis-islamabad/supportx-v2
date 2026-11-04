"""Connector runs, health and the failing/recovered notices (WP-040; REQ-INT-004, REQ-INT-005).

Every connector run, of any kind, is recorded here in the run's own transaction: its counts,
an error row when it failed, and the instance's health. A change of standing emits
`ConnectorFailing` or `ConnectorRecovered` through the outbox in that same transaction
(CLAUDE.md rule b), so admins are told once per failure and once on recovery.

The catalogue reads health and the last 24 hours' counts from here; a daily job drops runs and
errors past their retention.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, Integer, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.tenancy import TenantContext
from app.modules.integrations.domain.connector_health import (
    RUN_RETENTION_DAYS,
    Health,
    Notice,
    RunCounts,
    after_run,
)
from app.modules.integrations.events import ConnectorFailing, ConnectorRecovered
from app.modules.integrations.infra.models import ConnectorError, ConnectorHealth, ConnectorRun
from app.modules.integrations.service.connector_settings import get_connector_settings
from app.shared.events import record_event
from app.shared.ids import new_id


async def record_run(  # noqa: PLR0913 - one run's facts, explicit
    session: AsyncSession,
    kind: str,
    instance_id: uuid.UUID,
    *,
    started_at: datetime,
    counts: RunCounts,
    error_code: str | None = None,
    auth_failure: bool = False,
) -> Notice | None:
    """Record one run (failed when `error_code` is given); the notice it sent, if any."""
    now = datetime.now(UTC)
    ok = error_code is None
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    session.add(
        ConnectorRun(
            tenant_id=tenant,
            id=new_id(),
            kind=kind,
            instance_id=instance_id,
            started_at=started_at,
            finished_at=now,
            ok=ok,
            read=counts.read,
            created=counts.created,
            updated=counts.updated,
            skipped=counts.skipped,
            failed=counts.failed,
            error_code=error_code,
        )
    )
    if error_code is not None:
        session.add(
            ConnectorError(
                tenant_id=tenant,
                id=new_id(),
                kind=kind,
                instance_id=instance_id,
                occurred_at=now,
                code=error_code,
            )
        )
    row = await session.get(ConnectorHealth, _key(session, kind, instance_id), with_for_update=True)
    if row is None:
        row = ConnectorHealth(tenant_id=tenant, kind=kind, instance_id=instance_id, updated_at=now)
        row.failing, row.consecutive_failures = False, 0
        session.add(row)
    health, notice = after_run(
        Health(row.failing, row.consecutive_failures),
        ok=ok,
        auth_failure=auth_failure,
        failing_after=(await get_connector_settings(session)).failing_after_runs,  # D-041
    )
    row.failing, row.consecutive_failures, row.updated_at = (
        health.failing,
        health.consecutive_failures,
        now,
    )
    if ok:
        row.last_success_at, row.failing_since = now, None
    else:
        row.last_error_at, row.last_error_code = now, error_code
        if health.failing and row.failing_since is None:
            row.failing_since = now
    if notice is Notice.FAILING:
        await record_event(
            session,
            ConnectorFailing(kind=kind, instance_id=instance_id, reason=error_code or ""),
            aggregate_id=instance_id,
        )
    elif notice is Notice.RECOVERED:
        await record_event(
            session,
            ConnectorRecovered(kind=kind, instance_id=instance_id),
            aggregate_id=instance_id,
        )
    await session.flush()
    return notice


def _key(
    session: AsyncSession, kind: str, instance_id: uuid.UUID
) -> tuple[uuid.UUID, str, uuid.UUID]:
    return (session.info[SESSION_TENANT_KEY].tenant_id, kind, instance_id)


@dataclass(frozen=True)
class InstanceHealth:
    """What the catalogue shows besides the owner's own status (REQ-INT-004 AC1)."""

    failing: bool = False
    failing_since: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_code: str | None = None
    counts_24h: dict[str, int] = field(default_factory=dict)


_COUNTED = ("read", "created", "updated", "skipped", "failed")


async def health_of(
    session: AsyncSession, kind: str, instance_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, InstanceHealth]:
    """Health and the last 24 hours' counts of these instances (two queries in all)."""
    ids = list(instance_ids)
    if not ids:
        return {}
    rows = {
        r.instance_id: r
        for r in await session.scalars(
            select(ConnectorHealth).where(
                ConnectorHealth.kind == kind, ConnectorHealth.instance_id.in_(ids)
            )
        )
    }
    since = datetime.now(UTC) - timedelta(hours=24)
    columns = [func.coalesce(func.sum(getattr(ConnectorRun, c)), 0) for c in _COUNTED]
    failed_runs = func.count().filter(ConnectorRun.ok.is_(False)).cast(Integer)
    totals = {
        r[0]: r[1:]
        for r in await session.execute(
            select(ConnectorRun.instance_id, func.count(), failed_runs, *columns)
            .where(
                ConnectorRun.kind == kind,
                ConnectorRun.instance_id.in_(ids),
                ConnectorRun.finished_at >= since,
            )
            .group_by(ConnectorRun.instance_id)
        )
    }
    result: dict[uuid.UUID, InstanceHealth] = {}
    for instance_id in ids:
        row = rows.get(instance_id)
        sums = totals.get(instance_id)
        counts = (
            dict(zip(("runs", "failed_runs", *_COUNTED), (int(v) for v in sums), strict=True))
            if sums is not None
            else {}
        )
        result[instance_id] = (
            InstanceHealth(
                failing=row.failing,
                failing_since=row.failing_since,
                last_success_at=row.last_success_at,
                last_error_at=row.last_error_at,
                last_error_code=row.last_error_code,
                counts_24h=counts,
            )
            if row is not None
            else InstanceHealth(counts_24h=counts)
        )
    return result


async def purge(session: AsyncSession, now: datetime | None = None) -> tuple[int, int]:
    """Drop runs and errors past their retention in the session's tenant: (runs, errors)."""
    moment = now or datetime.now(UTC)
    keep_errors = (await get_connector_settings(session)).error_retention_days  # D-041
    runs = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(ConnectorRun).where(
                ConnectorRun.finished_at < moment - timedelta(days=RUN_RETENTION_DAYS)
            )
        ),
    )
    errors = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(ConnectorError).where(
                ConnectorError.occurred_at < moment - timedelta(days=keep_errors)
            )
        ),
    )
    return runs.rowcount, errors.rowcount


async def purge_schedule(database: Database, settings: Settings) -> None:
    """Daily, in every tenant: connector runs and errors past their retention."""
    del settings
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            await purge(session)
