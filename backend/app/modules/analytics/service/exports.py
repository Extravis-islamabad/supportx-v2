"""Report exports: CSV, Excel and PDF, built in the background (REQ-RPT-058; D-100).

1. The API checks the definition against what the user may see, records the request and emits
   `analytics.report_export.requested` through the outbox (403 without `reports.export`, 503
   without object storage).
2. The consumers worker rebuilds the user's subject (`identity_access.subject_for`), so the
   file holds exactly the records the user may list (REQ-RPT-002), runs the report read-only as
   supportx_report with the background time limit, streams the rows into the file, uploads it
   and marks the export ready or failed with a reason (REQ-RPT-056: never silent). Every export
   is audited with the user, the report and the row count (AC3).
3. The file can be downloaded by the person who asked, signed in, until it expires (tenant
   setting, 7 days by default).

Two contents: `summary` (the report's groups, measures and totals, as on screen) and `records`
(one row per record behind the report, with the report's groupings first). XLSX holds both;
CSV holds the one asked for; PDF holds the summary with its chart and at most PDF_RECORDS rows of
records.
"""

import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.analytics.domain.definition import ReportDefinition
from app.modules.analytics.domain.measures import MeasureSpec, Unit
from app.modules.analytics.domain.tables import CellKind, ChartData, Column, PdfInput, Value
from app.modules.analytics.events import ReportExportFinished, ReportExportRequested
from app.modules.analytics.infra.models import ReportExport
from app.modules.analytics.infra.writers import CsvSink, XlsxSink
from app.modules.analytics.service.compiler import CompiledReport, compile_report
from app.modules.analytics.service.naming import Namer, field_label, measure_label
from app.modules.analytics.service.runner import resolve_provider
from app.modules.audit import WORKER, AuditActorType, record
from app.modules.identity_access import Subject
from app.shared.events import record_event
from app.shared.ids import new_id
from app.shared.labels import label
from app.shared.reporting import DimensionKind, ReportingSource
from app.shared.storage import ObjectStorage, StorageNotConfigured, StorageUnavailable

log = get_logger(__name__)
EXPORT = "reports.export"
FORMATS = ("csv", "xlsx", "pdf")
CONTENTS = ("summary", "records")
RTL_LANGUAGES = frozenset({"ar", "ur"})
PDF_RECORDS = 1000  # a PDF is for reading: larger record lists are an Excel or CSV export
BATCH = 2000
CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
# Fields of a record listed in a records export, after the report's own groupings.
RECORD_FIELDS: dict[str, tuple[str, ...]] = {
    "incident": (
        "display_id",
        "subject",
        "status",
        "priority",
        "group_id",
        "technician_id",
        "requester_id",
        "created_at",
        "resolved_at",
    ),
}

SubjectLoader = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[Subject]]
# Renders the summary (and a few records) as PDF bytes; only the worker image has one.
PdfRenderer = Callable[[PdfInput], bytes]


@dataclass(frozen=True)
class ExportRequest:
    """What the user asked for."""

    definition: ReportDefinition
    format: str
    content: str
    title: str
    language: str
    time_zone: str


async def request_export(
    session: AsyncSession,
    subject: Subject,
    request: ExportRequest,
    *,
    validate: Callable[[ReportDefinition], Awaitable[None]],
    storage_ready: bool,
) -> ReportExport:
    """Record the request and hand it to the worker."""
    if not subject.holds(EXPORT):
        raise PermissionDenied(params={"permission": EXPORT})
    if not storage_ready:
        raise StorageNotConfigured
    await validate(request.definition)
    context: TenantContext = session.info["supportx.tenant"]
    row = ReportExport(
        id=new_id(),
        tenant_id=context.tenant_id,
        requested_by=subject.user_id,
        title=request.title.strip()[:200] or "Report",
        definition=request.definition.model_dump(mode="json", by_alias=True),
        format=request.format,
        content=request.content,
        language=request.language,
        time_zone=request.time_zone,
        status="running",
    )
    session.add(row)
    await session.flush()
    await record_event(
        session,
        ReportExportRequested(export_id=row.id, requested_by=subject.user_id),
        aggregate_id=row.id,
    )
    return row


async def list_exports(
    session: AsyncSession, subject: Subject, limit: int = 20
) -> list[ReportExport]:
    """The user's own exports, newest first."""
    return list(
        await session.scalars(
            select(ReportExport)
            .where(ReportExport.requested_by == subject.user_id)
            .order_by(ReportExport.created_at.desc())
            .limit(limit)
        )
    )


