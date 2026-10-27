"""Run a report for one viewer (WP-035, ADR-033).

1. The entity's provider must exist, its licence feature must be on (checked by the caller
   through the entitlement gate) and the viewer must hold `reports.view` and the entity's list
   permission (REQ-RPT-048).
2. The provider gives the entity as the viewer may see it; the compiler wraps it.
3. The queries run in a read-only transaction as supportx_report on the reporting pool, with the
   interactive time limit; a cancelled query becomes 422 `report_timeout` (REQ-RPT-009 AC1).
4. Each row carries the list filter behind it, so a click opens exactly those records
   (REQ-RPT-037).
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.errors import NotFound, PermissionDenied, RateLimited, ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.analytics.domain.definition import AGE_BUCKETS, DateBucket, ReportDefinition
from app.modules.analytics.domain.measures import MeasureSpec
from app.modules.analytics.service.compiler import CompiledGroup, compile_report, drill_filter
from app.modules.identity_access import Subject
from app.shared.reporting import (
    ReportingSource,
    SourceProvider,
    UnknownEntityError,
    provider_for,
)

RUN = "reports.view"
# Time to wait for a free slot before telling the user the tenant's report queue is full.
SLOT_WAIT_SECONDS = 5.0
_QUERY_CANCELED = "57014"  # PostgreSQL: canceling statement due to statement timeout


@dataclass(frozen=True)
class ResultRow:
    """One group: its keys (codes, ids, bucket starts), measure values and drill-down filter."""

    keys: tuple[Any, ...]
    values: tuple[float | int | None, ...]
    drill: Any


@dataclass(frozen=True)
class ReportResult:
    """What the viewer sees; labels are applied by the UI from the group and measure metadata."""

    entity: str
    list_path: str
    as_of: datetime
    time_zone: str
    groups: tuple[CompiledGroup, ...]
    measures: tuple[MeasureSpec, ...]
    rows: tuple[ResultRow, ...]
    totals: tuple[float | int | None, ...]
    truncated: bool
    drill_all: Any  # the list filter behind the totals


class TenantSlots:
    """Concurrent report queries per tenant in this process (REQ-RPT-009 AC3).

    The reporting pool already bounds the process; this keeps one tenant from holding all of it.
    A cross-replica limit (Valkey) comes with background report jobs.
    """

    def __init__(self, per_tenant: int) -> None:
        self._per_tenant = per_tenant
        self._slots: dict[uuid.UUID, asyncio.Semaphore] = {}

    def of(self, tenant_id: uuid.UUID) -> asyncio.Semaphore:
        """The tenant's semaphore."""
        slot = self._slots.get(tenant_id)
        if slot is None:
            slot = self._slots[tenant_id] = asyncio.Semaphore(self._per_tenant)
        return slot


def resolve_provider(entity: str, subject: Subject) -> SourceProvider:
    """The provider of `entity`, if the viewer may report on it (404 / 403 otherwise)."""
    try:
        provider = provider_for(entity)
    except UnknownEntityError:
        raise NotFound(code="report_entity_not_found") from None
    if not subject.holds(RUN) or not subject.holds(provider.permission):
        raise PermissionDenied(code="report_not_allowed")
    return provider


def _number(value: Any) -> float | int | None:  # noqa: ANN401 - a database aggregate
    if value is None:
        return None
    if isinstance(value, Decimal | float):
        return round(float(value), 4)
    return int(value)


