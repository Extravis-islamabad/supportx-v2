"""Verified e-mail domains (WP-057 S5d, REQ-SEC-010; lane B's and the coordinator's conditions).

A tenant admin adds a domain and gets a token, shown once. They publish it as a TXT record, and
the domain becomes verified when a check finds it (AC1). Only one tenant can hold a domain
verified (AC2): the partial unique index decides, and a conflicting verify gets 409
`domain_verified_elsewhere`, naming no tenant.

- **The lookup** goes through `resolver`, a port (`lookup(name) -> TXT strings`). It raises
  `DnsUnreachable` when DNS can't be asked; that's a labelled outcome of its own, never "not
  found". The installed lookup is dnspython on the installation's own resolver (D-183,
  `infra/dns_txt.py`: resolv.conf, never a public resolver; bounded). A host with no resolver
  configured says automatic checking isn't possible (`dns_check_unavailable`, never a failure
  that counts towards a lapse), and on a single-tenant installation (on-prem, air-gapped) a
  tenant admin can verify by hand (recent sign-in, a reason, audited). A domain
  verified by hand is not re-checked by DNS there; on a multi-tenant installation it is, like any
  other (`rules.scheduled`).
- **Keycloak follows our database** (lane B (1)): a verify or un-verify raises
  `VerifiedDomainChanged`, and its consumer marks the organisation's domain verified, or removes it
  (lane B (2)). If Keycloak refuses (another organisation holds it), the domain goes back to
  pending with `domain_verified_elsewhere`. A daily reconciler logs any drift and repairs it from
  our rows.
- **The schedule** checks pending domains daily for 7 days and verified ones every 30 days. A
  verified domain lapses only after 3 failed checks over at least 72 hours (lane B (3)); the
  tenant's admins are told.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import SESSION_TENANT_KEY, Database
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain import verified_domains as rules
from app.modules.identity_access.domain.verified_domains import (
    DnsCheckUnavailable,
    DnsUnreachable,
    DomainState,
)
from app.modules.identity_access.events import VerifiedDomainChanged
from app.modules.identity_access.infra import dns_txt
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminRefused,
    KeycloakAdmin,
    Organization,
)
from app.modules.identity_access.infra.models import VerifiedDomain
from app.shared.clock import system_clock
from app.shared.events import ConsumerSpec, EventEnvelope, record_event
from app.shared.history import stale_version

log = get_logger(__name__)

TxtLookup = Callable[[str], Awaitable[list[str]]]
TXT_ANSWERS_MAX = 20  # lane B (4): a capped read
ELSEWHERE = "domain_verified_elsewhere"
FOUND = "found"
NOT_FOUND = "not_found"
UNREACHABLE = "dns_unreachable"
UNAVAILABLE = "dns_check_unavailable"  # no resolver configured (an air-gapped host without DNS)
TOO_MANY = "domains_too_many"


async def _no_resolver(name: str) -> list[str]:
    del name
    raise DnsCheckUnavailable


# The TXT lookup: dnspython on the installation's own resolver (D-183, infra/dns_txt.py); tests
# swap it for a fake, and tests/conftest.py makes sure none of them ever asks real DNS.
resolver: TxtLookup = dns_txt.lookup
admin_factory: Callable[[Settings], IdentityAdmin | None] = KeycloakAdmin.from_settings


def _tenant(session: AsyncSession) -> TenantContext:
    context: TenantContext = session.info[SESSION_TENANT_KEY]
    return context


Change = Literal["added", "checked", "verified", "unverified", "lapsed", "deleted", "refused"]


async def _changed(session: AsyncSession, row: VerifiedDomain, change: Change) -> None:
    await record_event(
        session,
        VerifiedDomainChanged(domain_id=row.id, change=change),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


def _invalid(code: str) -> ValidationFailed:
    return ValidationFailed(
        errors=[FieldError(field="body.domain", code=code, message_key=f"errors.field.{code}")]
    )


@dataclass(frozen=True)
class Added:
    """A new domain and its token, shown this once."""

    row: VerifiedDomain
    token: str


async def list_domains(session: AsyncSession) -> list[VerifiedDomain]:
    """The tenant's domains, by name."""
    return list(
        await session.scalars(
            select(VerifiedDomain)
            .where(VerifiedDomain.deleted_at.is_(None))
            .order_by(VerifiedDomain.domain)
        )
    )


