"""Importing CIs and relationships from CSV or Excel (WP-053 S4b; REQ-CMDB-018).

The assets' import pattern (assets/service/imports.py, from WP-021's people import): the API
stores the file on a queued import and returns at once; the import job (a schedule in the
consumers worker) reads it with D-092's limits (app/shared/sheets.py: size, rows, columns, cells,
the zip-bomb check) and applies the rows in batches, one transaction per batch, each row in its
own savepoint. A bad row is reported (row, column, reason code) and the others are kept. Each
batch commits its progress with an event (`cmdb.import.progressed`, to the importer's own
channel), so the import screen moves live. Every import is a background job, whatever its size
(the coordinator's (5)); the upload takes an Idempotency-Key.

- **Dry run first:** every row goes through the same service calls inside a savepoint that is
  always rolled back, so nothing changes; the import ends `checked` with what would be created,
  updated or left as it is, and keeps the file. Running it queues the same file for real.
- **As the importer:** each row is the importer's own change, through the CI and relationship
  services (rights, ADR-053 reach, ADR-047 field rules, history with source `import`, outbox
  events): never a raw write.
- **What the importer may not see is not there** (lane C (6), (7)): rows match only CIs the
  importer may see. An update naming a CI they may not see reads `not_found`, as one that exists
  nowhere; a relationship row naming one is refused the same way, and nothing of the row is
  written (AC1). A name match never collides with an unseen CI (names are not unique: the row
  adds a CI of its own), and a CI row that names a display ID in "add" is `row_conflict`, seen or
  not. So no total, code or count tells an unseen CI from a missing one.
- **Re-importing the same file creates no duplicates (AC2):** "add and update" updates what it
  matches (unchanged when the values are the same), and a relationship already there is
  unchanged.
- **The source of every attribute (S4a, REQ-CMDB-016):** what a row writes is stamped `import`,
  and an update goes through the tenant's who-wins order like a sync run (the same `plan`): a
  value a stronger source set (by default, a hand edit) is kept, never overwritten. A row that
  changes nothing because of that is `kept` and counted so, never an error.
"""

