"""Custom domains (WP-017, REQ-PRT-016 AC3, REQ-SEC-004; D-090).

A tenant adds a host, points it at this installation, and asks SupportX to check it; only verified
hosts resolve to the tenant (`hosts.tenant_for_host`). Certificates: `automatic` waits for the
platform (cert-manager; D-090 open question on who provisions), `uploaded` stores the tenant's own
certificate with its key encrypted under the tenant's data key (files key ring).

Each change writes `organization.domain.changed` to the outbox; the routes audit it.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.organization.domain.domains import (
    CHECK_PATH,
    DomainProblem,
    DomainStatus,
    TlsMode,
    TlsStatus,
    check_certificate,
    normalise_domain,
    proof_matches,
)
from app.modules.organization.events import DomainChanged
from app.modules.organization.infra.domain_check import DomainCheckError
from app.modules.organization.infra.models import TenantDomain
from app.shared.events import record_event
from app.shared.files.service.core import current_data_key

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.shared.files.keyring import KeyRing

# Fetches the answer a host gives for a token (infra/domain_check.fetch_answer; tests fake it).
Fetcher = Callable[[str, str], Awaitable[str]]
MAX_DOMAINS = 20
NONCE_BYTES = 12


@dataclass(frozen=True)
class DomainView:
    """One custom domain as the screen shows it."""

    id: uuid.UUID
    host: str
    status: DomainStatus
    verify_token: str
    verified_at: datetime | None
    checked_at: datetime | None
    failure_code: str | None
    tls_mode: TlsMode
    tls_status: TlsStatus
    certificate_not_after: datetime | None
    version: int

    @property
    def check_url(self) -> str:
        """What SupportX fetches to verify the domain."""
        return f"http://{self.host}{CHECK_PATH}{self.verify_token}"


def _view(row: TenantDomain) -> DomainView:
    return DomainView(
        id=row.id,
        host=row.host,
        status=DomainStatus(row.status),
        verify_token=row.verify_token,
        verified_at=row.verified_at,
        checked_at=row.checked_at,
        failure_code=row.failure_code,
        tls_mode=TlsMode(row.tls_mode),
        tls_status=TlsStatus(row.tls_status),
        certificate_not_after=row.certificate_not_after,
        version=row.version,
    )


def _invalid(*, field: str, code: str) -> ValidationFailed:
    from app.core.errors import FieldError  # noqa: PLC0415 - one constructor, kept local

    return ValidationFailed(
        errors=[FieldError(field=field, code=code, message_key=f"errors.field.{code}")]
    )


async def list_domains(session: AsyncSession) -> list[DomainView]:
    """The tenant's custom domains, by host."""
    rows = await session.scalars(
        select(TenantDomain).where(TenantDomain.deleted_at.is_(None)).order_by(TenantDomain.host)
    )
    return [_view(row) for row in rows]


async def _row(session: AsyncSession, domain_id: uuid.UUID) -> TenantDomain:
    row = await session.scalar(
        select(TenantDomain).where(TenantDomain.id == domain_id, TenantDomain.deleted_at.is_(None))
    )
    if row is None:
        raise NotFound(code="domain_not_found")
    return row


async def _changed(session: AsyncSession, row: TenantDomain, change: str) -> None:
    await record_event(
        session,
        DomainChanged(domain_id=row.id, change=change),  # type: ignore[arg-type]  # Literal checked by pydantic
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def add_domain(
    session: AsyncSession, tenant_id: uuid.UUID, host: str, base_domain: str | None
) -> DomainView:
    """A new pending domain (409 `domain_taken` when any tenant already has it)."""
    try:
        name = normalise_domain(host, base_domain)
    except DomainProblem as exc:
        raise _invalid(field="host", code=exc.code) from exc
    if len(await list_domains(session)) >= MAX_DOMAINS:
        raise Conflict(code="domain_limit", params={"max": MAX_DOMAINS})
    row = TenantDomain(tenant_id=tenant_id, host=name, verify_token=secrets.token_urlsafe(24))
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict(code="domain_taken") from exc
    await _changed(session, row, "added")
    return _view(row)


async def verify_domain(
    session: AsyncSession,
    domain_id: uuid.UUID,
    *,
    secret: bytes,
    fetch: Fetcher,
    certificates_managed: bool,
) -> DomainView:
    """Fetch the proof now: verified on a correct answer, else failed with the reason."""
    row = await _row(session, domain_id)
    now = datetime.now(UTC)
    try:
        answer = await fetch(row.host, row.verify_token)
        code = None if proof_matches(secret, row.verify_token, answer) else "domain_wrong_answer"
    except DomainCheckError as exc:
        code = exc.code
    row.checked_at = now
    row.failure_code = code
    was_verified = row.status == DomainStatus.VERIFIED
    if code is None:
        row.status = DomainStatus.VERIFIED
        row.verified_at = row.verified_at or now
        if row.tls_mode == TlsMode.AUTOMATIC and row.tls_status == TlsStatus.WAITING:
            row.tls_status = TlsStatus.PENDING if certificates_managed else TlsStatus.NOT_MANAGED
    elif not was_verified:
        row.status = DomainStatus.FAILED
    row.version += 1
    await session.flush()
    if code is None and not was_verified:
        await _changed(session, row, "verified")
    elif code is not None and not was_verified:
        await _changed(session, row, "failed")
    return _view(row)


async def upload_certificate(  # noqa: PLR0913 - which domain, the files' key ring, the PEMs, the version
    session: AsyncSession,
    domain_id: uuid.UUID,
    *,
    keyring: KeyRing,
    chain_pem: str,
    key_pem: str,
    expected_version: int,
) -> DomainView:
    """Use the tenant's own certificate for this domain (on-prem single node)."""
    row = await _row(session, domain_id)
    if row.version != expected_version:
        raise Conflict(code="version_conflict", params={"current_version": row.version})
    try:
        checked = check_certificate(chain_pem, key_pem, row.host, datetime.now(UTC))
    except DomainProblem as exc:
        raise _invalid(field="certificate", code=exc.code) from exc
    key_id, data_key = await current_data_key(session, keyring)
    nonce = secrets.token_bytes(NONCE_BYTES)
    sealed = AESGCM(data_key).encrypt(nonce, checked.key_pem, f"domain:{row.id}".encode())
    row.certificate_pem = checked.chain_pem
    row.private_key = nonce + sealed
    row.private_key_key_id = key_id
    row.certificate_not_after = checked.not_after
    row.certificate_error = None
    row.tls_mode = TlsMode.UPLOADED
    row.tls_status = TlsStatus.ISSUED
    row.version += 1
    await session.flush()
    await _changed(session, row, "certificate")
    return _view(row)


async def remove_domain(
    session: AsyncSession, domain_id: uuid.UUID, expected_version: int
) -> DomainView:
    """Stop using the domain at once (soft delete; its host can be added again later)."""
    row = await _row(session, domain_id)
    if row.version != expected_version:
        raise Conflict(code="version_conflict", params={"current_version": row.version})
    row.deleted_at = datetime.now(UTC)
    row.version += 1
    await session.flush()
    await _changed(session, row, "removed")
    return _view(row)
