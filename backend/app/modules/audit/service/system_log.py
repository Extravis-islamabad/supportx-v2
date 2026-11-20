"""The system log (WP-057 S5b, REQ-AUD-016): what the platform did on its own, and what failed.

The public way in for every module (exported by `app.modules.audit`):

* `record_system(session, entry)`: inside the writer's own transaction (a job that commits its
  work and its log line together);
* `record_system_alone(database, tenant_id, entry)`: in a transaction of its own, for a failure
  whose work rolled back (a mailbox check that raised). It never raises: a log line that can't
  be written is logged to the process log and the caller carries on.
* `record_system_coalesced(session, entry, window=...)`: for something that can fail many times
  a minute (every refused message): at most one entry per code and params per window, in a
  savepoint of the caller's transaction, never raising, so the caller's work goes on whatever
  happens to the log line.

Entries are a code and small params (domain/system_log.py), the object they're about, the job's
reference and the request's ID. The table is append-only by grants; `purge()` (the retention
job) is the one way rows leave, through `system_log_purge()`, which picks the cut-off itself.
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, exists, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import cast

from app.core.database import SESSION_TENANT_KEY, Database
from app.core.logging import get_logger
from app.core.request_context import current_request_id
from app.core.tenancy import TenantContext
from app.modules.audit.domain.system_log import (
    SystemLogCode,
    SystemLogEntryIn,
    SystemLogSeverity,
    check_params,
)
from app.modules.audit.events import SystemLogRecorded
from app.modules.audit.infra.models import SystemLogEntry
from app.shared.events import record_event
from app.shared.ids import new_id

log = get_logger(__name__)

PAGE = 50
PAGE_MAX = 200
EXPORT_MAX = 50_000  # rows in one CSV (the screen's filters narrow it)
_PURGE = text("SELECT system_log_purge()")


async def record_system(
    session: AsyncSession, entry: SystemLogEntryIn, *, now: datetime | None = None
) -> uuid.UUID:
    """Write one entry in the caller's transaction; open system logs refetch (rule c)."""
    context: TenantContext = session.info[SESSION_TENANT_KEY]
    row = SystemLogEntry(
        id=new_id(),
        tenant_id=context.tenant_id,
        occurred_at=now or datetime.now(UTC),
        severity=entry.severity.value,
        module=entry.module,
        code=entry.code.value,
        params=check_params(entry.params),
        object_type=entry.about.type if entry.about else None,
        object_id=entry.about.id if entry.about else None,
        job_id=entry.job_id,
        request_id=current_request_id(),
    )
    session.add(row)
    await session.flush()
    await record_event(
        session,
        SystemLogRecorded(severity=entry.severity.value),
        aggregate_id=row.id,
    )
    return row.id


async def record_system_alone(
    database: Database, tenant_id: uuid.UUID, entry: SystemLogEntryIn
) -> uuid.UUID | None:
    """Write one entry in its own transaction; never raises (the writer is already failing)."""
    try:
        async with database.tenant_session(TenantContext(tenant_id)) as session:
            return await record_system(session, entry)
    except Exception as exc:  # noqa: BLE001 - a log line must never break its writer
        log.warning(
            "system_log_write_failed",
            tenant_id=str(tenant_id),
            code=entry.code.value,
            error=type(exc).__name__,
        )
        return None


COALESCE_WINDOW = timedelta(hours=1)


async def record_system_coalesced(
    session: AsyncSession,
    entry: SystemLogEntryIn,
    *,
    window: timedelta = COALESCE_WINDOW,
    now: datetime | None = None,
) -> uuid.UUID | None:
    """Write `entry` unless the same code and params were logged within `window`; never raises."""
    at = now or datetime.now(UTC)
    params = check_params(entry.params)
    try:
        async with session.begin_nested():
            seen = await session.scalar(
                select(
                    exists().where(
                        SystemLogEntry.code == entry.code.value,
                        SystemLogEntry.occurred_at >= at - window,
                        SystemLogEntry.params.op("@>")(cast(params, JSONB)),
                        SystemLogEntry.params.op("<@")(cast(params, JSONB)),
                    )
                )
            )
            if seen:
                return None
            return await record_system(session, entry, now=at)
    except Exception as exc:  # noqa: BLE001 - a log line must never break its writer
        log.warning("system_log_write_failed", code=entry.code.value, error=type(exc).__name__)
        return None


@dataclass(frozen=True)
class SystemLogFilter:
    """The screen's filters, the export's too (AC3: the same rows)."""

    severities: Collection[SystemLogSeverity] = ()
    modules: Collection[str] = ()
    codes: Collection[SystemLogCode] = ()
    object_type: str | None = None
    object_id: uuid.UUID | None = None
    since: datetime | None = None
    until: datetime | None = None


def _filtered(where: SystemLogFilter) -> Select[SystemLogEntry]:
    statement = select(SystemLogEntry)
    if where.severities:
        statement = statement.where(
            SystemLogEntry.severity.in_([s.value for s in where.severities])
        )
    if where.modules:
        statement = statement.where(SystemLogEntry.module.in_(list(where.modules)))
    if where.codes:
        statement = statement.where(SystemLogEntry.code.in_([c.value for c in where.codes]))
    if where.object_type is not None:
        statement = statement.where(SystemLogEntry.object_type == where.object_type)
    if where.object_id is not None:
        statement = statement.where(SystemLogEntry.object_id == where.object_id)
    if where.since is not None:
        statement = statement.where(SystemLogEntry.occurred_at >= where.since)
    if where.until is not None:
        statement = statement.where(SystemLogEntry.occurred_at < where.until)
    return statement.order_by(SystemLogEntry.occurred_at.desc(), SystemLogEntry.id.desc())


async def entries(
    session: AsyncSession,
    where: SystemLogFilter,
    *,
    after: tuple[datetime, uuid.UUID] | None = None,
    limit: int = PAGE,
) -> list[SystemLogEntry]:
    """A page, newest first; `after` is the last row of the previous page (a keyset cursor)."""
    statement = _filtered(where)
    if after is not None:
        at, last = after
        statement = statement.where(
            (SystemLogEntry.occurred_at < at)
            | ((SystemLogEntry.occurred_at == at) & (SystemLogEntry.id < last))
        )
    return list(await session.scalars(statement.limit(max(1, min(limit, PAGE_MAX)))))


async def export_rows(session: AsyncSession, where: SystemLogFilter) -> Sequence[SystemLogEntry]:
    """Every row the screen would show for `where`, in the same order, up to EXPORT_MAX."""
    return list(await session.scalars(_filtered(where).limit(EXPORT_MAX)))


async def purge(session: AsyncSession) -> int:
    """Entries past the tenant's retention go; the database picks the cut-off (never under 30)."""
    return int(await session.scalar(_PURGE) or 0)
