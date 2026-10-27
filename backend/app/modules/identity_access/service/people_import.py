"""Importing people from CSV or Excel in the background (WP-021, REQ-ADM-003).

The API stores the file on a queued import and returns at once. The import job (a schedule in
the consumers worker) reads it with the limits of domain/people_import.py, then applies the rows
in batches: one transaction per batch, one savepoint per row, so a bad row is reported and the
others are kept. Each batch commits its progress with an event, so the import screen moves live.

Rows match existing people by email or by employee ID (the admin chooses). A matched row changes
only the cells it fills; an empty cell leaves the value alone. A row that would make a technician
beyond the licence's seats is refused like any other bad row (`technician_limit_reached`).
"""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import AppError, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.people import LOCALES
from app.modules.identity_access.domain.people_import import (
    MAX_FILE_BYTES,
    ImportFailure,
    ImportRefused,
    file_format,
    flag,
    read_rows,
)
from app.modules.identity_access.events import PeopleImportProgressed
from app.modules.identity_access.infra.models import PeopleImport, User
from app.modules.identity_access.service.people import (
    create_person,
    set_sign_in,
    set_user_type,
    update_person,
)
from app.modules.organization import department_site, find_department, find_site
from app.shared.db.repository import Repository
from app.shared.events import record_event

log = get_logger(__name__)

BATCH = 100
MAX_PROBLEMS = 1000  # kept on the import; the counts stay exact beyond this
MatchOn = Literal["email", "employee_id"]
LANGUAGE_NAMES = {"english": "en", "arabic": "ar", "urdu": "ur"}


class ImportRepository(Repository[PeopleImport]):
    """People imports of the session's tenant."""

    model = PeopleImport


class RowProblem(Exception):
    """One row cannot be applied: the field and the reason code."""

    def __init__(self, field: str, code: str) -> None:
        """`field`: the person field (column) the problem is in."""
        super().__init__(code)
        self.field = field
        self.code = code


async def start_import(
    session: AsyncSession, file_name: str, content: bytes, match_on: MatchOn
) -> PeopleImport:
    """Queue a file. Only its kind and size are checked here; the job reads it."""
    try:
        kind = file_format(file_name, content)
        if len(content) > MAX_FILE_BYTES:
            raise ImportRefused(ImportFailure.TOO_LARGE)  # noqa: TRY301 - same refusal as the job's
    except ImportRefused as refused:
        raise ValidationFailed(code=f"people_import_{refused.failure.value}") from refused
    job = await ImportRepository(session).add(
        PeopleImport(
            file_name=file_name[:255] or "people",
            file_format=kind,
            content=content,
            match_on=match_on,
            status="queued",
            problems=[],
        )
    )
    await _progress(session, job)
    return job


async def _progress(session: AsyncSession, job: PeopleImport) -> None:
    await record_event(
        session,
        PeopleImportProgressed(
            import_id=job.id,
            status=job.status,  # type: ignore[arg-type]  # CHECK constraint: a valid status code
            processed=job.processed,
            total=job.total,
        ),
        aggregate_id=job.id,
    )


async def run_people_imports(database: Database, settings: Settings) -> None:
    """Schedule: every tenant's queued imports (and any a stopped run left running), in order."""
    del settings
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        while True:
            job = await _next(database, tenant)
            if job is None:
                break
            try:
                await _run(database, tenant, job)
            except Exception:  # one broken import must not stop the others; it is logged
                log.exception("people_import_failed", import_id=str(job[0]))
                await _finish(database, tenant, job[0], failure="unexpected")


async def _next(database: Database, tenant: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID | None] | None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        row = (
            await session.execute(
                select(PeopleImport.id, PeopleImport.created_by)
                .where(
                    PeopleImport.status.in_(("queued", "running")),
                    PeopleImport.deleted_at.is_(None),
                )
                .order_by(PeopleImport.created_at, PeopleImport.id)
                .limit(1)
            )
        ).one_or_none()
    return (row.id, row.created_by) if row is not None else None


async def _run(
    database: Database, tenant: uuid.UUID, job_ref: tuple[uuid.UUID, uuid.UUID | None]
) -> None:
    job_id, importer = job_ref
    context = TenantContext(tenant, importer)  # the rows are the importer's changes
    async with database.tenant_session(context) as session:
        job = await session.get(PeopleImport, job_id)
        if job is None or job.content is None:
            return
        try:
            sheet = read_rows(job.file_format, job.content)
        except ImportRefused as refused:
            job.status, job.failure, job.content = "failed", refused.failure.value, None
            job.finished_at = datetime.now(UTC)
            if refused.detail:
                job.problems = [
                    {
                        "row": None,
                        "field": None,
                        "code": refused.failure.value,
                        "detail": refused.detail,
                    }
                ]
            await _progress(session, job)
            return
        rows = sheet.rows
        start = job.processed
        match_on: MatchOn = "employee_id" if job.match_on == "employee_id" else "email"
        if job.status != "running":
            job.status, job.total = "running", len(rows)
            await _progress(session, job)
    for offset in range(start, len(rows), BATCH):
        async with database.tenant_session(context) as session:
            await _batch(session, job_id, importer, rows[offset : offset + BATCH], match_on)
    await _finish(database, tenant, job_id)