async def download(session: AsyncSession, subject: Subject, export_id: uuid.UUID) -> ReportExport:
    """The user's ready export (404 not theirs, 409 not ready or expired)."""
    row = await session.scalar(
        select(ReportExport).where(
            ReportExport.id == export_id, ReportExport.requested_by == subject.user_id
        )
    )
    if row is None:
        raise NotFound(code="report_export_not_found")
    expired = row.expires_at is not None and row.expires_at < datetime.now(UTC)
    if row.status != "ready" or row.object_key is None or expired:
        status = "expired" if expired else row.status
        raise Conflict(code="report_export_not_ready", params={"status": status})
    return row


# --- building (worker) ----------------------------------------------------------------------------


def _measure_kind(spec: MeasureSpec) -> CellKind:
    return {
        Unit.SECONDS: CellKind.HOURS,
        Unit.PERCENT: CellKind.PERCENT,
    }.get(spec.unit, CellKind.NUMBER)


def _measure_header(entity: str, spec: MeasureSpec, language: str) -> str:
    name = measure_label(entity, spec.code, language)
    return label("reports.in_hours", language, name=name) if spec.unit == Unit.SECONDS else name


def _record_kind(source: ReportingSource, name: str) -> CellKind:
    dimension = source.dimensions.get(name)
    if dimension is not None and dimension.kind == DimensionKind.DATETIME:
        return CellKind.DATETIME
    if dimension is not None and dimension.kind == DimensionKind.NUMBER:
        return CellKind.NUMBER
    return CellKind.TEXT


def _number(value: Any) -> Value:  # noqa: ANN401 - a database aggregate
    if value is None:
        return None
    return round(float(value), 4) if not isinstance(value, int) else value


