"""Verified e-mail domains' routes (WP-057 S5d, REQ-SEC-010).

`identity.manage`, every write audited; adding, vouching for and removing a domain ask for a
recent sign-in.

- `GET /identity/domains`: the tenant's domains, their state and their last check.
- `POST /identity/domains`: add one (Idempotency-Key). The answer carries the TXT record's name
  and value once; only its hash is kept.
- `POST /identity/domains/{id}/check`: look for the record now (AC1).
- `POST /identity/domains/{id}/verify`: verify without DNS (on-prem and air-gapped installs with
  no DNS to ask), with a reason. If-Match.
- `DELETE /identity/domains/{id}`: remove it, and its routing (If-Match).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import PermissionDenied
from app.core.recent_auth import RecentAuth
from app.modules.audit import AuditNote, audited
from app.modules.identity_access.domain import verified_domains as rules
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.infra.models import VerifiedDomain
from app.modules.identity_access.service import verified_domains as domains
from app.shared.api.concurrency import ExpectedVersion
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/identity/domains",
    tags=["identity"],
    dependencies=[Depends(rate_limit("identity"))],
)
Manage = Annotated[Subject, Depends(require_permission("identity.manage"))]
MANUAL_NOT_ALLOWED = "domain_manual_verify_not_allowed"


def _single_tenant(request: Request) -> None:
    """A manual verify only where one organisation owns the realm (D-098; lane B's #569 review).

    On a multi-tenant installation, an admin vouching for a domain would let their provider take
    every sign-in of it from the shared page: there only the DNS proof counts.
    """
    if request.app.state.settings.multi_tenant:
        raise PermissionDenied(code=MANUAL_NOT_ALLOWED)


class VerifiedDomainOut(BaseModel):
    """A domain as its tenant's admins see it (never the token)."""

    id: uuid.UUID
    domain: str
    state: rules.DomainState
    verified_at: datetime | None
    verified_by_method: Literal["dns", "manual"] | None
    last_checked_at: datetime | None
    last_outcome: str | None = Field(description="Labels: `domain_check.<code>`.")
    failure_count: int
    record_name: str = Field(description="Where the TXT record goes.")
    version: int


class VerifiedDomainAddedOut(VerifiedDomainOut):
    """Just added: the record's value, shown this once."""

    record_value: str


class VerifiedDomainIn(BaseModel):
    """A domain to prove."""

    model_config = ConfigDict(extra="forbid")

    domain: str = Field(max_length=300)


class DomainCheckOut(BaseModel):
    """What a check found (labels: `domain_check.<outcome>`), and the domain now."""

    outcome: str
    domain: VerifiedDomainOut


class DomainManualVerifyIn(BaseModel):
    """Why the domain is verified without DNS (kept in the audit entry)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


def _out(row: VerifiedDomain) -> VerifiedDomainOut:
    return VerifiedDomainOut(
        id=row.id,
        domain=row.domain,
        state=rules.DomainState(row.state),
        verified_at=row.verified_at,
        verified_by_method=row.verified_by_method,  # type: ignore[arg-type]  # a checked code
        last_checked_at=row.last_checked_at,
        last_outcome=row.last_outcome,
        failure_count=row.failure_count,
        record_name=rules.record_name(row.domain),
        version=row.version,
    )


@router.get("", summary="Verified e-mail domains")
async def list_domains(session: TenantSession, subject: Manage) -> list[VerifiedDomainOut]:
    """Every domain of the tenant, by name."""
    del subject
    return [_out(row) for row in await domains.list_domains(session)]


@router.post(
    "",
    summary="Add a domain to verify",
    status_code=201,
    dependencies=[RecentAuth],
    response_model=VerifiedDomainAddedOut,
)
async def add_domain(
    body: VerifiedDomainIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("identity.domain_added", object_type="verified_domain")],
) -> Response:
    """Pending until its TXT record is found; the record's value is in this answer only."""
    del subject

    async def operation() -> Created:
        added = await domains.add(session, body.domain)
        note.object_id = str(added.row.id)
        note.details = {"domain": added.row.domain}
        out = VerifiedDomainAddedOut(
            **_out(added.row).model_dump(), record_value=rules.record_value(added.token)
        )
        return Created(out, {"ETag": f'"{added.row.version}"'})

    return await idempotency.run(body, operation)


@router.post("/{domain_id}/check", summary="Look for the domain's record now")
async def check_domain(
    domain_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    note: Annotated[
        AuditNote,
        audited("identity.domain_checked", object_type="verified_domain", object_param="domain_id"),
    ],
) -> DomainCheckOut:
    """Found: verified (or 409 when another tenant holds it); else the reason, labelled."""
    del subject
    row = await domains.get_domain(session, domain_id)
    outcome = await domains.check(session, row)
    note.details = {"domain": row.domain, "outcome": outcome}
    return DomainCheckOut(outcome=outcome, domain=_out(row))


@router.post(
    "/{domain_id}/verify",
    summary="Verify a domain without DNS (single-tenant installations only)",
    dependencies=[RecentAuth, Depends(_single_tenant)],
)
async def verify_domain(  # noqa: PLR0913, PLR0917 - FastAPI parameters
    domain_id: uuid.UUID,
    body: DomainManualVerifyIn,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    note: Annotated[
        AuditNote,
        audited(
            "identity.domain_verified_manually",
            object_type="verified_domain",
            object_param="domain_id",
        ),
    ],
) -> VerifiedDomainOut:
    """For installations with no DNS to ask: the admin vouches for it, and that is audited."""
    del subject
    row = await domains.get_domain(session, domain_id)
    await domains.verify_manually(session, row, version)
    note.details = {"domain": row.domain, "reason": body.reason}
    return _out(row)


@router.delete(
    "/{domain_id}", summary="Remove a domain", status_code=204, dependencies=[RecentAuth]
)
async def delete_domain(
    domain_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    note: Annotated[
        AuditNote,
        audited("identity.domain_removed", object_type="verified_domain", object_param="domain_id"),
    ],
) -> Response:
    """Its routing goes too (lane B (2)); the SSO set-up stays."""
    del subject
    row = await domains.get_domain(session, domain_id)
    was_verified = await domains.delete(session, row, version)
    note.details = {"domain": row.domain, "was_verified": was_verified}
    return Response(status_code=204)