async def _batch(
    session: AsyncSession,
    job_id: uuid.UUID,
    importer: uuid.UUID | None,
    rows: list[tuple[int, dict[str, str]]],
    match_on: MatchOn,
) -> None:
    job = await session.get(PeopleImport, job_id, with_for_update=True)
    if job is None:
        raise NotFound
    problems = list(job.problems)
    for number, values in rows:
        try:
            async with session.begin_nested():
                outcome = await apply_row(session, importer, values, match_on)
        except RowProblem as problem:
            job.failed_count += 1
            if len(problems) < MAX_PROBLEMS:
                problems.append({"row": number, "field": problem.field, "code": problem.code})
            continue
        if outcome == "created":
            job.created_count += 1
        else:
            job.updated_count += 1
    job.processed += len(rows)
    job.problems = problems
    await _progress(session, job)


async def _finish(
    database: Database, tenant: uuid.UUID, job_id: uuid.UUID, *, failure: str | None = None
) -> None:
    async with database.tenant_session(TenantContext(tenant)) as session:
        job = await session.get(PeopleImport, job_id, with_for_update=True)
        if job is None or job.status in {"done", "failed"}:
            return
        job.status = "failed" if failure else "done"
        job.failure = failure
        job.content = None  # the file is not kept once read
        job.finished_at = datetime.now(UTC)
        await _progress(session, job)


async def apply_row(
    session: AsyncSession, importer: uuid.UUID | None, values: Mapping[str, str], match_on: MatchOn
) -> Literal["created", "updated"]:
    """Create or update one person from a row; RowProblem when the row cannot be applied."""
    fields, user_type, can_sign_in = await _row_values(session, values)
    key = fields.get(match_on)
    existing = None
    if key:
        column = func.lower(User.email) if match_on == "email" else User.employee_id
        wanted = key.lower() if match_on == "email" else key
        existing = await session.scalar(
            select(User).where(column == wanted, User.deleted_at.is_(None))
        )
    await _suggest_site(session, fields, existing)
    try:
        if existing is None:
            await create_person(
                session,
                fields,
                user_type=user_type or UserType.REQUESTER,
                can_sign_in=bool(fields.get("email")) if can_sign_in is None else can_sign_in,
                source="import",
            )
            return "created"
        person = await update_person(
            session, existing.id, expected_version=existing.version, changes=fields, source="import"
        )
        if user_type is not None and user_type.value != person.user_type:
            person = await set_user_type(
                session, person.id, user_type, expected_version=person.version
            )
        if can_sign_in is not None and can_sign_in != person.can_sign_in:
            await set_sign_in(
                session, importer, person.id, can_sign_in, expected_version=person.version
            )
    except ValidationFailed as invalid:
        first = invalid.errors[0] if invalid.errors else None
        field = first.field.removeprefix("body.") if first else "row"
        raise RowProblem(field, first.code if first else invalid.instance_code) from invalid
    except AppError as refused:  # seat limit, conflicts: the row is refused with the reason
        field = "user_type" if "technician" in refused.instance_code else "row"
        raise RowProblem(field, refused.instance_code) from refused
    return "updated"


async def _suggest_site(
    session: AsyncSession, fields: dict[str, Any], existing: User | None
) -> None:
    """D-096: a department's site fills an empty site; a site in the file or on record stays."""
    department_id = fields.get("department_id")
    if department_id is None or "site_id" in fields:
        return
    if existing is not None and existing.site_id is not None:
        return
    site_id = await department_site(session, department_id)
    if site_id is not None:
        fields["site_id"] = site_id


async def _row_values(  # noqa: C901, PLR0912 - one rule per column, flat
    session: AsyncSession, values: Mapping[str, str]
) -> tuple[dict[str, Any], UserType | None, bool | None]:
    fields: dict[str, Any] = {}
    for name in (
        "first_name",
        "last_name",
        "display_name",
        "email",
        "employee_id",
        "job_title",
        "phone",
        "mobile",
    ):
        if values.get(name):
            fields[name] = values[name]
    if values.get("site"):
        site_id = await find_site(session, values["site"])
        if site_id is None:
            raise RowProblem(field="site_id", code="site_not_found")
        fields["site_id"] = site_id
    if values.get("department"):
        department_id = await find_department(session, values["department"])
        if department_id is None:
            raise RowProblem(field="department_id", code="department_not_found")
        fields["department_id"] = department_id
    if values.get("manager"):
        manager_id = await session.scalar(
            select(User.id).where(
                func.lower(User.email) == values["manager"].lower(), User.deleted_at.is_(None)
            )
        )
        if manager_id is None:
            raise RowProblem(field="manager_id", code="user_not_found")
        fields["manager_id"] = manager_id
    if values.get("vip"):
        vip = flag(values["vip"])
        if vip is None:
            raise RowProblem(field="vip", code="invalid_choice")
        fields["vip"] = vip
    if values.get("locale"):
        locale = values["locale"].lower()
        locale = LANGUAGE_NAMES.get(locale, locale)
        if locale not in LOCALES:
            raise RowProblem(field="locale", code="invalid_choice")
        fields["locale"] = locale
    user_type = None
    if values.get("user_type"):
        try:
            user_type = UserType(values["user_type"].strip().lower())
        except ValueError as exc:
            raise RowProblem(field="user_type", code="invalid_choice") from exc
    can_sign_in = None
    if values.get("can_sign_in"):
        can_sign_in = flag(values["can_sign_in"])
        if can_sign_in is None:
            raise RowProblem(field="can_sign_in", code="invalid_choice")
    return fields, user_type, can_sign_in


async def recent_imports(session: AsyncSession, limit: int = 20) -> list[PeopleImport]:
    """The tenant's latest imports, newest first."""
    rows = await session.scalars(
        select(PeopleImport)
        .where(PeopleImport.deleted_at.is_(None))
        .order_by(PeopleImport.created_at.desc(), PeopleImport.id.desc())
        .limit(limit)
    )
    return list(rows)