async def get_domain(session: AsyncSession, domain_id: uuid.UUID) -> VerifiedDomain:
    """One of the tenant's domains (404 for another tenant's or a deleted one)."""
    row = await session.get(VerifiedDomain, domain_id)
    if row is None or row.deleted_at is not None:
        raise NotFound(code="domain_not_found")
    return row


async def add(session: AsyncSession, raw: str) -> Added:
    """Add a domain (pending) with a new token; a re-add of a deleted one makes a new token."""
    try:
        domain = rules.normalise(raw)
    except rules.DomainProblem as problem:
        raise _invalid(problem.code) from None
    if len(await list_domains(session)) >= rules.MAX_DOMAINS:
        raise _invalid(TOO_MANY)
    token = rules.new_token()
    row = VerifiedDomain(
        tenant_id=_tenant(session).tenant_id,
        domain=domain,
        state=DomainState.PENDING.value,
        token_digest=token.digest,
    )
    await session.flush()  # anything pending first, outside the savepoint
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        raise Conflict(code="domain_already_added") from None
    await _changed(session, row, "added")
    return Added(row, token.value)


async def _lookup(domain: str) -> list[str] | str:
    """The TXT strings at `_supportx.<domain>` (at most 20), or why there are none to read."""
    try:
        found = await resolver(rules.record_name(domain))
    except DnsCheckUnavailable:
        return UNAVAILABLE
    except DnsUnreachable:
        return UNREACHABLE
    return found[:TXT_ANSWERS_MAX]


async def _verify(session: AsyncSession, row: VerifiedDomain, method: str, now: datetime) -> str:
    """Mark verified; when another tenant holds the domain verified (AC2), it stays pending."""
    await session.flush()  # anything pending first, outside the savepoint
    try:
        # The change is made inside the savepoint, so the unique index's refusal undoes only it.
        async with session.begin_nested():
            row.state = DomainState.VERIFIED.value
            row.verified_at, row.verified_by_method = now, method
            row.failing_since, row.failure_count = None, 0
            row.last_outcome = FOUND
            await session.flush()
    except IntegrityError:
        # The savepoint rolled back and expired the row: read it again before marking it.
        await session.refresh(row)
        row.last_checked_at, row.last_outcome = now, ELSEWHERE
        await session.flush()
        await _changed(session, row, "checked")
        return ELSEWHERE
    await _changed(session, row, "verified")
    return FOUND


async def check(session: AsyncSession, row: VerifiedDomain, *, now: datetime | None = None) -> str:
    """Look for the record now; the outcome code (found, not_found, dns_unreachable, ...)."""
    at = now or system_clock.now()
    texts = await _lookup(row.domain)
    row.last_checked_at = at
    if not isinstance(texts, str) and rules.proves(texts, row.token_digest):
        if row.state == DomainState.VERIFIED.value:
            row.failing_since, row.failure_count, row.last_outcome = None, 0, FOUND
            await session.flush()
            await _changed(session, row, "checked")
            return FOUND
        return await _verify(session, row, "dns", at)
    outcome = texts if isinstance(texts, str) else NOT_FOUND
    row.last_outcome = outcome
    # No lookup installed says nothing about the record: it never counts towards a lapse.
    if row.state == DomainState.VERIFIED.value and outcome != UNAVAILABLE:
        row.failure_count += 1
        row.failing_since = row.failing_since or at
        if rules.lapses(row.failure_count, row.failing_since, at):
            row.state = DomainState.LAPSED.value
            await session.flush()
            await _changed(session, row, "lapsed")
            return outcome
    await session.flush()
    await _changed(session, row, "checked")
    return outcome


async def verify_manually(session: AsyncSession, row: VerifiedDomain, expected_version: int) -> str:
    """A tenant admin's verify without DNS (on-prem / air-gapped); the route audits the reason."""
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    if row.state == DomainState.VERIFIED.value:
        return FOUND
    outcome = await _verify(session, row, "manual", system_clock.now())
    if outcome == ELSEWHERE:
        raise Conflict(code=ELSEWHERE)
    return outcome


