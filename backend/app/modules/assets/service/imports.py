"""Importing assets, consumables and vendors from CSV or Excel (WP-049b S4b, S4c; REQ-AST-053).

The people import's job pattern (WP-021, identity_access/service/people_import.py): the API
stores the file on a queued import and returns at once; the import job (a schedule in the
consumers worker) reads it with WP-021's limits (app/shared/sheets.py; up to 20,000 rows here)
and applies the rows in batches, one transaction per batch. A bad row is reported (row,
column, reason code) and the others are kept. Each batch commits its progress with an event
(`assets.import_progress` on the importer's own channel), so the import screen moves live.

- **Dry run first (AC2):** every row goes through the same service calls inside a savepoint
  that is always rolled back, so nothing changes (no record, history, event or tag number); the
  import ends `checked` with what would be created and updated, and keeps the file. Running it
  (`start_run`) queues the same file for real.
- **Modes:** add only, update only, add and update (AC3); rows match on the asset tag or serial
  number, a consumable's product, a vendor's name. No "delete existing and add" mode.
- **As the importer:** each row is the importer's own change (scope, life cycle, licence slot,
  D-157 money), through `create_asset` / `update_asset`, the consumable calls, or
  procurement's `create_vendor` / `update_vendor`, one call per row: every record keeps its own
  permission check, history, outbox event and audit entry.

**Speed (S4c; 20,000 rows took 47 ms a row on CI).** The services are still called once per
row; what changed is the work around them:

- **Lookups once per job:** product, site and vendor names are resolved once per job
  (`Lookups`: made by the job for its own tenant and importer, never shared, answering as the
  row path's lookups do), and the records a batch's rows match are read in one query for the
  whole batch instead of one per row.
- **Check, then write:** each row is first checked without writing (columns, dates, money,
  names, the mode against the records read), in the order the row path checked it. The rows
  that pass go through the services together in one savepoint per batch (rolled back in a dry
  run). If any is refused, that savepoint is rolled back and the batch is redone row by row,
  each row in its own savepoint and checked afresh, so the problems are exactly the row path's.
  A key twice in a batch splits the savepoint there, so the second row sees the first as the
  row path did (in a dry run: does not).
- **Short locks:** a save holds the tag counter row and the asset limit's lock until its
  transaction commits, so a transaction ends after BATCH rows or BATCH_SECONDS, whichever comes
  first; someone adding an asset meanwhile waits that long at most. Tag numbers are taken in the
  caller's transaction (app/shared/db/display_ids.py), so a rolled-back savepoint (a dry run, a
  refused batch) gives its numbers back.
- The asset service reads the tenant's configuration once per (sub)transaction
  (service/memo.py).
- **Rows written together (step B):** inside a batch savepoint, the rows' outbox events, field
  history, audit entries and new valuations wait in a buffer and go in one INSERT per table
  when the rows are done (app/shared/db/deferred.py): about one statement per asset instead of
  seven. The row-by-row redo writes each row's at once, as before.
"""

import contextlib
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.errors import AppError, Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules import procurement
from app.modules.assets.domain.assets import counts_toward_limit
from app.modules.assets.domain.batch import (
    IMPORT_LIMITS,
    MATCHES,
    MAX_IMPORT_PROBLEMS,
    MAX_IMPORT_ROWS,
    AssetImportStatus,
    ImportKind,
    ImportMatch,
    ImportMode,
    ImportRefused,
    ImportRowOutcome,
    day,
    flag,
    read_import,
)
from app.modules.assets.domain.catalogue import AssetStateCategory
from app.modules.assets.events import AssetImportProgressed
from app.modules.assets.infra.models import (
    Asset,
    AssetConsumable,
    AssetImport,
    AssetProduct,
    AssetProductType,
    AssetState,
)
from app.modules.assets.service import consumables
from app.modules.assets.service.assets import (
    LIMIT_CODE,
    MANAGE,
    create_asset,
    prefetch_unique,
    return_unused_tags,
    update_asset,
    use_tag_blocks,
)
from app.modules.assets.service.memo import keep_slot_count
from app.modules.identity_access import Subject, subject_for
from app.modules.licensing import LimitKey, remaining
from app.modules.organization import find_site
from app.shared import sheets
from app.shared.db.deferred import deferred_writes
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history.conflicts import stale_version

log = get_logger(__name__)

