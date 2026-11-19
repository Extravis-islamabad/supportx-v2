"""Admin > Vendor support (WP-057 S4c-1, REQ-SEC-045, D-173): grants to named Extravis engineers.

Every route needs `identity.manage`, and the service also requires the tenant admin role (D-173
(1)). Making or extending a grant asks for a recent sign-in; ending one never does (taking
access away must always be easy). Every write is audited.

The one-time password exists only on the out-of-band path and only in this request's own answer:
the answer kept for an Idempotency-Key replay never holds it, and nothing logs it (as API keys,
D-128). The answer is never cached.
"""

import json
import uuid
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission
from app.core.database import TenantSession, after_commit, get_database
from app.core.recent_auth import RecentAuth
from app.core.tenancy import TenantContext
from app.modules.audit import AuditNote, audited
from app.modules.identity_access.domain import support_grants as rules
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.service import support_grants as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit
from app.shared.clock import system_clock
from app.shared.history import source_of

Manage = Annotated[Subject, Depends(require_permission("identity.manage"))]
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}

router = APIRouter(
    prefix="/identity/vendor-support",
    tags=["vendor-support"],
    dependencies=[Depends(rate_limit("identity"))],
)


class SupportGrantOut(BaseModel):
    """A grant as a tenant admin sees it."""

    id: uuid.UUID
    engineer_name: str
    engineer_email: str
    reason: str
    ticket_ref: str | None
    access: Literal["view", "view_and_change"]
    change_reason: str | None
    unmask_personal: bool
    ip_allowlist: list[str]
    starts_at: str
    ends_at: str
    state: Literal["pending_verification", "active", "ended", "revoked"] = Field(
        description="pending_verification reads 'waiting for the engineer' (never 'active')."
    )
    verification: Literal["email", "out_of_band"]
    first_used_at: str | None
    ended_at: str | None
    version: int

    @classmethod
    def of(cls, view: service.GrantView) -> "SupportGrantOut":
        """From the service's view."""
        return cls(
            id=view.id,
            engineer_name=view.engineer_name,
            engineer_email=view.engineer_email,
            reason=view.reason,
            ticket_ref=view.ticket_ref,
            access=cast("Any", view.access),  # the column's check holds these codes
            change_reason=view.change_reason,
            unmask_personal=view.unmask_personal,
            ip_allowlist=view.ip_allowlist,
            starts_at=view.starts_at.isoformat(),
            ends_at=view.ends_at.isoformat(),
            state=cast("Any", view.state),  # the column's check holds these codes
            verification=cast("Any", view.verification),  # the column's check holds these codes
            first_used_at=view.first_used_at.isoformat() if view.first_used_at else None,
            ended_at=view.ended_at.isoformat() if view.ended_at else None,
            version=view.version,
        )


class SupportGrantMadeOut(SupportGrantOut):
    """A new grant; the one-time password only in the first answer, out of band only."""

    delivery: Literal["actions_email", "one_time_password"]
    admin_could_act: bool = Field(
        description="True: the admin held a credential and could have acted as the engineer."
    )
    one_time_password: str | None = Field(
        default=None, description="Shown once, never again; null on a replay and for e-mail."
    )


class SupportGrantIn(BaseModel):
    """A new grant (D-173): who, why, what, how long, from where, how they were verified."""

    model_config = ConfigDict(extra="forbid")

    engineer_name: str = Field(min_length=1, max_length=rules.NAME_MAX)
    engineer_email: str = Field(min_length=3, max_length=320)
    reason: str = Field(min_length=1, max_length=rules.REASON_MAX)
    ticket_ref: str | None = Field(default=None, max_length=rules.TICKET_MAX)
    access: Literal["view", "view_and_change"] = "view"
    change_reason: str | None = Field(default=None, max_length=rules.REASON_MAX)
    unmask_personal: bool = False
    hours: int | None = Field(default=None, ge=1, le=72, description="Default 24.")
    ip_allowlist: list[str] = Field(default_factory=list, max_length=rules.IP_LIST_MAX)
    verification: Literal["email", "out_of_band"] = "email"
    confirmation_note: str | None = Field(default=None, max_length=rules.REASON_MAX)

    def request(self) -> rules.GrantRequest:
        """The domain's request."""
        return rules.GrantRequest(
            engineer_name=self.engineer_name,
            engineer_email=self.engineer_email,
            reason=self.reason,
            ticket_ref=self.ticket_ref,
            access=rules.Access(self.access),
            change_reason=self.change_reason,
            unmask_personal=self.unmask_personal,
            hours=self.hours,
            ip_allowlist=self.ip_allowlist,
            verification=rules.Verification(self.verification),
            confirmation_note=self.confirmation_note,
        )


class SupportGrantExtendIn(BaseModel):
    """More time, never past 72 hours from the start."""

    model_config = ConfigDict(extra="forbid")

    hours: int = Field(ge=1, le=71)


class VendorSupportSettingIn(BaseModel):
    """The tenant's opt-out (D-173 (9))."""

    model_config = ConfigDict(extra="forbid")

    never_allow: bool


class VendorSupportSettingOut(BaseModel):
    """Whether vendor support is allowed here, and the settings' version for If-Match."""

    never_allow: bool
    version: int


@router.get("/grants", summary="Vendor support grants")
async def list_grants(session: TenantSession, subject: Manage) -> list[SupportGrantOut]:
    """Open grants first, then newest first."""
    return [SupportGrantOut.of(v) for v in await service.list_grants(session, subject)]


@router.get("/grants/{grant_id}", summary="A vendor support grant")
async def get_grant(
    grant_id: uuid.UUID, session: TenantSession, subject: Manage, response: Response
) -> SupportGrantOut:
    """404 when there is none."""
    view = await service.get_grant(session, subject, grant_id)
    set_etag(response, view.version)
    return SupportGrantOut.of(view)


