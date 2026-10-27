"""People administration over HTTP (WP-021; REQ-ADM-002..005; D-073, D-092). No logic here.

`/users/...` adds to the WP-008 directory: add a person, change the person record, technician or
requester, sign-in, deactivate and reactivate. Imports live at `/people-imports` and the
technician-visibility question at `/access-settings`. Writes are audited, changes send If-Match,
creates take an Idempotency-Key.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail, ValidationFailed
from app.modules.audit import AuditNote, audited
from app.modules.identity_access.api.routes import UserDetail
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.people_import import MAX_FILE_BYTES
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.infra.models import PeopleImport
from app.modules.identity_access.service import access_settings, people, people_import
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission, or no technician seat."},
    404: {"model": ProblemDetail, "description": "No such person or import."},
    409: {"model": ProblemDetail, "description": "Stale If-Match (says who changed what)."},
    422: {"model": ProblemDetail, "description": "Problems by field."},
}
RATE = [Depends(rate_limit("users"))]
Manage = Annotated[Subject, Depends(require_permission("users.manage"))]


def _session_ender(
    request: Request, subject: Manage
) -> Callable[[uuid.UUID], Awaitable[None]] | None:
    """Ends a person's sessions (after commit); None where sign-in is not configured (tests)."""
    auth = getattr(request.app.state, "auth", None)
    if auth is None:
        return None

    async def end(user_id: uuid.UUID) -> None:
        await auth.end_sessions(subject.tenant_id, user_id)

    return end


EndSessions = Annotated[Callable[[uuid.UUID], Awaitable[None]] | None, Depends(_session_ender)]


class PersonFields(BaseModel):
    """The person record (REQ-ADM-002). Lengths are checked by the service, with the limit."""

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = Field(
        default=None, description="Own display name; null: 'first last'."
    )
    email: str | None = Field(default=None, description="Needed to sign in; optional otherwise.")
    employee_id: str | None = None
    job_title: str | None = None
    description: str | None = None
    phone: str | None = None
    mobile: str | None = None
    vip: bool | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    locale: Literal["en", "ar", "ur"] | None = None
    time_zone: str | None = None
    request_visibility: Literal["site"] | None = Field(
        default=None, description="Portal: null = the tenant's rule; site = all of their site."
    )


class PersonIn(PersonFields):
    """A new person: requester or technician (takes a seat), may sign in or is a contact."""

    first_name: str  # required when adding
    user_type: UserType = UserType.REQUESTER
    can_sign_in: bool = Field(default=True, description="False: a contact (no sign-in).")


people_router = APIRouter(prefix="/users", tags=["users"], dependencies=RATE, responses=RESPONSES)


@people_router.post(
    "",
    summary="Add a person",
    status_code=status.HTTP_201_CREATED,
    response_model=UserDetail,
    responses={201: {"model": UserDetail, "description": "Created (or replayed)."}},
)
async def create_person(
    body: PersonIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("user.created", object_type="user")],
) -> Response:
    """Before their first sign-in, which links them by email (D-092)."""
    note.skip = True

    async def operation() -> Created:
        values = body.model_dump(
            include=body.model_fields_set - {"user_type", "can_sign_in"} | {"first_name"}
        )
        person = await people.create_person(
            session, values, user_type=body.user_type, can_sign_in=body.can_sign_in
        )
        note.skip = False
        note.object_id = str(person.id)
        note.details = {"user_type": body.user_type.value}
        return Created(UserDetail.of(person, subject), {"ETag": f'"{person.version}"'})

    return await idempotency.run(body, operation)


@people_router.patch(
    "/{user_id}/person",
    summary="Change a person's record",
    dependencies=[audited("user.changed", object_type="user", object_param="user_id")],
)
async def update_person(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    body: PersonFields,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
    request: Request,
) -> UserDetail:
    """Only the fields sent change; a stale If-Match gets an explained 409."""
    person = await people.update_person(
        session,
        user_id,
        expected_version=version,
        changes=body.model_dump(include=body.model_fields_set),
        source=source_of(request),
    )
    set_etag(response, person.version)
    return UserDetail.of(person, subject)