BATCH = 100  # rows per transaction at most
BATCH_SECONDS = 2.0  # and at most about this long: the locks a save holds end with it
SOURCE: Literal["import"] = "import"
# File format names, sent as values so labels isolate them (as the people import does).
FORMAT_WORDS = {
    "csv": "CSV (UTF-8)",
    "xlsx": ".xlsx",
    "max_rows": str(MAX_IMPORT_ROWS),
    "max_mb": str(IMPORT_LIMITS.max_file_bytes // 2**20),
}
_ASSET_TEXT = (
    "name",
    "tag",
    "serial_number",
    "barcode",
    "location",
    "description",
    "cost_centre",
    "gl_code",
    "currency",
)
_ASSET_DATES = ("acquired_on", "warranty_expires_on", "expires_on")
_ASSET_MONEY = ("purchase_price", "purchase_tax")
_VENDOR_TEXT = (
    "currency",
    "description",
    "contact_person",
    "address",
    "email",
    "phone",
    "fax",
    "website",
)
_CURRENCY = re.compile(r"[A-Z]{3}")
# What a row matches on, as compared: a lowered tag, serial or vendor name, a product's ID.
type Key = str | uuid.UUID


class ImportRepository(Repository[AssetImport]):
    """Asset imports of the session's tenant."""

    model = AssetImport


class RowProblem(Exception):
    """One row cannot be applied: the column and the reason code."""

    def __init__(self, field: str, code: str) -> None:
        """`field`: the column the problem is in ("row" for the row as a whole)."""
        super().__init__(code)
        self.field = field
        self.code = code


def require_import(subject: Subject, kind: ImportKind, mode: ImportMode) -> None:
    """Who may import: assets.manage for assets and consumables; vendors' own rights for them."""
    needed: list[str] = []
    if kind == ImportKind.VENDORS:
        if mode != ImportMode.UPDATE:
            needed.append(procurement.VENDORS_CREATE)
        if mode != ImportMode.ADD:
            needed.append(procurement.VENDORS_MANAGE)
    else:
        needed.append(MANAGE)
    for permission in needed:
        if not subject.holds(permission):
            raise PermissionDenied(params={"permission": permission})


async def start_import(  # noqa: PLR0913 - the upload's facts, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    kind: ImportKind,
    mode: ImportMode,
    match_on: ImportMatch,
    file_name: str,
    content: bytes,
    dry_run: bool = True,
) -> AssetImport:
    """Queue a file (a dry run unless asked otherwise). Only its kind and size are checked here."""
    require_import(subject, kind, mode)
    if match_on not in MATCHES[kind]:
        raise ValidationFailed(code="asset_import_match_invalid", params={"kind": kind.value})
    try:
        file_format = sheets.file_format(file_name, content)
        if len(content) > IMPORT_LIMITS.max_file_bytes:
            raise sheets.SheetRefused(sheets.FILE_TOO_LARGE)  # noqa: TRY301 - the job's refusal
    except sheets.SheetRefused as refused:
        raise ValidationFailed(code=f"asset_import_{refused.code}", params=FORMAT_WORDS) from None
    job = await ImportRepository(session).add(
        AssetImport(
            kind=kind.value,
            mode=mode.value,
            match_on=match_on.value,
            dry_run=dry_run,
            file_name=file_name[:255] or "import",
            file_format=file_format,
            content=content,
            status=AssetImportStatus.QUEUED.value,
            problems=[],
        )
    )
    await _progress(session, job)
    return job


async def own_import(session: AsyncSession, subject: Subject, import_id: uuid.UUID) -> AssetImport:
    """One of the subject's own imports (anyone else's is not found)."""
    found: AssetImport | None = await session.scalar(
        select(AssetImport).where(
            AssetImport.id == import_id,
            AssetImport.created_by == subject.user_id,
            AssetImport.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="asset_import_not_found")
    return found


async def recent_imports(
    session: AsyncSession, subject: Subject, *, limit: int = 20
) -> list[AssetImport]:
    """The subject's latest imports, newest first."""
    rows = await session.scalars(
        select(AssetImport)
        .where(AssetImport.created_by == subject.user_id, AssetImport.deleted_at.is_(None))
        .order_by(AssetImport.created_at.desc(), AssetImport.id.desc())
        .limit(limit)
    )
    return list(rows)


async def start_run(
    session: AsyncSession, subject: Subject, import_id: uuid.UUID, *, expected_version: int
) -> AssetImport:
    """Run a checked dry run for real: the same file, mode and match (If-Match)."""
    job = await own_import(session, subject, import_id)
    require_import(subject, ImportKind(job.kind), ImportMode(job.mode))
    if job.version != expected_version:
        raise await stale_version(
            session, job, expected_version=expected_version, record_type="asset_import",
            record_id=job.id,
        )  # fmt: skip
    if job.status != AssetImportStatus.CHECKED or job.content is None:
        raise Conflict(code="asset_import_not_checked", params={"status": job.status})
    job.dry_run = False
    job.status = AssetImportStatus.QUEUED.value
    job.processed = job.created_count = job.updated_count = job.failed_count = 0
    job.problems = []
    job.finished_at = None
    job.version += 1
    await session.flush()
    await _progress(session, job)
    return job


async def _progress(session: AsyncSession, job: AssetImport) -> None:
    if job.created_by is None:  # pragma: no cover - imports are only started by people
        return
    await record_event(
        session,
        AssetImportProgressed(
            import_id=job.id,
            requested_by=job.created_by,
            status=job.status,  # type: ignore[arg-type]  # CHECK constraint: a status code
            processed=job.processed,
            total=job.total,
        ),
        aggregate_id=job.id,
    )


# --- the worker -----------------------------------------------------------------------------------


async def run_asset_imports(database: Database, settings: Settings) -> None:
    """Schedule: every tenant's queued imports (and any a stopped run left running), in order."""
    del settings
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        while (ref := await _next(database, tenant)) is not None:
            try:
                await _run(database, tenant, ref)
            except Exception:  # one broken import must not stop the others; it is logged
                log.exception("asset_import_failed", import_id=str(ref[0]))
                await _finish(database, tenant, ref, failure="unexpected")


async def _next(database: Database, tenant: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        row = (
            await session.execute(
                select(AssetImport.id, AssetImport.created_by)
                .where(
                    AssetImport.status.in_((AssetImportStatus.QUEUED, AssetImportStatus.RUNNING)),
                    AssetImport.deleted_at.is_(None),
                )
                .order_by(AssetImport.created_at, AssetImport.id)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        if row.created_by is None:  # pragma: no cover - imports are only started by people
            found = await session.get(AssetImport, row.id)
            if found is not None:
                found.status, found.failure = AssetImportStatus.FAILED.value, "unexpected"
            return None
    return row.id, row.created_by


async def _run(database: Database, tenant: uuid.UUID, ref: tuple[uuid.UUID, uuid.UUID]) -> None:
    import_id, importer = ref
    context = TenantContext(tenant, importer)  # the rows are the importer's own changes
    async with database.tenant_session(context) as session:
        job = await session.get(AssetImport, import_id)
        if job is None or job.content is None:
            return
        kind, match_on = ImportKind(job.kind), ImportMatch(job.match_on)
        try:
            sheet = read_import(kind, match_on, job.file_format, job.content)
        except ImportRefused as refused:
            job.status, job.failure, job.content = "failed", refused.code, None
            job.failure_detail = (refused.detail or "")[:100] or None
            job.finished_at = datetime.now(UTC)
            job.version += 1
            await _progress(session, job)
            return
        rows = sheet.rows
        offset = job.processed
        if job.status != AssetImportStatus.RUNNING:
            job.status, job.total = AssetImportStatus.RUNNING.value, len(rows)
            job.version += 1
            await _progress(session, job)
    lookups = Lookups(tenant=tenant, requester=importer)  # this job's own, never shared
    while offset < len(rows):
        async with database.tenant_session(context) as session:
            offset = await _batch(session, import_id, rows, offset, lookups)
    await _finish(database, tenant, ref)


@dataclass(slots=True)
class _Tally:
    """One transaction's outcomes, written to the import once at its end."""

    problems: list[dict[str, Any]]
    created: int = 0
    updated: int = 0
    failed: int = 0

    def add(self, number: int, outcome: ImportRowOutcome | RowProblem) -> None:
        if isinstance(outcome, RowProblem):
            self.failed += 1
            if len(self.problems) < MAX_IMPORT_PROBLEMS:
                self.problems.append({"row": number, "field": outcome.field, "code": outcome.code})
        elif outcome == ImportRowOutcome.CREATED:
            self.created += 1
        else:
            self.updated += 1


@dataclass(frozen=True, slots=True)
class _How:
    """How the rows of one import are applied, and by whom."""

    subject: Subject
    kind: ImportKind
    mode: ImportMode
    match_on: ImportMatch
    dry_run: bool
    lookups: "Lookups"
    deadline: float


async def _batch(
    session: AsyncSession,
    import_id: uuid.UUID,
    rows: Sequence[tuple[int, dict[str, str]]],
    offset: int,
    lookups: "Lookups",
) -> int:
    """One transaction: up to BATCH rows from `offset`, or fewer once BATCH_SECONDS have passed.

    Returns the offset to go on from. The time bound keeps the locks a save takes until commit
    (the tag counter row, the asset limit's lock) short, so a person adding an asset meanwhile
    waits about BATCH_SECONDS at most.
    """
    job = await session.get(AssetImport, import_id, with_for_update=True)
    if job is None or job.created_by is None:  # pragma: no cover - never hard-deleted
        return len(rows)
    how = _How(
        subject=await subject_for(session, lookups.tenant, job.created_by),
        kind=ImportKind(job.kind),
        mode=ImportMode(job.mode),
        match_on=ImportMatch(job.match_on),
        dry_run=job.dry_run,
        lookups=lookups,
        deadline=time.monotonic() + BATCH_SECONDS,
    )
    batch = list(rows[offset : offset + BATCH])
    tally = _Tally(problems=list(job.problems))
    done = 0
    found = await _prefetch(session, how, batch)
    while done < len(batch) and (done == 0 or time.monotonic() < how.deadline):
        plans = await _chunk(session, how, batch[done:], found)
        applied = await _apply_chunk(session, how, plans, tally)
        done += applied
        if not how.dry_run and done < len(batch):
            found = await _prefetch(session, how, batch[done:])  # what this run just made
    job.processed += done
    job.created_count += tally.created
    job.updated_count += tally.updated
    job.failed_count += tally.failed
    job.problems = tally.problems
    job.version += 1
    await _progress(session, job)
    return offset + done


async def _chunk(
    session: AsyncSession,
    how: _How,
    rows: Sequence[tuple[int, dict[str, str]]],
    found: Mapping[Key, uuid.UUID],
) -> list["Plan"]:
    """Check the next rows without writing (AC2), up to a key a row before them already has.

    A key twice in one savepoint would see the first row's write; split there, the second row
    is checked once the first is done, as the row-by-row import always did.
    """
    plans: list[Plan] = []
    keys: set[Key] = set()
    for number, values in rows:
        plan = await prepare_row(session, how, number, values, found)
        if plan.key is not None and plan.key in keys:
            break
        if plan.key is not None:
            keys.add(plan.key)
        plans.append(plan)
    return plans


async def _apply_chunk(
    session: AsyncSession, how: _How, plans: Sequence["Plan"], tally: _Tally
) -> int:
    """The checked rows through the services in one savepoint; row by row once any is refused.

    Returns how many rows it used (at least one; fewer than `plans` once the time is up).
    """
    outcomes: list[ImportRowOutcome | RowProblem] = []
    savepoint = await session.begin_nested()
    keep_slot_count(session)  # a refusal redoes the rows one by one, each counting afresh
    if how.kind == ImportKind.ASSETS:  # the creates' tags and serials, one query (S4c follow-up)
        creates = [p.fields for p in plans if p.problem is None and p.record_id is None]
        await prefetch_unique(session, creates)
        use_tag_blocks(session, sum(1 for f in creates if not f.get("tag")))
    try:
        # The rows' outbox events, history, audit entries and valuations go in one INSERT per
        # table when the block ends (step B; app/shared/db/deferred.py). A dry run drops them:
        # its savepoint is rolled back anyway, and every check ran before a row was buffered.
        # Closed before the savepoint ends, so a refusal (an exception) writes none of them.
        async with deferred_writes(session, write=not how.dry_run):
            for plan in plans:
                if outcomes and time.monotonic() >= how.deadline:
                    break
                outcomes.append(plan.problem or await execute_row(session, how, plan))
    except (RowProblem, IntegrityError):
        await savepoint.rollback()  # nothing of the savepoint stays: redo each row on its own
        return await _one_by_one(session, how, plans[: len(outcomes) + 1], tally)
    except BaseException:
        await savepoint.rollback()
        raise
    if how.dry_run:
        await savepoint.rollback()  # AC2: a dry run changes nothing, tag numbers included
    else:
        await return_unused_tags(session)  # only the saved rows keep numbers, no gap
        await savepoint.commit()
    for plan, outcome in zip(plans, outcomes, strict=False):
        tally.add(plan.number, await _dry_limit(session, how, plan, outcome))
    return len(outcomes)


async def _one_by_one(
    session: AsyncSession, how: _How, plans: Sequence["Plan"], tally: _Tally
) -> int:
    """Each row in its own savepoint, checked afresh: the per-row problems exactly as before."""
    used = 0
    for plan in plans:
        if used and time.monotonic() >= how.deadline:
            break
        used += 1
        savepoint = await session.begin_nested()
        try:
            fresh = await prepare_row(session, how, plan.number, plan.values, None)
            outcome = fresh.problem or await execute_row(session, how, fresh)
        except (RowProblem, IntegrityError) as refused:
            await savepoint.rollback()
            # A value the database refuses (a CHECK the services do not repeat) is a bad row too.
            tally.add(plan.number, _problem(refused))
            continue
        except BaseException:
            await savepoint.rollback()
            raise
        if how.dry_run or isinstance(outcome, RowProblem):
            await savepoint.rollback()
        else:
            await savepoint.commit()
        tally.add(plan.number, await _dry_limit(session, how, fresh, outcome))
    return used


async def _dry_limit(
    session: AsyncSession, how: _How, plan: "Plan", outcome: ImportRowOutcome | RowProblem
) -> ImportRowOutcome | RowProblem:
    """A dry run's row as the run would end it under the asset limit (lane A, #434).

    Each dry-run row is rolled back, so the service's own reservation never sees the slots the
    earlier rows would take. Here, in file order, from the slots left (read once per job), a
    row that makes a counting asset takes one and is refused (`asset_limit_reached`, as the
    run refuses it) when none is left; a row that makes a counting asset non-counting frees
    one. Imports set no state, so only a create and a product change can switch counting.
    A real run is untouched: `reserve_capacity` under the limit's lock stays the only judge.
    """
    if not how.dry_run or how.kind != ImportKind.ASSETS or isinstance(outcome, RowProblem):
        return outcome
    change = await _slot_change(session, how.lookups, plan)
    lookups = how.lookups
    if change == 0:
        return outcome
    if not lookups.slots_read:
        lookups.slots_left = await remaining(session, LimitKey.ASSETS)
        lookups.slots_read = True
    if lookups.slots_left is None:
        return outcome  # unlimited
    if change > 0 and lookups.slots_left < change:
        return RowProblem(field="row", code=LIMIT_CODE)
    lookups.slots_left -= change
    return outcome


async def _counts_as(
    session: AsyncSession, lookups: "Lookups", product_id: uuid.UUID, state: str
) -> bool:
    if product_id not in lookups.product_kinds:
        row = (
            await session.execute(
                select(AssetProductType.category, AssetProductType.kind)
                .join(AssetProduct, AssetProduct.product_type_id == AssetProductType.id)
                .where(AssetProduct.id == product_id)
            )
        ).one()
        lookups.product_kinds[product_id] = (row.category, row.kind)
    category, kind = lookups.product_kinds[product_id]
    return counts_toward_limit(category, kind, state)


async def _slot_change(session: AsyncSession, lookups: "Lookups", plan: "Plan") -> int:
    """+1: the row makes a counting asset; -1: it makes one non-counting; 0: neither."""
    product_id = plan.fields.get("product_id")
    if plan.record_id is None:  # a create: the default in-stock state, as `create_asset`
        if product_id is None:
            return 0
        return int(await _counts_as(session, lookups, product_id, AssetStateCategory.IN_STOCK))
    if product_id is None:
        return 0  # the product (and so the type) stays; imports set no state
    current = (
        await session.execute(
            select(Asset.product_id, AssetState.category)
            .join(AssetState, AssetState.id == Asset.state_id)
            .where(Asset.id == plan.record_id)
        )
    ).one_or_none()
    if current is None:
        return 0
    before = await _counts_as(session, lookups, current.product_id, current.category)
    after = await _counts_as(session, lookups, product_id, current.category)
    return int(after) - int(before)


def _problem(refused: Exception) -> RowProblem:
    if isinstance(refused, RowProblem):
        return refused
    return RowProblem(field="row", code="invalid_value")


async def _finish(
    database: Database,
    tenant: uuid.UUID,
    ref: tuple[uuid.UUID, uuid.UUID],
    *,
    failure: str | None = None,
) -> None:
    async with database.tenant_session(TenantContext(tenant, ref[1])) as session:
        job = await session.get(AssetImport, ref[0], with_for_update=True)
        finished = (AssetImportStatus.DONE, AssetImportStatus.FAILED, AssetImportStatus.CHECKED)
        if job is None or job.status in finished:
            return
        if failure is not None:
            job.status, job.failure, job.content = AssetImportStatus.FAILED.value, failure, None
            job.finished_at = datetime.now(UTC)
        elif job.dry_run:
            job.status, job.checked_at = AssetImportStatus.CHECKED.value, datetime.now(UTC)
        else:
            job.status, job.content = AssetImportStatus.DONE.value, None  # not kept once read
            job.finished_at = datetime.now(UTC)
        job.version += 1
        await _progress(session, job)


# --- one row ----------------------------------------------------------------------------------


@dataclass(slots=True)
class Lookups:
    """Names a job's rows give, resolved once per job (S4c), for one tenant and one importer.

    A job makes its own (never a module global, never shared with another job), and it refuses
    a session of another tenant or person. It answers exactly as the row path did: the lookups
    behind it (`find_site`, `find_vendor_id`, the product by name) read the tenant's live
    records with no person's scope, so neither does the cache. What the importer may do with
    the record a row names is still decided by the service, on every row.
    """

    tenant: uuid.UUID
    requester: uuid.UUID
    products: dict[str, uuid.UUID | str] = field(default_factory=dict)  # an ID, or a problem code
    sites: dict[str, uuid.UUID | None] = field(default_factory=dict)
    vendors: dict[str, uuid.UUID | None] = field(default_factory=dict)
    # The dry run's view of the asset limit (#434): slots left, read once per job (None:
    # unlimited), then taken and freed by each row's outcome in file order.
    slots_read: bool = False
    slots_left: int | None = None
    product_kinds: dict[uuid.UUID, tuple[str, str]] = field(default_factory=dict)

    def _check(self, session: AsyncSession) -> None:
        context = session.info.get(SESSION_TENANT_KEY)
        if not isinstance(context, TenantContext) or (context.tenant_id, context.user_id) != (
            self.tenant,
            self.requester,
        ):
            msg = "an import's lookups serve only its own tenant and importer"
            raise RuntimeError(msg)

    async def product(self, session: AsyncSession, name: str) -> uuid.UUID:
        """The live product of this name (RowProblem: none, or more than one)."""
        self._check(session)
        wanted = " ".join(name.split()).lower()
        if wanted not in self.products:
            self.products[wanted] = await _product_id(session, wanted)
        found = self.products[wanted]
        if isinstance(found, str):
            raise RowProblem(field="product", code=found)
        return found

    async def site(self, session: AsyncSession, name: str) -> uuid.UUID | None:
        """`find_site`'s answer."""
        self._check(session)
        wanted = name.strip().lower()
        if wanted not in self.sites:
            self.sites[wanted] = await find_site(session, name)
        return self.sites[wanted]

    async def vendor(self, session: AsyncSession, name: str) -> uuid.UUID | None:
        """`procurement.find_vendor_id`'s answer."""
        self._check(session)
        wanted = " ".join(name.split()).lower()
        if wanted not in self.vendors:
            self.vendors[wanted] = await procurement.find_vendor_id(session, name)
        return self.vendors[wanted]


@dataclass(frozen=True, slots=True)
class Plan:
    """A checked row: what it will do, or its problem. Nothing is written to make one."""

    number: int
    values: Mapping[str, str]
    key: Key | None = None  # what the row matches on, as compared (None: matches nothing)
    problem: RowProblem | None = None
    fields: Mapping[str, Any] = field(default_factory=dict)
    record_id: uuid.UUID | None = None  # the record it updates (None: it creates one)


async def _prefetch(
    session: AsyncSession, how: _How, rows: Sequence[tuple[int, dict[str, str]]]
) -> dict[Key, uuid.UUID]:
    """The existing records the rows match, in one query for all of them (S4c)."""
    match how.kind:
        case ImportKind.ASSETS:
            column = Asset.tag if how.match_on == ImportMatch.TAG else Asset.serial_number
            wanted = {values.get(how.match_on.value, "").lower() for _, values in rows} - {""}
            if not wanted:
                return {}
            found = await session.execute(
                select(func.lower(column), Asset.id).where(
                    func.lower(column).in_(sorted(wanted)), Asset.deleted_at.is_(None)
                )
            )
            # Keyed by lower() as the database lowers it: `get(key.lower())` is the row path's
            # `lower(column) = key.lower()` exactly.
            return {str(row[0]): row[1] for row in found}
        case ImportKind.CONSUMABLES:
            products: set[uuid.UUID] = set()
            for _, values in rows:
                if values.get("product"):
                    with contextlib.suppress(RowProblem):  # the row's own check reports it
                        products.add(await how.lookups.product(session, values["product"]))
            if not products:
                return {}
            held = await session.execute(
                select(AssetConsumable.product_id, AssetConsumable.id)
                .where(
                    AssetConsumable.product_id.in_(products), AssetConsumable.deleted_at.is_(None)
                )
                .order_by(AssetConsumable.id)
            )
            consumables: dict[Key, uuid.UUID] = {}
            for product_id, consumable_id in held:
                consumables.setdefault(product_id, consumable_id)
            return consumables
        case ImportKind.VENDORS:
            names = [values.get("name", "") for _, values in rows]
            vendors: dict[Key, uuid.UUID] = {}
            vendors.update(await procurement.find_vendors(session, names))
            return vendors


async def _existing(
    session: AsyncSession, how: _How, key: Key, found: Mapping[Key, uuid.UUID] | None
) -> uuid.UUID | None:
    """The record a row matches: from the batch's prefetch, or (`found` None) read now."""
    if found is not None:
        return found.get(key)
    match how.kind:
        case ImportKind.ASSETS:
            column = Asset.tag if how.match_on == ImportMatch.TAG else Asset.serial_number
            return await session.scalar(
                select(Asset.id).where(func.lower(column) == key, Asset.deleted_at.is_(None))
            )
        case ImportKind.CONSUMABLES:
            return await session.scalar(
                select(AssetConsumable.id).where(
                    AssetConsumable.product_id == key, AssetConsumable.deleted_at.is_(None)
                )
            )
        case ImportKind.VENDORS:
            vendor = await procurement.find_vendor(session, str(key))
            return None if vendor is None else vendor.id


async def prepare_row(
    session: AsyncSession,
    how: _How,
    number: int,
    values: Mapping[str, str],
    found: Mapping[Key, uuid.UUID] | None,
) -> Plan:
    """Check one row without writing: columns, dates, money, names, and the mode (AC3).

    The checks run in the order the row path always ran them, so the first problem found is the
    one reported. `found`: the batch's prefetched records (None: look the row's up now).
    """
    try:
        match how.kind:
            case ImportKind.ASSETS:
                return await _asset_plan(session, how, number, values, found)
            case ImportKind.CONSUMABLES:
                return await _consumable_plan(session, how, number, values, found)
            case ImportKind.VENDORS:
                return await _vendor_plan(session, how, number, values, found)
    except RowProblem as problem:
        return Plan(number=number, values=values, problem=problem)


async def execute_row(session: AsyncSession, how: _How, plan: Plan) -> ImportRowOutcome:
    """Apply a checked row through the services, as the importer; RowProblem when refused."""
    try:
        match how.kind:
            case ImportKind.ASSETS:
                return await _asset_row(session, how.subject, plan)
            case ImportKind.CONSUMABLES:
                return await _consumable_row(session, how.subject, plan)
            case ImportKind.VENDORS:
                return await _vendor_row(session, how.subject, plan)
    except ValidationFailed as invalid:
        first = invalid.errors[0] if invalid.errors else None
        field_name = first.field.removeprefix("body.") if first else "row"
        raise RowProblem(field_name, first.code if first else invalid.instance_code) from invalid
    except AppError as refused:  # permission, scope, licence slot, conflicts: the row is refused
        raise RowProblem(field="row", code=refused.instance_code) from refused


def _check_mode(mode: ImportMode, *, found: bool, key_field: str) -> None:
    if found and mode == ImportMode.ADD:
        raise RowProblem(field=key_field, code="asset_import_exists")
    if not found and mode == ImportMode.UPDATE:
        raise RowProblem(field=key_field, code="asset_import_no_match")


async def _product_id(session: AsyncSession, wanted: str) -> uuid.UUID | str:
    """The live product named `wanted` (spaced and lowered), or the problem's code."""
    found = list(
        await session.scalars(
            select(AssetProduct.id)
            .where(func.lower(AssetProduct.name) == wanted, AssetProduct.deleted_at.is_(None))
            .limit(2)
        )
    )
    if not found:
        return "asset_product_not_found"
    if len(found) > 1:
        return "asset_product_ambiguous"
    return found[0]


def _amount(name: str, value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        raise RowProblem(field=name, code="invalid_number") from None


async def _asset_values(  # noqa: C901 - one rule per column, flat
    session: AsyncSession, lookups: Lookups, values: Mapping[str, str]
) -> dict[str, Any]:
    """The row's filled cells as the asset service takes them; an empty cell leaves a value."""
    fields: dict[str, Any] = {name: values[name] for name in _ASSET_TEXT if values.get(name)}
    for name in _ASSET_DATES:
        if values.get(name):
            parsed = day(values[name])
            if parsed is None:
                raise RowProblem(field=name, code="invalid_date")
            fields[name] = parsed
    for name in _ASSET_MONEY:
        if values.get(name):
            fields[name] = _amount(name, values[name])
    if values.get("product"):
        fields["product_id"] = await lookups.product(session, values["product"])
    if values.get("site"):
        site_id = await lookups.site(session, values["site"])
        if site_id is None:
            raise RowProblem(field="site", code="site_not_found")
        fields["site_id"] = site_id
    if values.get("vendor"):
        vendor_id = await lookups.vendor(session, values["vendor"])
        if vendor_id is None:
            raise RowProblem(field="vendor", code="vendor_not_found")
        fields["vendor_id"] = vendor_id
    if "currency" in fields:
        fields["currency"] = _currency(str(fields["currency"]))
    return fields


def _currency(value: str) -> str:
    code = value.strip().upper()
    if not _CURRENCY.fullmatch(code):
        raise RowProblem(field="currency", code="invalid_choice")
    return code


async def _asset_plan(
    session: AsyncSession,
    how: _How,
    number: int,
    values: Mapping[str, str],
    found: Mapping[Key, uuid.UUID] | None,
) -> Plan:
    key = values.get(how.match_on.value, "")
    existing = await _existing(session, how, key.lower(), found) if key else None
    if not key and how.mode == ImportMode.UPDATE:
        raise RowProblem(field=how.match_on.value, code="required")
    _check_mode(how.mode, found=existing is not None, key_field=how.match_on.value)
    fields = await _asset_values(session, how.lookups, values)
    if existing is not None:
        fields.pop(how.match_on.value, None)  # the key it was found by stays as it is
    return Plan(
        number=number,
        values=values,
        key=key.lower() or None,
        fields=fields,
        record_id=existing,
    )


async def _version(
    session: AsyncSession, model: type[Asset | AssetConsumable], row_id: uuid.UUID
) -> int:
    """The version the record has now: the service's If-Match, as when it was read per row."""
    return await session.scalar(select(model.version).where(model.id == row_id)) or 0


async def _asset_row(session: AsyncSession, subject: Subject, plan: Plan) -> ImportRowOutcome:
    if plan.record_id is None:
        await create_asset(session, subject, plan.fields, source=SOURCE)
        return ImportRowOutcome.CREATED
    await update_asset(
        session, subject, plan.record_id, plan.fields,
        expected_version=await _version(session, Asset, plan.record_id), source=SOURCE,
    )  # fmt: skip
    return ImportRowOutcome.UPDATED


async def _consumable_plan(
    session: AsyncSession,
    how: _How,
    number: int,
    values: Mapping[str, str],
    found: Mapping[Key, uuid.UUID] | None,
) -> Plan:
    if not values.get("product"):
        raise RowProblem(field="product", code="required")
    product_id = await how.lookups.product(session, values["product"])
    existing = await _existing(session, how, product_id, found)
    _check_mode(how.mode, found=existing is not None, key_field="product")
    fields: dict[str, Any] = {k: values[k] for k in ("barcode", "comment") if values.get(k)}
    if values.get("unit_cost"):
        fields["unit_cost"] = _amount("unit_cost", values["unit_cost"])
    if values.get("vendor"):
        vendor_id = await how.lookups.vendor(session, values["vendor"])
        if vendor_id is None:
            raise RowProblem(field="vendor", code="vendor_not_found")
        fields["vendor_id"] = vendor_id
    tracked = None
    if values.get("batch_tracked"):
        tracked = flag(values["batch_tracked"])
        if tracked is None:
            raise RowProblem(field="batch_tracked", code="invalid_choice")
    if existing is None:
        fields["product_id"] = product_id
        fields["batch_tracked"] = bool(tracked)
    elif tracked is not None:
        fields["batch_tracked"] = tracked  # a change is refused: fixed when it was made (033)
    return Plan(number=number, values=values, key=product_id, fields=fields, record_id=existing)


async def _consumable_row(session: AsyncSession, subject: Subject, plan: Plan) -> ImportRowOutcome:
    if plan.record_id is None:
        await consumables.create_consumable(session, subject, plan.fields)
        return ImportRowOutcome.CREATED
    version = await _version(session, AssetConsumable, plan.record_id)
    await consumables.update_consumable(
        session, subject, plan.record_id, plan.fields, expected_version=version
    )
    return ImportRowOutcome.UPDATED


async def _vendor_plan(
    session: AsyncSession,
    how: _How,
    number: int,
    values: Mapping[str, str],
    found: Mapping[Key, uuid.UUID] | None,
) -> Plan:
    name = values.get("name", "")
    if not name:
        raise RowProblem(field="name", code="required")
    key = " ".join(name.split()).lower()
    existing = await _existing(session, how, key, found) if key else None
    _check_mode(how.mode, found=existing is not None, key_field="name")
    fields: dict[str, Any] = {k: values[k] for k in _VENDOR_TEXT if values.get(k)}
    if "currency" in fields:
        fields["currency"] = _currency(str(fields["currency"]))
    if existing is None:
        fields = {"name": name, **fields}
    return Plan(number=number, values=values, key=key or None, fields=fields, record_id=existing)


async def _vendor_row(session: AsyncSession, subject: Subject, plan: Plan) -> ImportRowOutcome:
    if plan.record_id is None:
        await procurement.create_vendor(session, subject, plan.fields, source=SOURCE)
        return ImportRowOutcome.CREATED
    vendor = await procurement.find_vendor(session, plan.values.get("name", ""))
    await procurement.update_vendor(
        session, subject, plan.record_id, plan.fields,
        expected_version=0 if vendor is None else vendor.version, source=SOURCE,
    )  # fmt: skip
    return ImportRowOutcome.UPDATED
