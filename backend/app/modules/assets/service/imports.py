"""Importing assets, consumables and vendors from CSV or Excel (WP-049b S4b; REQ-AST-053).

The people import's job pattern (WP-021, identity_access/service/people_import.py): the API
stores the file on a queued import and returns at once; the import job (a schedule in the
consumers worker) reads it with WP-021's limits (app/shared/sheets.py; up to 20,000 rows here)
and applies the rows in batches, one transaction per batch and one savepoint per row, so a bad
row is reported (row, column, reason code) and the others are kept. Each batch commits its
progress with an event, so the import screen moves live.

- **Dry run first (AC2):** every row goes through the same service calls inside a savepoint
  that is always rolled back, so nothing changes (no record, history, event or tag number); the
  import ends `checked` with what would be created and updated, and keeps the file. Running it
  (`start_run`) queues the same file for real.
- **Modes:** add only, update only, add and update (AC3); rows match on the asset tag or serial
  number, a consumable's product, a vendor's name. No "delete existing and add" mode.
- **As the importer:** each row is the importer's own change (scope, life cycle, licence slot,
  D-157 money), through `create_asset` / `update_asset`, the consumable calls, or
  procurement's `create_vendor` / `update_vendor`.
"""

import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import AppError, Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules import procurement
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
from app.modules.assets.events import AssetImportProgressed
from app.modules.assets.infra.models import Asset, AssetConsumable, AssetImport, AssetProduct
from app.modules.assets.service import consumables
from app.modules.assets.service.assets import MANAGE, create_asset, update_asset
from app.modules.identity_access import Subject, subject_for
from app.modules.organization import find_site
from app.shared import sheets
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history.conflicts import stale_version

log = get_logger(__name__)

BATCH = 100
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
        start = job.processed
        if job.status != AssetImportStatus.RUNNING:
            job.status, job.total = AssetImportStatus.RUNNING.value, len(rows)
            job.version += 1
            await _progress(session, job)
    for offset in range(start, len(rows), BATCH):
        async with database.tenant_session(context) as session:
            await _batch(session, tenant, import_id, rows[offset : offset + BATCH])
    await _finish(database, tenant, ref)


async def _batch(
    session: AsyncSession,
    tenant: uuid.UUID,
    import_id: uuid.UUID,
    rows: list[tuple[int, dict[str, str]]],
) -> None:
    job = await session.get(AssetImport, import_id, with_for_update=True)
    if job is None or job.created_by is None:  # pragma: no cover - never hard-deleted
        return
    subject = await subject_for(session, tenant, job.created_by)
    kind, mode, match_on = ImportKind(job.kind), ImportMode(job.mode), ImportMatch(job.match_on)
    problems = list(job.problems)
    for number, values in rows:
        savepoint = await session.begin_nested()
        try:
            outcome = await apply_row(
                session, subject, kind=kind, mode=mode, match_on=match_on, values=values
            )
        except (RowProblem, IntegrityError) as refused:
            await savepoint.rollback()
            # A value the database refuses (a CHECK the services do not repeat) is a bad row too.
            problem = (
                refused
                if isinstance(refused, RowProblem)
                else RowProblem(field="row", code="invalid_value")
            )
            job.failed_count += 1
            if len(problems) < MAX_IMPORT_PROBLEMS:
                problems.append({"row": number, "field": problem.field, "code": problem.code})
            continue
        except BaseException:
            await savepoint.rollback()
            raise
        if job.dry_run:
            await savepoint.rollback()  # AC2: a dry run changes nothing
        else:
            await savepoint.commit()
        if outcome == ImportRowOutcome.CREATED:
            job.created_count += 1
        else:
            job.updated_count += 1
    job.processed += len(rows)
    job.problems = problems
    job.version += 1
    await _progress(session, job)


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


async def apply_row(  # noqa: PLR0913 - the row and how to apply it, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    kind: ImportKind,
    mode: ImportMode,
    match_on: ImportMatch,
    values: Mapping[str, str],
) -> ImportRowOutcome:
    """Create or update one record from a row; RowProblem when the row cannot be applied."""
    try:
        match kind:
            case ImportKind.ASSETS:
                return await _asset_row(session, subject, mode, match_on, values)
            case ImportKind.CONSUMABLES:
                return await _consumable_row(session, subject, mode, values)
            case ImportKind.VENDORS:
                return await _vendor_row(session, subject, mode, values)
    except ValidationFailed as invalid:
        first = invalid.errors[0] if invalid.errors else None
        field = first.field.removeprefix("body.") if first else "row"
        raise RowProblem(field, first.code if first else invalid.instance_code) from invalid
    except AppError as refused:  # permission, scope, licence slot, conflicts: the row is refused
        raise RowProblem(field="row", code=refused.instance_code) from refused


