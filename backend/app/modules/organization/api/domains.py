"""Custom domains API (WP-017, REQ-PRT-016 AC3, REQ-SEC-004).

`branding.manage`: list, add (Idempotency-Key), check now, upload a certificate (If-Match),
remove (If-Match); each change audited (`domain.*`). Public: the proof a domain check fetches.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import public_route, require_permission
from app.core.database import TenantSession
from app.core.entitlements import entitlement_exempt
from app.core.errors import ProblemDetail, ServiceUnavailable
from app.modules.audit import AuditNote, audited
from app.modules.organization.api.branding import Files
from app.modules.organization.domain.domains import DomainStatus, TlsMode, TlsStatus, proof
from app.modules.organization.infra.domain_check import fetch_answer
from app.modules.organization.service import domains
from app.modules.organization.service.email_branding import tenant_origin
from app.modules.organization.service.file_access import MANAGE
from app.modules.organization.service.tenants import get_current_tenant
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

Manage = Annotated[Any, Depends(require_permission(MANAGE))]

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission."},
    404: {"model": ProblemDetail, "description": "No such domain."},
}


class DomainOut(BaseModel):
    """A custom domain, its proof of ownership and its certificate."""

    id: uuid.UUID
    host: str
    status: DomainStatus
    check_url: str = Field(description="What SupportX fetches to verify the domain.")
    verified_at: datetime | None
    checked_at: datetime | None
    failure_code: str | None = Field(description="Why the last check failed (labels: errors.*).")
    tls_mode: TlsMode
    tls_status: TlsStatus
    certificate_not_after: datetime | None
    version: int


class DomainsOut(BaseModel):
    """The tenant's addresses: its subdomain (when the installation has them) and its domains."""

    subdomain: str | None
    point_to: str = Field(description="Where a custom domain must point (CNAME target).")
    items: list[DomainOut]


class DomainIn(BaseModel):
    """A host name, e.g. help.example.com."""

    host: str = Field(min_length=4, max_length=253)


class CertificateIn(BaseModel):
    """PEM certificate chain (the host's certificate first) and its unencrypted private key."""

    certificate_pem: str = Field(min_length=100, max_length=65536)
    private_key_pem: str = Field(min_length=100, max_length=16384)


def _out(view: domains.DomainView) -> DomainOut:
    return DomainOut(
        id=view.id,
        host=view.host,
        status=view.status,
        check_url=view.check_url,
        verified_at=view.verified_at,
        checked_at=view.checked_at,
        failure_code=view.failure_code,
        tls_mode=view.tls_mode,
        tls_status=view.tls_status,
        certificate_not_after=view.certificate_not_after,
        version=view.version,
    )


def _secret(request: Request) -> bytes:
    secret = request.app.state.settings.session_secret
    if secret is None:
        raise ServiceUnavailable(code="domains_not_configured")
    return bytes(secret.get_secret_value(), "utf-8")


router = APIRouter(
    prefix="/organization/domains",
    tags=["organization"],
    dependencies=[Depends(rate_limit("organization"))],
    responses=RESPONSES,
)


@router.get("", summary="Your addresses")
async def list_domains(request: Request, session: TenantSession, subject: Manage) -> DomainsOut:
    """The subdomain and every custom domain, with their state."""
    del subject
    settings = request.app.state.settings
    tenant = await get_current_tenant(session)
    origin = tenant_origin(settings, tenant.slug)
    host = origin.split("://", 1)[1]
    return DomainsOut(
        subdomain=host if settings.tenant_base_domain else None,
        point_to=host.split(":", 1)[0],
        items=[_out(view) for view in await domains.list_domains(session)],
    )


@router.post(
    "",
    summary="Add a custom domain",
    status_code=status.HTTP_201_CREATED,
    response_model=DomainOut,
    responses={409: {"model": ProblemDetail, "description": "Already used, or too many."}},
)
async def add_domain(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: DomainIn,
    request: Request,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("domain.added", object_type="domain")],
) -> Response:
    """Add a host; it resolves to your tenant once checked (Idempotency-Key supported)."""
    note.skip = True  # a replay creates nothing

    async def operation() -> Created:
        created = _out(
            await domains.add_domain(
                session, subject.tenant_id, body.host, request.app.state.settings.tenant_base_domain
            )
        )
        note.skip = False
        note.object_id = str(created.id)
        return Created(created, {"ETag": f'"{created.version}"'})

    return await idempotency.run(body, operation)


@router.post("/{domain_id}/verify", summary="Check a custom domain now")
async def verify_domain(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    domain_id: uuid.UUID,
    request: Request,
    response: Response,
    session: TenantSession,
    subject: Manage,
    note: Annotated[
        AuditNote, audited("domain.verified", object_type="domain", object_param="domain_id")
    ],
) -> DomainOut:
    """Fetch the proof from the domain: verified when it answers like this installation."""
    del subject
    view = await domains.verify_domain(
        session,
        domain_id,
        secret=_secret(request),
        fetch=fetch_answer,
        certificates_managed=request.app.state.settings.domain_certificates_managed,
    )
    note.skip = view.status != DomainStatus.VERIFIED
    note.details = {"status": view.status.value}
    set_etag(response, view.version)
    return _out(view)


@router.put(
    "/{domain_id}/certificate",
    summary="Use your own certificate",
    responses={409: {"model": ProblemDetail}, 422: {"model": ProblemDetail}},
)
async def upload_certificate(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    domain_id: uuid.UUID,
    body: CertificateIn,
    response: Response,
    session: TenantSession,
    subject: Manage,
    files: Files,
    version: ExpectedVersion,
    note: Annotated[
        AuditNote,
        audited("domain.certificate_uploaded", object_type="domain", object_param="domain_id"),
    ],
) -> DomainOut:
    """Checked (key matches, names the host, valid now), then stored with the key encrypted."""
    del subject
    _, keyring = files.require_storage()
    view = await domains.upload_certificate(
        session,
        domain_id,
        keyring=keyring,
        chain_pem=body.certificate_pem,
        key_pem=body.private_key_pem,
        expected_version=version,
    )
    note.details = {
        "not_after": view.certificate_not_after.isoformat() if view.certificate_not_after else None
    }
    set_etag(response, view.version)
    return _out(view)


@router.delete(
    "/{domain_id}",
    summary="Remove a custom domain",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[audited("domain.removed", object_type="domain", object_param="domain_id")],
)
async def remove_domain(
    domain_id: uuid.UUID, session: TenantSession, subject: Manage, version: ExpectedVersion
) -> Response:
    """It stops resolving to your tenant at once."""
    del subject
    await domains.remove_domain(session, domain_id, version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


public_router = APIRouter(prefix="/public/domain-check", tags=["organization"])


@public_router.get(
    "/{token}",
    summary="Domain proof",
    response_class=Response,
    responses={200: {"content": {"text/plain": {}}}},
)
@entitlement_exempt
@public_route
async def domain_proof(token: str, request: Request) -> Response:
    """The installation's answer for a token (no lookup: only this installation can compute it)."""
    if len(token) > 64:  # noqa: PLR2004 - tokens are 32 characters
        token = token[:64]
    return Response(
        proof(_secret(request), token),
        media_type="text/plain",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