class TypeIn(BaseModel):
    """Technician (takes a licence seat) or requester."""

    model_config = ConfigDict(extra="forbid")

    user_type: UserType


@people_router.put(
    "/{user_id}/type",
    summary="Make a person a technician or a requester",
    dependencies=[audited("user.type_changed", object_type="user", object_param="user_id")],
)
async def set_type(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    body: TypeIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
) -> UserDetail:
    """403 `technician_limit_reached` when no seat is left; a tenant admin stays a technician."""
    person = await people.set_user_type(session, user_id, body.user_type, expected_version=version)
    set_etag(response, person.version)
    return UserDetail.of(person, subject)


class SignInIn(BaseModel):
    """Allow or stop sign-in."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool


@people_router.put(
    "/{user_id}/sign-in",
    summary="Allow or stop a person's sign-in",
    dependencies=[audited("user.sign_in_changed", object_type="user", object_param="user_id")],
)
async def set_sign_in(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    body: SignInIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
    end_sessions: EndSessions,
) -> UserDetail:
    """Allowing needs an email address; stopping ends their sessions at once."""
    person = await people.set_sign_in(
        session,
        subject.user_id,
        user_id,
        body.allowed,
        expected_version=version,
        end_sessions=end_sessions,
    )
    set_etag(response, person.version)
    return UserDetail.of(person, subject)


@people_router.post(
    "/{user_id}/deactivate",
    summary="Deactivate a person",
    dependencies=[audited("user.deactivated", object_type="user", object_param="user_id")],
)
async def deactivate(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
    end_sessions: EndSessions,
) -> UserDetail:
    """They cannot sign in (sessions end now); records, roles and groups are kept."""
    person = await people.deactivate(
        session, subject.user_id, user_id, expected_version=version, end_sessions=end_sessions
    )
    set_etag(response, person.version)
    return UserDetail.of(person, subject)


class ReactivationOut(BaseModel):
    """What a deactivated person still holds; the admin confirms what they keep."""

    role_ids: list[uuid.UUID]
    group_ids: list[uuid.UUID]


@people_router.get("/{user_id}/reactivation", summary="What reactivating would keep")
async def reactivation(
    user_id: uuid.UUID, session: TenantSession, subject: Manage
) -> ReactivationOut:
    """The roles and groups the person still has."""
    del subject
    found = await people.reactivation(session, user_id)
    return ReactivationOut(role_ids=found.role_ids, group_ids=found.group_ids)


class ReactivateIn(BaseModel):
    """The roles and groups to keep; the others are removed."""

    model_config = ConfigDict(extra="forbid")

    keep_role_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    keep_group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


@people_router.post(
    "/{user_id}/reactivate",
    summary="Reactivate a person",
    dependencies=[audited("user.reactivated", object_type="user", object_param="user_id")],
)
async def reactivate(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    user_id: uuid.UUID,
    body: ReactivateIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
) -> UserDetail:
    """A technician takes a seat again (403 when none is left)."""
    person = await people.reactivate(
        session,
        user_id,
        expected_version=version,
        keep_role_ids=body.keep_role_ids,
        keep_group_ids=body.keep_group_ids,
    )
    set_etag(response, person.version)
    return UserDetail.of(person, subject)


# --- imports --------------------------------------------------------------------------------------


class ImportProblem(BaseModel):
    """One refused row: its number in the file, the column and the reason code."""

    row: int | None
    field: str | None
    code: str
    detail: str | None = None


class ImportOut(BaseModel):
    """A people import and how far it got. Updates live (`people_imports.changed`)."""

    id: uuid.UUID
    file_name: str
    file_format: Literal["csv", "xlsx"]
    status: Literal["queued", "running", "done", "failed"]
    match_on: Literal["email", "employee_id"]
    total: int
    processed: int
    created_count: int
    updated_count: int
    failed_count: int
    problems: list[ImportProblem]
    failure: str | None
    created_at: datetime
    finished_at: datetime | None


def _import_out(job: PeopleImport) -> ImportOut:
    return ImportOut.model_validate(job, from_attributes=True)


imports_router = APIRouter(
    prefix="/people-imports", tags=["users"], dependencies=RATE, responses=RESPONSES
)


class ImportTarget(BaseModel):
    """The Idempotency-Key fingerprint of an upload."""

    name: str
    match_on: str
    size: int


@imports_router.post(
    "",
    summary="Import people from a CSV or Excel file",
    status_code=status.HTTP_201_CREATED,
    response_model=ImportOut,
    responses={201: {"model": ImportOut, "description": "Queued (or replayed)."}},
)
async def start_import(  # noqa: PLR0913 - the upload's facts, explicit
    *,
    request: Request,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("people.import_started", object_type="people_import")],
    name: Annotated[str, Query(min_length=1, max_length=255)],
    match_on: Annotated[Literal["email", "employee_id"], Query()] = "email",
) -> Response:
    """The raw file as the body (up to 5 MB, 5,000 rows); it is processed in the background."""
    del subject
    content = bytearray()
    async for piece in request.stream():
        content += piece
        if len(content) > MAX_FILE_BYTES:
            raise ValidationFailed(code="people_import_file_too_large")
    note.skip = True
    target = ImportTarget(name=name, match_on=match_on, size=len(content))

    async def operation() -> Created:
        job = await people_import.start_import(session, name, bytes(content), match_on)
        note.skip = False
        note.object_id = str(job.id)
        note.details = {"rows_file_bytes": len(content), "match_on": match_on}
        return Created(_import_out(job))

    return await idempotency.run(target, operation)


@imports_router.get("", summary="Recent people imports")
async def list_imports(session: TenantSession, subject: Manage) -> list[ImportOut]:
    """The last 20, newest first."""
    del subject
    return [_import_out(job) for job in await people_import.recent_imports(session)]


@imports_router.get("/{import_id}", summary="One people import")
async def get_import(import_id: uuid.UUID, session: TenantSession, subject: Manage) -> ImportOut:
    """Its progress and refused rows."""
    del subject
    return _import_out(await people_import.ImportRepository(session).get(import_id))


# --- access settings (D-073) ----------------------------------------------------------------------


class AccessSettingsOut(BaseModel):
    """What the built-in technician role sees. `answered_at` null: not asked yet (first run)."""

    technician_scope: Literal["group", "all"]
    answered_at: datetime | None
    version: int = Field(description="Send back as If-Match; 0 until first saved.")


class AccessSettingsIn(BaseModel):
    """The answer: group (their groups, their own, their sites' unassigned) or all."""

    model_config = ConfigDict(extra="forbid")

    technician_scope: Literal["group", "all"]


access_router = APIRouter(
    prefix="/access-settings", tags=["access"], dependencies=RATE, responses=RESPONSES
)
ManageRoles = Annotated[Subject, Depends(require_permission("roles.manage"))]


@access_router.get("", summary="Technician visibility")
async def get_access(session: TenantSession, subject: ManageRoles) -> AccessSettingsOut:
    """The tenant's answer, or the default "group" with `answered_at` null."""
    del subject
    found = await access_settings.get_access_settings(session)
    return AccessSettingsOut(**found.__dict__)


@access_router.put(
    "",
    summary="Answer or change technician visibility",
    dependencies=[audited("access.settings_changed", object_type="tenant")],
)
async def put_access(
    body: AccessSettingsIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: ManageRoles,
) -> AccessSettingsOut:
    """Applies to every technician at once (their screens refresh)."""
    del subject
    saved = await access_settings.save_access_settings(
        session, technician_scope=body.technician_scope, expected_version=version
    )
    set_etag(response, saved.version)
    return AccessSettingsOut(**saved.__dict__)