@dataclass
class _Job:
    """One export being built: its row, the compiled report, the source and the reader."""

    row: ReportExport
    rs: AsyncSession  # the read-only reporting transaction
    compiled: CompiledReport
    definition: ReportDefinition
    source: ReportingSource
    namer: Namer
    header: list[str]
    max_rows: int

    @property
    def language(self) -> str:
        """The reader's language."""
        return self.row.language

    async def summary(self) -> tuple[list[Column], list[list[Value]], list[Value]]:
        """The report's groups and measures as on screen, with the totals row."""
        groups = self.compiled.groups
        records = (await self.rs.execute(self.compiled.grouped)).all() if groups else []
        totals = (await self.rs.execute(self.compiled.totals)).one()
        for index, group in enumerate(groups):
            await self.namer.prepare(group.field, group.dimension, [r[index] for r in records])
        entity = self.source.entity
        columns = [Column(field_label(g.field, self.language, {})) for g in groups] + [
            Column(_measure_header(entity, m, self.language), _measure_kind(m))
            for m in self.compiled.measures
        ]
        rows: list[list[Value]] = []
        for record_ in records:
            names: list[Value] = [
                self.namer.name(g.field, g.dimension, record_[i], g.bucket)
                for i, g in enumerate(groups)
            ]
            rows.append(names + [_number(v) for v in record_[len(groups) :]])
        lead: list[Value] = (
            [label("reports.total", self.language), *([""] * (len(groups) - 1))] if groups else []
        )
        return columns, rows, lead + [_number(v) for v in totals]

    def record_names(self) -> list[str]:
        """Fields of a records export: the report's groupings first, then the entity's list."""
        grouped = [g.field for g in self.compiled.groups]
        wanted = grouped + [
            f for f in RECORD_FIELDS.get(self.source.entity, ()) if f not in grouped
        ]
        return [n for n in wanted if self.source.fields.get(n) is not None]

    def record_columns(self) -> list[Column]:
        """Their headers and kinds."""
        return [
            Column(field_label(n, self.language, {}), _record_kind(self.source, n))
            for n in self.record_names()
        ]

    async def records(self, limit: int) -> AsyncIterator[list[Value]]:
        """One row per record behind the report, in grouping order, at most `limit`."""
        names = self.record_names()
        fields = self.source.fields.fields
        statement = (
            self.source.rows.where(self.compiled.where)
            .with_only_columns(*[fields[n].column for n in names], maintain_column_froms=True)
            .order_by(*[fields[n].column for n in names[: len(self.compiled.groups)]])
            .limit(limit)
            .execution_options(yield_per=BATCH)
        )
        result = await self.rs.stream(statement)
        async for batch in result.partitions(BATCH):
            for index, name in enumerate(names):
                dimension = self.source.dimensions.get(name)
                if dimension is not None:
                    await self.namer.prepare(name, dimension, [r[index] for r in batch])
            for record_ in batch:
                yield [self._cell(name, record_[i]) for i, name in enumerate(names)]

    def _cell(self, name: str, value: object) -> Value:
        dimension = self.source.dimensions.get(name)
        if isinstance(value, datetime):
            # Spreadsheets have no zones: the wall-clock time of the export's zone.
            return value.astimezone(self.namer.zone).replace(tzinfo=None)
        if dimension is None or dimension.kind == DimensionKind.DATETIME:
            return value if isinstance(value, str | int | float) or value is None else str(value)
        return self.namer.name(name, dimension, value, None)

    async def csv(self, out: IO[bytes]) -> int:
        """The summary or the records as CSV."""
        if self.row.content == "summary":
            columns, rows, totals = await self.summary()
            sink = CsvSink(out, columns, self.header)
            for values in rows:
                sink.row(values)
            sink.row(totals)
            sink.close()
            return len(rows)
        sink = CsvSink(out, self.record_columns(), self.header)
        count = 0
        async for values in self.records(self.max_rows):
            sink.row(values)
            count += 1
        sink.close()
        return count

    async def xlsx(self, out: IO[bytes]) -> int:
        """The summary sheet, and the records sheet when asked for; right to left in ar/ur."""
        sink = XlsxSink(rtl=self.language in RTL_LANGUAGES)
        columns, rows, totals = await self.summary()
        sink.sheet(label("reports.sheet_summary", self.language), columns, self.header)
        for values in rows:
            sink.row(values)
        sink.row(totals, bold=True)
        count = len(rows)
        if self.row.content == "records":
            sink.sheet(
                label("reports.sheet_records", self.language), self.record_columns(), self.header
            )
            count = 0
            async for values in self.records(self.max_rows):
                sink.row(values)
                count += 1
        sink.save(out)
        return count

    async def pdf(self, out: IO[bytes], render: PdfRenderer) -> int:
        """The summary with its chart, and the first PDF_RECORDS records when asked for."""
        columns, rows, totals = await self.summary()
        records = (
            [values async for values in self.records(PDF_RECORDS + 1)]
            if self.row.content == "records"
            else []
        )
        chart = None
        width = len(self.compiled.groups)
        if width and self.definition.chart.value not in {"table", "kpi"}:
            chart = ChartData(
                kind=self.definition.chart.value,
                categories=[str(r[0]) for r in rows],
                values=[
                    v if isinstance(v, int | float) else None for v in (r[width] for r in rows)
                ],
                series_name=columns[width].header,
            )
        out.write(
            render(
                PdfInput(
                    title=self.row.title,
                    language=self.language,
                    rtl=self.language in RTL_LANGUAGES,
                    header_lines=self.header,
                    columns=columns,
                    rows=rows,
                    totals=totals,
                    chart=chart,
                    records_columns=self.record_columns() if records else [],
                    records=records[:PDF_RECORDS],
                    records_cut=len(records) > PDF_RECORDS,
                )
            )
        )
        return len(records) if self.row.content == "records" else len(rows)


def _header_lines(row: ReportExport, ran_at: datetime, zone: ZoneInfo) -> list[str]:
    language = row.language
    return [
        row.title,
        label(
            "reports.export_run_at",
            language,
            time=ran_at.astimezone(zone).strftime("%Y-%m-%d %H:%M"),
        ),
        label("reports.times_in", language, zone=zone.key),
        label("reports.scope_note", language),
    ]


@dataclass(frozen=True)
class Worker:
    """What the worker gives every build."""

    reporting: Database
    storage: ObjectStorage | None
    load_subject: SubjectLoader
    render_pdf: PdfRenderer | None
    timeout_seconds: float
    max_rows: int
    link_days: int
    week_start: str = "monday"