import csv
import io
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import (
    AppError,
    Conflict,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.cmdb.domain import field_access as field_rules
from app.modules.cmdb.domain import merge as domain
from app.modules.cmdb.domain import relationships as rel
from app.modules.cmdb.domain import sources as source_rules
from app.modules.cmdb.domain import sync as sync_rules
from app.modules.cmdb.events import CiImportProgressed
from app.modules.cmdb.infra.models import Ci, CiImport, CiState, Relationship, RelationshipType
from app.modules.cmdb.service import cis, relationships
from app.modules.cmdb.service.catalogue import ADD, EDIT, ensure_defaults, get_settings, get_type
from app.modules.identity_access import Subject, subject_for
from app.shared import sheets
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Source
from app.shared.history.conflicts import stale_version
from app.shared.labels import has_label, plain_label

log = get_logger(__name__)

BATCH = 100  # rows per transaction at most
BATCH_SECONDS = 2.0  # and at most about this long
SOURCE: Source = "import"
CI_VALUES = ("name", "description", "business_impact", "criticality")
FORMAT_WORDS = {"max_rows": domain.MAX_IMPORT_ROWS, "max_megabytes": 25}


class ImportRepository(Repository[CiImport]):
    """CMDB imports of the session's tenant."""

    model = CiImport


class RowProblem(Exception):
    """One row cannot be applied: the column and the reason code."""

    def __init__(self, column: str, code: str) -> None:
        """`column`: the field the problem is in ("row" for the row as a whole)."""
        super().__init__(code)
        self.column = column
        self.code = code


def _needed(kind: domain.CiImportKind, mode: domain.CiImportMode) -> list[str]:
    if kind is domain.CiImportKind.RELATIONSHIPS:
        return [EDIT]
    return {
        domain.CiImportMode.ADD: [ADD],
        domain.CiImportMode.UPDATE: [EDIT],
        domain.CiImportMode.ADD_UPDATE: [ADD, EDIT],
    }[mode]


def require_import(subject: Subject, kind: domain.CiImportKind, mode: domain.CiImportMode) -> None:
    """CIs: cmdb.add to add, cmdb.edit to update (or cmdb.manage); relationships: cmdb.edit."""
    for permission in _needed(kind, mode):
        if cis.writer(subject, permission) is None:
            raise PermissionDenied(params={"permission": permission, "reason": "no_permission"})


async def start_import(  # noqa: PLR0913 - the upload's facts, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    kind: domain.CiImportKind,
    mode: domain.CiImportMode,
    match_on: domain.CiImportMatch,
    type_id: uuid.UUID | None,
    file_name: str,
    content: bytes,
    dry_run: bool = True,
) -> CiImport:
    """Queue a file (a dry run unless asked otherwise). Only its kind and size are checked here."""
    require_import(subject, kind, mode)
    await ensure_defaults(session)
    if kind is domain.CiImportKind.CIS:
        if type_id is None:
            raise ValidationFailed(code="cmdb_import_type_required")
        await get_type(session, type_id)
    try:
        file_format = sheets.file_format(file_name, content)
        if len(content) > domain.IMPORT_LIMITS.max_file_bytes:
            raise sheets.SheetRefused(sheets.FILE_TOO_LARGE)  # noqa: TRY301 - the job's refusal
    except sheets.SheetRefused as refused:
        raise ValidationFailed(code=f"cmdb_import_{refused.code}", params=FORMAT_WORDS) from None
    job = await ImportRepository(session).add(
        CiImport(
            kind=kind.value,
            mode=mode.value,
            match_on=match_on.value,
            type_id=type_id if kind is domain.CiImportKind.CIS else None,
            dry_run=dry_run,
            file_name=file_name[:255] or "import",
            file_format=file_format,
            content=content,
            status=domain.CiImportStatus.QUEUED.value,
            problems=[],
        )
    )
    await _progress(session, job)
    return job


async def own_import(session: AsyncSession, subject: Subject, import_id: uuid.UUID) -> CiImport:
    """One of the subject's own imports (anyone else's is not found)."""
    found: CiImport | None = await session.scalar(
        select(CiImport).where(
            CiImport.id == import_id,
            CiImport.created_by == subject.user_id,
            CiImport.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="cmdb_import_not_found")
    return found


async def recent_imports(
    session: AsyncSession, subject: Subject, *, limit: int = 20
) -> list[CiImport]:
    """The subject's latest imports, newest first."""
    rows = await session.scalars(
        select(CiImport)
        .where(CiImport.created_by == subject.user_id, CiImport.deleted_at.is_(None))
        .order_by(CiImport.created_at.desc(), CiImport.id.desc())
        .limit(limit)
    )
    return list(rows)


async def start_run(
    session: AsyncSession, subject: Subject, import_id: uuid.UUID, *, expected_version: int
) -> CiImport:
    """Run a checked dry run for real: the same file, mode and match (If-Match)."""
    job = await own_import(session, subject, import_id)
    require_import(subject, domain.CiImportKind(job.kind), domain.CiImportMode(job.mode))
    if job.version != expected_version:
        raise await stale_version(
            session,
            job,
            expected_version=expected_version,
            record_type="cmdb_import",
            record_id=job.id,
        )
    if job.status != domain.CiImportStatus.CHECKED or job.content is None:
        raise Conflict(code="cmdb_import_not_checked", params={"status": job.status})
    job.dry_run = False
    job.status = domain.CiImportStatus.QUEUED.value
    job.processed = job.created_count = job.updated_count = 0
    job.unchanged_count = job.kept_count = job.failed_count = 0
    job.problems = []
    job.finished_at = None
    job.version += 1
    await session.flush()
    await _progress(session, job)
    return job


def problems_csv(job: CiImport, language: str) -> str:
    """The refused rows as a CSV in the reader's language (codes in words, formula-safe).

    Codes only ever (never a value from the file), and every cell still goes through
    `safe_cell`, so no cell opens as a formula (the coordinator's (4)).
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            domain.safe_cell(plain_label(f"cmdb.import.column.{name}", language))
            for name in ("row", "field", "problem")
        ]
    )
    for problem in job.problems:
        column = f"cmdb_import_field.{problem.get('field') or 'row'}"
        code = f"errors.field.{problem.get('code')}"
        writer.writerow(
            [
                domain.safe_cell(str(problem.get("row") or "")),
                domain.safe_cell(
                    plain_label(column if has_label(column) else "cmdb_import_field.row", language)
                ),
                domain.safe_cell(
                    plain_label(code if has_label(code) else "errors.field.invalid_value", language)
                ),
            ]
        )
    return "﻿" + buffer.getvalue()


async def _progress(session: AsyncSession, job: CiImport) -> None:
    if job.created_by is None:  # pragma: no cover - imports are only started by people
        return
    await record_event(
        session,
        CiImportProgressed(
            import_id=job.id,
            requested_by=job.created_by,
            status=job.status,
            processed=job.processed,
            total=job.total,
        ),
        aggregate_id=job.id,
    )


# --- the worker -----------------------------------------------------------------------------------


async def run_cmdb_imports(database: Database, settings: Settings) -> None:
    """Schedule: every tenant's queued imports (and any a stopped run left running), in order."""
    del settings
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        await run_tenant(database, tenant)


async def run_tenant(database: Database, tenant: uuid.UUID) -> None:
    """One tenant's queued imports (the schedule, and tests)."""
    while (ref := await _next(database, tenant)) is not None:
        try:
            await _run(database, tenant, ref)
        except Exception:  # one broken import must not stop the others; it is logged
            log.exception("cmdb_import_failed", import_id=str(ref[0]))
            await _finish(database, tenant, ref, failure="cmdb_import_unexpected")


async def _next(database: Database, tenant: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        row = (
            await session.execute(
                select(CiImport.id, CiImport.created_by)
                .where(
                    CiImport.status.in_(
                        (domain.CiImportStatus.QUEUED, domain.CiImportStatus.RUNNING)
                    ),
                    CiImport.deleted_at.is_(None),
                )
                .order_by(CiImport.created_at, CiImport.id)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        if row.created_by is None:  # pragma: no cover - imports are only started by people
            found = await session.get(CiImport, row.id)
            if found is not None:
                found.status = domain.CiImportStatus.FAILED.value
                found.failure = "cmdb_import_unexpected"
            return None
    return row.id, row.created_by


async def _run(database: Database, tenant: uuid.UUID, ref: tuple[uuid.UUID, uuid.UUID]) -> None:
    import_id, importer = ref
    context = TenantContext(tenant, importer)  # the rows are the importer's own changes
    async with database.tenant_session(context) as session:
        job = await session.get(CiImport, import_id)
        if job is None or job.content is None:
            return
        try:
            sheet = domain.read_import(
                domain.CiImportKind(job.kind),
                domain.CiImportMatch(job.match_on),
                job.file_format,
                job.content,
            )
        except domain.ImportRefused as refused:
            job.status, job.failure, job.content = "failed", refused.code[:50], None
            job.failure_detail = (refused.detail or "")[:100] or None
            job.finished_at = datetime.now(UTC)
            job.version += 1
            await _progress(session, job)
            return
        rows = sheet.rows
        offset = job.processed
        if job.status != domain.CiImportStatus.RUNNING:
            job.status, job.total = domain.CiImportStatus.RUNNING.value, len(rows)
            job.version += 1
            await _progress(session, job)
    while offset < len(rows):
        async with database.tenant_session(context) as session:
            offset = await _batch(session, tenant, import_id, rows, offset)
    await _finish(database, tenant, ref)


@dataclass(slots=True)
class _Tally:
    """One transaction's outcomes, written to the import once at its end."""

    problems: list[dict[str, Any]]
    counts: dict[domain.CiRowOutcome | None, int] = field(default_factory=dict)

    def add(self, number: int, outcome: domain.CiRowOutcome | RowProblem) -> None:
        if isinstance(outcome, RowProblem):
            self.counts[None] = self.counts.get(None, 0) + 1
            if len(self.problems) < domain.MAX_IMPORT_PROBLEMS:
                self.problems.append({"row": number, "field": outcome.column, "code": outcome.code})
        else:
            self.counts[outcome] = self.counts.get(outcome, 0) + 1


@dataclass(frozen=True, slots=True)
class _How:
    """How the rows of one import are applied, and by whom."""

    subject: Subject
    kind: domain.CiImportKind
    mode: domain.CiImportMode
    match_on: domain.CiImportMatch
    type_id: uuid.UUID | None
    dry_run: bool
    precedence: source_rules.Precedence  # the tenant's who-wins order (S4a)


async def _batch(
    session: AsyncSession,
    tenant: uuid.UUID,
    import_id: uuid.UUID,
    rows: Sequence[tuple[int, dict[str, str]]],
    offset: int,
) -> int:
    """One transaction: up to BATCH rows from `offset`, or fewer once BATCH_SECONDS have passed."""
    job = await session.get(CiImport, import_id, with_for_update=True)
    if job is None or job.created_by is None:  # pragma: no cover - never hard-deleted
        return len(rows)
    how = _How(
        subject=await subject_for(session, tenant, job.created_by),
        kind=domain.CiImportKind(job.kind),
        mode=domain.CiImportMode(job.mode),
        match_on=domain.CiImportMatch(job.match_on),
        type_id=job.type_id,
        dry_run=job.dry_run,
        precedence=source_rules.precedence_of((await get_settings(session)).source_precedence),
    )
    deadline = time.monotonic() + BATCH_SECONDS
    tally = _Tally(problems=list(job.problems))
    done = 0
    for number, values in rows[offset : offset + BATCH]:
        if done and time.monotonic() >= deadline:
            break
        done += 1
        tally.add(number, await _one(session, how, values))
    job.processed += done
    job.created_count += tally.counts.get(domain.CiRowOutcome.CREATED, 0)
    job.updated_count += tally.counts.get(domain.CiRowOutcome.UPDATED, 0)
    job.unchanged_count += tally.counts.get(domain.CiRowOutcome.UNCHANGED, 0)
    job.kept_count += tally.counts.get(domain.CiRowOutcome.KEPT, 0)
    job.failed_count += tally.counts.get(None, 0)
    job.problems = tally.problems
    job.version += 1
    await _progress(session, job)
    return offset + done


async def _one(
    session: AsyncSession, how: _How, values: Mapping[str, str]
) -> domain.CiRowOutcome | RowProblem:
    """One row in its own savepoint, rolled back in a dry run or when the row is refused."""
    savepoint = await session.begin_nested()
    try:
        outcome = await (
            _ci_row(session, how, values)
            if how.kind is domain.CiImportKind.CIS
            else _relationship_row(session, how, values)
        )
    except RowProblem as problem:
        await savepoint.rollback()
        return problem
    except AppError as refused:
        await savepoint.rollback()
        return _problem(refused)
    except BaseException:
        await savepoint.rollback()
        raise
    if how.dry_run:
        await savepoint.rollback()  # a dry run changes nothing, display IDs included
    else:
        await savepoint.commit()
    return outcome


# A service's field name as the file's column (the rest keep their own name).
_COLUMNS = {"state_id": "state", "targets": "to", "type_id": "row", "custom": "row"}


def _problem(refused: AppError) -> RowProblem:
    """A service's refusal as the row's problem: the field and code it names, never a value."""
    if isinstance(refused, ValidationFailed) and refused.errors:
        first = refused.errors[0]
        name = first.field.removeprefix("body.").split(".")[0]
        return RowProblem(_COLUMNS.get(name, name) or "row", first.code)
    if isinstance(refused, PermissionDenied):
        return RowProblem(column="row", code=domain.NOT_PERMITTED)
    if isinstance(refused, NotFound):
        return RowProblem(column="row", code=domain.NOT_FOUND)
    if isinstance(refused, Conflict):
        return RowProblem(column="row", code=domain.ROW_CONFLICT)
    return RowProblem(column="row", code=domain.INVALID)


# --- a CI row -------------------------------------------------------------------------------------


async def _visible_match(session: AsyncSession, how: _How, wanted: str) -> list[Ci]:
    """The CIs the importer may see that the row names (by display ID, or by name in the type)."""
    rows = cis.visible_rows(how.subject)
    if how.match_on is domain.CiImportMatch.DISPLAY_ID:
        rows = rows.where(func.lower(Ci.display_id) == wanted.lower())
    else:
        rows = rows.where(Ci.type_id == how.type_id, func.lower(Ci.name) == wanted.lower())
    return list(await session.scalars(rows.limit(2)))


async def _ci_values(session: AsyncSession, values: Mapping[str, str]) -> dict[str, Any]:
    """The row's CI fields: empty cells leave a field alone; a state by its code."""
    found: dict[str, Any] = {k: values[k] for k in CI_VALUES if values.get(k)}
    for key in ("business_impact", "criticality"):
        if key in found:
            found[key] = found[key].strip().lower()
    if state := values.get("state"):
        state_id = await session.scalar(
            select(CiState.id).where(
                func.lower(CiState.api_name) == state.strip().lower(), CiState.deleted_at.is_(None)
            )
        )
        if state_id is None:
            raise RowProblem(column="state", code=domain.NOT_FOUND)
        found["state_id"] = state_id
    return found


async def _ci_row(
    session: AsyncSession, how: _How, values: Mapping[str, str]
) -> domain.CiRowOutcome:
    key_field = how.match_on.value
    wanted = (values.get(key_field) or "").strip()
    if how.match_on is domain.CiImportMatch.NAME and not wanted:
        raise RowProblem(column="name", code=domain.REQUIRED)
    matches = await _visible_match(session, how, wanted) if wanted else []
    if len(matches) > 1:
        raise RowProblem(key_field, domain.AMBIGUOUS)
    record = matches[0] if matches else None
    fields = await _ci_values(session, values)
    if record is None:
        if how.mode is domain.CiImportMode.UPDATE:
            raise RowProblem(key_field, domain.NOT_FOUND)  # missing or unseen: the same
        if how.match_on is domain.CiImportMatch.DISPLAY_ID and wanted:
            # A display ID is the system's to give: naming one in an add is refused, whether it
            # exists, exists out of sight or exists nowhere (lane C (6)).
            code = (
                domain.NOT_FOUND
                if how.mode is domain.CiImportMode.ADD_UPDATE
                else domain.ROW_CONFLICT
            )
            raise RowProblem(key_field, code)
        if "name" not in fields:
            raise RowProblem(column="name", code=domain.REQUIRED)
        await cis.add_imported(session, how.subject, {**fields, "type_id": how.type_id}, SOURCE)
        return domain.CiRowOutcome.CREATED
    if how.mode is domain.CiImportMode.ADD:
        raise RowProblem(key_field, domain.ROW_CONFLICT)
    # Who wins, per attribute (S4a): only what the import's source may change is written.
    found = sync_rules.plan(
        how.precedence,
        field_rules.flat(cis.snapshot(record)),
        cis.effective_stamps(record),
        {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in fields.items()},
        source=source_rules.AttributeSource.IMPORT,
    )
    if not found.changes:
        return domain.CiRowOutcome.KEPT if found.kept else domain.CiRowOutcome.UNCHANGED
    before = record.version
    updated = await cis.update(
        session,
        how.subject,
        record.id,
        expected_version=record.version,
        values={k: fields[k] for k in found.changes},
        source=SOURCE,
        stamp_as=source_rules.AttributeSource.IMPORT,
    )
    changed = updated.record.version != before
    return domain.CiRowOutcome.UPDATED if changed else domain.CiRowOutcome.UNCHANGED


# --- a relationship row ---------------------------------------------------------------------------


async def _end(session: AsyncSession, how: _How, column: str, values: Mapping[str, str]) -> Ci:
    wanted = (values.get(column) or "").strip()
    if not wanted:
        raise RowProblem(column, domain.REQUIRED)
    rows = cis.visible_rows(how.subject)
    rows = rows.where(
        func.lower(Ci.display_id) == wanted.lower()
        if how.match_on is domain.CiImportMatch.DISPLAY_ID
        else func.lower(Ci.name) == wanted.lower()
    )
    found: list[Ci] = list(await session.scalars(rows.limit(2)))
    if not found:
        raise RowProblem(column, domain.NOT_FOUND)  # missing or unseen: the same (AC1)
    if len(found) > 1:
        raise RowProblem(column, domain.AMBIGUOUS)
    return found[0]


async def _relationship_row(
    session: AsyncSession, how: _How, values: Mapping[str, str]
) -> domain.CiRowOutcome:
    start = await _end(session, how, "from", values)
    end = await _end(session, how, "to", values)
    code = (values.get("relationship") or "").strip().lower()
    if not code:
        raise RowProblem(column="relationship", code=domain.REQUIRED)
    await relationships.ensure_types(session)
    kind = await session.scalar(
        select(RelationshipType).where(
            RelationshipType.code == code, RelationshipType.deleted_at.is_(None)
        )
    )
    if kind is None:
        raise RowProblem(column="relationship", code=domain.TYPE_UNKNOWN)
    if start.id == end.id:
        raise RowProblem(column="to", code="cmdb_relationship_self")
    there = await session.scalar(
        select(Relationship.id).where(
            Relationship.type_id == kind.id,
            Relationship.from_ci_id == start.id,
            Relationship.to_ci_id == end.id,
            Relationship.deleted_at.is_(None),
        )
    )
    if there is not None:
        return domain.CiRowOutcome.UNCHANGED  # AC2: a re-import makes no second link
    await relationships.add(
        session,
        how.subject,
        start.id,
        type_id=kind.id,
        direction=rel.RelationshipDirection.FORWARD,
        target_ids=[end.id],
        source=SOURCE,
    )
    return domain.CiRowOutcome.CREATED


async def _finish(
    database: Database,
    tenant: uuid.UUID,
    ref: tuple[uuid.UUID, uuid.UUID],
    *,
    failure: str | None = None,
) -> None:
    async with database.tenant_session(TenantContext(tenant, ref[1])) as session:
        job = await session.get(CiImport, ref[0], with_for_update=True)
        finished = (
            domain.CiImportStatus.DONE,
            domain.CiImportStatus.FAILED,
            domain.CiImportStatus.CHECKED,
        )
        if job is None or job.status in finished:
            return
        if failure is not None:
            job.status, job.failure, job.content = domain.CiImportStatus.FAILED.value, failure, None
            job.finished_at = datetime.now(UTC)
        elif job.dry_run:
            job.status, job.checked_at = domain.CiImportStatus.CHECKED.value, datetime.now(UTC)
        else:
            job.status, job.content = domain.CiImportStatus.DONE.value, None  # not kept once read
            job.finished_at = datetime.now(UTC)
        job.version += 1
        await _progress(session, job)