def _key(value: Any) -> Any:  # noqa: ANN401 - a grouping value from the database
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _next_start(start: datetime, bucket: DateBucket) -> datetime:
    match bucket:
        case DateBucket.DAY:
            return start + timedelta(days=1)
        case DateBucket.WEEK:
            return start + timedelta(days=7)
        case DateBucket.AGE:  # pragma: no cover - ageing uses age_bounds()
            return start
        case DateBucket.MONTH | DateBucket.QUARTER | DateBucket.YEAR:
            months = {DateBucket.MONTH: 1, DateBucket.QUARTER: 3, DateBucket.YEAR: 12}[bucket]
            index = start.year * 12 + start.month - 1 + months
            return start.replace(year=index // 12, month=index % 12 + 1)


def age_bounds(index: int, now: datetime) -> tuple[str, str]:
    """[from, to) of creation instants for the ageing bucket `index` (oldest bucket: from 2000)."""
    _code, low, high = AGE_BUCKETS[index]
    start = now - timedelta(days=high) if high is not None else datetime(2000, 1, 1, tzinfo=UTC)
    return start.astimezone(UTC).isoformat(), (now - timedelta(days=low)).astimezone(
        UTC
    ).isoformat()


def bucket_bounds(local_start: datetime, bucket: DateBucket, zone: ZoneInfo) -> tuple[str, str]:
    """[from, to) of a bucket as UTC instants; `local_start` is the zone's wall-clock start.

    Computed on the wall clock, so a daylight-saving change gives a 23- or 25-hour day rather
    than a missing or doubled one (REQ-DSH-044 AC3).
    """
    low = local_start.replace(tzinfo=zone)
    high = _next_start(local_start, bucket).replace(tzinfo=zone)
    return low.astimezone(UTC).isoformat(), high.astimezone(UTC).isoformat()


def _rows(
    definition: ReportDefinition,
    groups: Sequence[CompiledGroup],
    records: Sequence[Any],
    zone: ZoneInfo,
    now: datetime,
) -> list[ResultRow]:
    rows: list[ResultRow] = []
    width = len(groups)
    for record in records:
        raw_keys = tuple(record[:width])
        bounds: dict[int, tuple[str, str]] = {}
        keys_out: list[Any] = []
        for i, group in enumerate(groups):
            raw = raw_keys[i]
            if group.bucket == DateBucket.AGE:
                bounds[i] = age_bounds(raw, now)
                keys_out.append(AGE_BUCKETS[raw][0])
                continue
            if group.bucket is not None and raw is not None:
                bounds[i] = bucket_bounds(raw, group.bucket, zone)
            keys_out.append(_key(raw))
        keys = tuple(keys_out)
        drill = drill_filter(definition, groups, keys, bucket_bounds=bounds)
        rows.append(ResultRow(keys, tuple(_number(v) for v in record[width:]), drill))
    return rows


async def run_report(  # noqa: PLR0913 - the run's inputs, explicit
    session: AsyncSession,
    reporting: Database,
    context: TenantContext,
    subject: Subject,
    definition: ReportDefinition,
    *,
    source: ReportingSource,
    zone: ZoneInfo,
    timeout_seconds: float,
    slots: TenantSlots,
) -> ReportResult:
    """Compile and run `definition` over `source` (the viewer's view of the entity)."""
    del session, subject  # the source already carries the viewer's scope
    now = datetime.now(zone)
    compiled = compile_report(definition, source, now=now, zone=zone.key)
    slot = slots.of(context.tenant_id)
    try:
        await asyncio.wait_for(slot.acquire(), timeout=SLOT_WAIT_SECONDS)
    except TimeoutError:
        raise RateLimited(code="report_queue_full", headers={"Retry-After": "5"}) from None
    try:
        async with reporting.reporting_session(context, timeout_seconds=timeout_seconds) as rs:
            grouped = (await rs.execute(compiled.grouped)).all() if compiled.groups else []
            totals = (await rs.execute(compiled.totals)).one()
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == _QUERY_CANCELED:
            raise ValidationFailed(
                code="report_timeout", params={"seconds": int(timeout_seconds)}
            ) from None
        raise
    finally:
        slot.release()
    truncated = definition.limit is not None and len(grouped) > definition.limit
    if truncated:
        grouped = grouped[: definition.limit]
    return ReportResult(
        entity=source.entity,
        list_path=source.list_path,
        as_of=datetime.now(UTC),
        time_zone=zone.key,
        groups=compiled.groups,
        measures=compiled.measures,
        rows=tuple(_rows(definition, compiled.groups, grouped, zone, now)),
        totals=tuple(_number(v) for v in totals),
        truncated=truncated,
        drill_all=definition.filter_json(),
    )