def _check_mode(mode: ImportMode, *, found: bool, key_field: str) -> None:
    if found and mode == ImportMode.ADD:
        raise RowProblem(field=key_field, code="asset_import_exists")
    if not found and mode == ImportMode.UPDATE:
        raise RowProblem(field=key_field, code="asset_import_no_match")


async def _product_id(session: AsyncSession, name: str) -> uuid.UUID:
    wanted = " ".join(name.split()).lower()
    found = list(
        await session.scalars(
            select(AssetProduct.id)
            .where(func.lower(AssetProduct.name) == wanted, AssetProduct.deleted_at.is_(None))
            .limit(2)
        )
    )
    if not found:
        raise RowProblem(field="product", code="asset_product_not_found")
    if len(found) > 1:
        raise RowProblem(field="product", code="asset_product_ambiguous")
    return found[0]


def _amount(name: str, value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        raise RowProblem(field=name, code="invalid_number") from None


async def _asset_values(  # noqa: C901 - one rule per column, flat
    session: AsyncSession, values: Mapping[str, str]
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
        fields["product_id"] = await _product_id(session, values["product"])
    if values.get("site"):
        site_id = await find_site(session, values["site"])
        if site_id is None:
            raise RowProblem(field="site", code="site_not_found")
        fields["site_id"] = site_id
    if values.get("vendor"):
        vendor_id = await procurement.find_vendor_id(session, values["vendor"])
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


async def _asset_row(
    session: AsyncSession,
    subject: Subject,
    mode: ImportMode,
    match_on: ImportMatch,
    values: Mapping[str, str],
) -> ImportRowOutcome:
    key = values.get(match_on.value, "")
    column = Asset.tag if match_on == ImportMatch.TAG else Asset.serial_number
    existing = (
        await session.scalar(
            select(Asset).where(func.lower(column) == key.lower(), Asset.deleted_at.is_(None))
        )
        if key
        else None
    )
    if not key and mode == ImportMode.UPDATE:
        raise RowProblem(field=match_on.value, code="required")
    _check_mode(mode, found=existing is not None, key_field=match_on.value)
    fields = await _asset_values(session, values)
    if existing is None:
        await create_asset(session, subject, fields, source=SOURCE)
        return ImportRowOutcome.CREATED
    fields.pop(match_on.value, None)  # the key it was found by stays as it is
    await update_asset(
        session, subject, existing.id, fields, expected_version=existing.version, source=SOURCE
    )
    return ImportRowOutcome.UPDATED


async def _consumable_row(
    session: AsyncSession, subject: Subject, mode: ImportMode, values: Mapping[str, str]
) -> ImportRowOutcome:
    if not values.get("product"):
        raise RowProblem(field="product", code="required")
    product_id = await _product_id(session, values["product"])
    existing = await session.scalar(
        select(AssetConsumable).where(
            AssetConsumable.product_id == product_id, AssetConsumable.deleted_at.is_(None)
        )
    )
    _check_mode(mode, found=existing is not None, key_field="product")
    fields: dict[str, Any] = {k: values[k] for k in ("barcode", "comment") if values.get(k)}
    if values.get("unit_cost"):
        fields["unit_cost"] = _amount("unit_cost", values["unit_cost"])
    if values.get("vendor"):
        vendor_id = await procurement.find_vendor_id(session, values["vendor"])
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
        await consumables.create_consumable(session, subject, fields)
        return ImportRowOutcome.CREATED
    if tracked is not None:
        fields["batch_tracked"] = tracked  # a change is refused: fixed when it was made (033)
    await consumables.update_consumable(
        session, subject, existing.id, fields, expected_version=existing.version
    )
    return ImportRowOutcome.UPDATED


async def _vendor_row(
    session: AsyncSession, subject: Subject, mode: ImportMode, values: Mapping[str, str]
) -> ImportRowOutcome:
    name = values.get("name", "")
    if not name:
        raise RowProblem(field="name", code="required")
    existing = await procurement.find_vendor(session, name)
    _check_mode(mode, found=existing is not None, key_field="name")
    fields: dict[str, Any] = {k: values[k] for k in _VENDOR_TEXT if values.get(k)}
    if "currency" in fields:
        fields["currency"] = _currency(str(fields["currency"]))
    if existing is None:
        await procurement.create_vendor(session, subject, {"name": name, **fields}, source=SOURCE)
        return ImportRowOutcome.CREATED
    await procurement.update_vendor(
        session, subject, existing.id, fields, expected_version=existing.version, source=SOURCE
    )
    return ImportRowOutcome.UPDATED