@router.post(
    "/grants",
    summary="Grant vendor support access",
    status_code=status.HTTP_201_CREATED,
    response_model=SupportGrantMadeOut,
    dependencies=[RecentAuth],
)
async def create_grant(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: SupportGrantIn,
    request: Request,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[
        AuditNote, audited("identity_access.support_grant_created", object_type="support_grant")
    ],
) -> Response:
    """Make a grant and its temporary account (Idempotency-Key; recent sign-in)."""
    note.skip = True
    password: list[str] = []  # only this request's own answer carries it

    async def go() -> Created:
        made = await service.create_grant(
            session,
            subject,
            body.request(),
            settings=request.app.state.settings,
            admin=getattr(request.app.state, "identity_admin", None),
            now=system_clock.now(),
            source=source_of(request),
        )
        if made.one_time_password is not None:
            password.append(made.one_time_password)
        note.skip = False
        note.object_id = str(made.grant.id)
        # Lane B (11): which grants an admin could have used, readable in the audit.
        note.details = {
            "access": made.grant.access,
            "verification": made.grant.verification,
            "delivery": made.delivery.value,
            "admin_could_act": made.admin_could_act,
        }
        out = SupportGrantMadeOut(
            **SupportGrantOut.of(made.grant).model_dump(),
            delivery=made.delivery.value,
            admin_could_act=made.admin_could_act,
            one_time_password=None,  # the stored answer (for replays) never holds it
        )
        return Created(body=out.model_dump(mode="json"), headers={"ETag": f'"{out.version}"'})

    response = await idempotency.run(body, go, status_code=status.HTTP_201_CREATED)
    answer: dict[str, Any] = json.loads(bytes(response.body))
    if password:
        answer["one_time_password"] = password[0]
    headers = {k: v for k, v in response.headers.items() if k.lower() not in _SKIP} | NO_STORE
    return JSONResponse(answer, status_code=response.status_code, headers=headers)


_SKIP = frozenset({"content-length", "content-type"})


@router.post("/grants/{grant_id}/extend", summary="Extend a grant", dependencies=[RecentAuth])
async def extend_grant(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    grant_id: uuid.UUID,
    body: SupportGrantExtendIn,
    request: Request,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    note: Annotated[
        AuditNote,
        audited(
            "identity_access.support_grant_extended",
            object_type="support_grant",
            object_param="grant_id",
        ),
    ],
) -> SupportGrantOut:
    """More time (If-Match; recent sign-in); never past 72 hours in total."""
    view = await service.extend_grant(
        session,
        subject,
        grant_id,
        expected_version=version,
        extra_hours=body.hours,
        source=source_of(request),
    )
    note.details = {"hours": body.hours, "ends_at": view.ends_at.isoformat()}
    set_etag(response, view.version)
    return SupportGrantOut.of(view)


@router.post("/grants/{grant_id}/revoke", summary="End a grant now")
async def revoke_grant(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    grant_id: uuid.UUID,
    request: Request,
    session: TenantSession,
    subject: Manage,
    response: Response,
    note: Annotated[
        AuditNote,
        audited(
            "identity_access.support_grant_revoked",
            object_type="support_grant",
            object_param="grant_id",
        ),
    ],
) -> SupportGrantOut:
    """Access ends at once (the account is refused in this transaction); idempotent.

    After the commit the sessions end and the Keycloak account is removed; the 30-second
    schedule finishes whatever this could not.
    """
    await service.require_tenant_admin(session, subject)
    ended = await service.end_grant(
        session,
        grant_id,
        tenant_id=subject.tenant_id,
        revoked_by=subject.user_id,
        now=system_clock.now(),
        source=source_of(request),
    )
    if ended is None:
        note.details = {"already_ended": True}
    else:
        _finish_after_commit(session, request, ended)
    view = await service.get_grant(session, subject, grant_id)
    set_etag(response, view.version)
    return SupportGrantOut.of(view)


def _finish_after_commit(session: AsyncSession, request: Request, ended: service.Ended) -> None:
    """Sessions and the Keycloak account, once the revoke is committed.

    Best effort: the schedule's sweep is the backstop.
    """
    auth = getattr(request.app.state, "auth", None)
    admin = getattr(request.app.state, "identity_admin", None)
    database = get_database(request)

    async def end_sessions(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        if auth is not None:
            await auth.end_sessions(tenant_id, user_id)

    async def finish() -> None:
        error = await service.finish_end(ended, end_sessions=end_sessions, admin=admin)
        async with database.tenant_session(TenantContext(ended.tenant_id)) as fresh:
            await service.record_removal(fresh, ended.grant_id, error=error, now=system_clock.now())

    after_commit(session, finish)


@router.get("/setting", summary="Whether vendor support is allowed")
async def get_setting(session: TenantSession, subject: Manage) -> VendorSupportSettingOut:
    """The opt-out and the settings' version."""
    await service.require_tenant_admin(session, subject)
    never, version = await service.setting(session)
    return VendorSupportSettingOut(never_allow=never, version=version)


@router.put("/setting", summary="Never allow vendor support", dependencies=[RecentAuth])
async def put_setting(
    body: VendorSupportSettingIn,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    note: Annotated[
        AuditNote,
        audited("identity_access.vendor_support_setting_changed", object_type="identity_settings"),
    ],
) -> VendorSupportSettingOut:
    """On: no grant can be made, refused while one is open (If-Match; recent sign-in)."""
    saved = await service.set_never_allow(
        session, subject, never_allow=body.never_allow, expected_version=version
    )
    note.details = {"never_allow": body.never_allow}
    return VendorSupportSettingOut(never_allow=body.never_allow, version=saved)