async def delete(session: AsyncSession, row: VerifiedDomain, expected_version: int) -> bool:
    """Soft-delete; whether it was verified (its routing goes too, through the outbox)."""
    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)
    was_verified = row.state == DomainState.VERIFIED.value
    row.deleted_at = system_clock.now()
    await session.flush()
    await _changed(session, row, "unverified" if was_verified else "deleted")
    return was_verified


# --- Keycloak follows our rows (lane B (1), (2)) ------------------------------------------------


async def _organization_domains(
    session: AsyncSession, admin: IdentityAdmin
) -> tuple[Organization, list[dict[str, Any]]] | None:
    from app.modules.identity_access.service.sso import organization_of  # noqa: PLC0415 - sso imports this module's neighbours

    organization = await organization_of(session, admin)
    return organization, list(organization.raw.get("domains") or [])


async def sync_one(
    session: AsyncSession, admin: IdentityAdmin, row: VerifiedDomain, *, multi_tenant: bool
) -> None:
    """Make Keycloak match one row: verified there iff verified here (idempotent).

    Un-verifying removes the domain from a multi-tenant realm's organisation (lane B (2): never
    left to block another tenant); a single-tenant realm keeps it, only no longer verified, so an
    SSO set-up's own routing stays (lane B's #569 review).
    """
    found = await _organization_domains(session, admin)
    if found is None:
        return
    organization, current = found
    live = row.state == DomainState.VERIFIED.value and row.deleted_at is None
    if live:
        wanted = rules.kc_verified(current, row.domain)
    elif multi_tenant:
        wanted = rules.kc_without(current, row.domain)
    else:
        wanted = rules.kc_unverified(current, row.domain)
    if wanted == current:
        return
    try:
        await admin.set_organization_domains(organization, wanted)
    except IdentityAdminRefused:
        # Another organisation holds it: never verified on two (the coordinator's condition).
        row.state, row.verified_at, row.verified_by_method = DomainState.PENDING.value, None, None
        row.last_outcome = ELSEWHERE
        await session.flush()
        await _changed(session, row, "refused")


async def on_domain_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: a verify or un-verify reaches Keycloak."""
    assert session is not None  # noqa: S101 - transactional consumer
    if envelope.payload.get("change") not in {"verified", "unverified", "lapsed"}:
        return
    settings = get_settings()
    admin = admin_factory(settings)
    if admin is None:
        return
    row = await session.get(VerifiedDomain, uuid.UUID(str(envelope.payload["domain_id"])))
    if row is not None:
        # An unreachable Keycloak raises: the worker retries.
        await sync_one(session, admin, row, multi_tenant=settings.multi_tenant)


DOMAIN_SYNC = ConsumerSpec(
    name="identity_access__verified_domain_sync",
    event_types=(VerifiedDomainChanged.event_type,),
    handler=on_domain_changed,
)


# --- the daily schedule ---------------------------------------------------------------------------


async def _tenant_ids(database: Database) -> list[uuid.UUID]:
    async with database.platform_session() as session:
        return list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())


async def check_schedule(database: Database, settings: Settings) -> None:
    """Daily: check what is due, then reconcile Keycloak with every tenant's verified rows."""
    admin = admin_factory(settings)
    now = system_clock.now()
    for tenant in await _tenant_ids(database):
        try:
            async with database.tenant_session(TenantContext(tenant)) as session:
                for row in await list_domains(session):
                    if not rules.scheduled(
                        row.verified_by_method, multi_tenant=settings.multi_tenant
                    ):
                        continue  # vouched for by an admin on a single-tenant installation
                    state = DomainState(row.state)
                    failing = row.failing_since is not None
                    if failing or rules.due(state, row.last_checked_at, row.created_at, now):
                        await check(session, row, now=now)
            if admin is not None:
                async with database.tenant_session(TenantContext(tenant)) as session:
                    for row in await list_domains(session):
                        await sync_one(session, admin, row, multi_tenant=settings.multi_tenant)
        except Exception:  # one tenant's failure never stops the others; it is logged
            log.exception("verified_domains_schedule_failed", tenant_id=str(tenant))