async def _job(session: AsyncSession, row: ReportExport, worker: Worker) -> "_Job | str":
    """The job for `row`, or the problem code that stops it before any query runs."""
    if worker.storage is None:
        return "storage_not_configured"
    if row.format == "pdf" and worker.render_pdf is None:
        return "pdf_not_available"
    subject = await worker.load_subject(session, row.tenant_id, row.requested_by)
    definition = ReportDefinition.model_validate(row.definition)
    try:
        provider = resolve_provider(definition.entity, subject)
    except (NotFound, PermissionDenied):
        return "report_not_allowed"
    source = await provider.source(session, subject)
    zone = ZoneInfo(row.time_zone)
    now = datetime.now(zone)
    compiled = compile_report(
        definition, source, now=now, zone=zone.key, week_start=worker.week_start
    )
    namer = Namer(session, source.entity, row.language, zone)
    header = _header_lines(row, now, zone)
    # The reporting transaction is opened by build_export; rs is set there.
    return _Job(row, session, compiled, definition, source, namer, header, worker.max_rows)


async def build_export(
    session: AsyncSession, export_id: uuid.UUID, worker: Worker
) -> ReportExport | None:
    """Build, upload and mark the export ready, or failed with a reason (never silent)."""
    row = await session.get(ReportExport, export_id, with_for_update=True)
    if row is None or row.status != "running":
        return row
    job = await _job(session, row, worker)
    if isinstance(job, str):
        return await _finish(session, row, job)
    assert worker.storage is not None  # noqa: S101 - _job checked it
    key = f"reports/exports/{row.tenant_id}/{row.id}.{row.format}"
    handle, name = tempfile.mkstemp(prefix="sx-report-", suffix=f".{row.format}")
    path = Path(name)
    try:
        context = TenantContext(row.tenant_id, row.requested_by)
        async with worker.reporting.reporting_session(
            context, timeout_seconds=worker.timeout_seconds
        ) as rs:
            job.rs = rs
            with open(handle, "wb") as out:  # noqa: PTH123, ASYNC230 - local temp file from mkstemp
                if row.format == "csv":
                    count = await job.csv(out)
                elif row.format == "xlsx":
                    count = await job.xlsx(out)
                else:
                    assert worker.render_pdf is not None  # noqa: S101 - _job checked it
                    count = await job.pdf(out, worker.render_pdf)
        await worker.storage.put_stream(key, _chunks(path), CONTENT_TYPES[row.format])
        size = path.stat().st_size  # noqa: ASYNC240 - a local temp file in the worker
    except DBAPIError as error:
        log.warning("report_export_query_failed", export_id=str(row.id))
        cancelled = getattr(error.orig, "sqlstate", None) == "57014"
        return await _finish(session, row, "report_timeout" if cancelled else "report_failed")
    except StorageUnavailable:
        log.exception("report_export_storage_failed", export_id=str(row.id))
        return await _finish(session, row, "storage_unavailable")
    finally:
        path.unlink(missing_ok=True)  # noqa: ASYNC240 - a local temp file in the worker
    row.status = "ready"
    row.object_key = key
    row.size_bytes = size
    row.row_count = count
    row.finished_at = datetime.now(UTC)
    row.expires_at = row.finished_at + timedelta(days=worker.link_days)
    await record(
        session,
        action_code="report.exported",
        facts=WORKER,
        actor=(AuditActorType.PERSON, row.requested_by),
        object_type="report_export",
        object_id=row.id,
        details={"format": row.format, "content": row.content, "rows": count, "title": row.title},
    )
    return await _finish(session, row, None)


async def _chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            yield chunk


async def _finish(session: AsyncSession, row: ReportExport, problem: str | None) -> ReportExport:
    """Mark the export failed (problem given) and tell the person who asked, live."""
    if problem is not None:
        row.status = "failed"
        row.problem = problem
        row.finished_at = datetime.now(UTC)
    await session.flush()
    await record_event(
        session,
        ReportExportFinished(
            export_id=row.id, requested_by=row.requested_by, status=row.status, problem=row.problem
        ),
        aggregate_id=row.id,
    )
    return row


async def expire_exports(session: AsyncSession, storage: ObjectStorage | None) -> int:
    """Remove files past their expiry; the row stays as `expired`."""
    rows = list(
        await session.scalars(
            select(ReportExport).where(
                ReportExport.status == "ready", ReportExport.expires_at < datetime.now(UTC)
            )
        )
    )
    for row in rows:
        if storage is not None and row.object_key:
            await storage.delete(row.object_key)
        row.status = "expired"
        row.object_key = None
    await session.flush()
    return len(rows)
