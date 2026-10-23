"""Entitlement providers (WP-009).

Which one runs is configuration (SUPPORTX_ENTITLEMENT_PROVIDER), read in licensing/__init__.py
only; nothing else in the app knows which is active.

- `SubscriptionProvider`: the tenant's plan row in `tenant_subscriptions` (architecture.md §13.8;
  the control plane's data, cached per cell).
- `LicenceFileProvider`: one licence document for the whole installation (§13.2-13.5). Unsigned
  dev licences are accepted only in the dev and test profiles; WP-013 replaces the verifier and
  installation check with the Rust licence core.
- `StaticProvider`: fixed entitlements per tenant, for tests.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.licensing.domain.catalogue import Edition, Feature, LimitKey
from app.modules.licensing.domain.entitlement import Entitlement, Term
from app.modules.licensing.domain.licence import (
    LicenceDocument,
    LicenceRejectedError,
    parse_licence,
)
from app.modules.licensing.infra.models import TenantSubscription
from app.modules.licensing.service.ports import InstallationCheck, LicenceVerifier

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def subscription_entitlement(row: TenantSubscription) -> Entitlement:
    """Domain entitlement from a subscription row."""
    return Entitlement.build(
        Edition(row.edition),
        term=Term(
            starts_at=row.starts_at,
            expires_at=row.expires_at,
            maintenance_until=row.maintenance_until,
            grace_days=row.grace_days,
        ),
        extra_features=frozenset(Feature(f) for f in row.features),
        limit_overrides={LimitKey(k): v for k, v in row.limits.items()},
        suspended=row.status == "suspended",
    )


class SubscriptionProvider:
    """Reads `tenant_subscriptions` as the application role (RLS: own row only)."""

    cacheable = True

    def __init__(self, database: Database) -> None:
        self._database = database

    async def load(self, tenant_id: uuid.UUID, session: AsyncSession | None = None) -> Entitlement:
        """The tenant's plan, or no entitlement when it has no subscription row.

        Uses the caller's session when given (see the port), else a short session of its own.
        """
        if session is not None:
            return await self._read(session, tenant_id)
        async with self._database.tenant_session(TenantContext(tenant_id)) as own:
            return await self._read(own, tenant_id)

    @staticmethod
    async def _read(session: AsyncSession, tenant_id: uuid.UUID) -> Entitlement:
        row = await session.scalar(
            select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id)
        )
        return Entitlement.none() if row is None else subscription_entitlement(row)


class DevLicenceVerifier:
    """Accepts unsigned licences in dev/test only. Signed licences cannot be verified yet.

    TODO(WP-013): replace with the licence-core verifier (Ed25519 over
    `LicenceDocument.signed_payload`, public key compiled into the binary, §13.2 step 5).
    """

    def __init__(self, *, allow_unsigned: bool) -> None:
        self._allow_unsigned = allow_unsigned

    def verify(self, document: LicenceDocument) -> None:
        """Unsigned + dev/test profile: accepted. Anything else: rejected."""
        if document.signature is None:
            if not self._allow_unsigned:
                raise LicenceRejectedError(
                    reason="licence_unsigned",
                    detail="unsigned licences are accepted in dev/test only",
                )
            return
        raise LicenceRejectedError(
            reason="signature_verification_unavailable",
            detail="signed licences need the licence core (WP-013)",
        )


class NoInstallationCheck:
    """Binding check that always holds.

    TODO(WP-013): hardware fingerprint v1 (3 of 5 components, §13.4), installation ID binding and
    the signed "last seen" clock-rollback check (§13.5), re-run every 15 minutes.
    """

    def degraded_since(self, document: LicenceDocument, now: datetime) -> datetime | None:
        """Never degraded."""
        del document, now
        return None


class LicenceFileProvider:
    """The installation's licence file, read and verified when the service starts.

    A rejected licence raises LicenceRejectedError from the constructor, which stops startup:
    "Signature invalid → service refuses to start and logs the reason" (§13.6).
    """

    cacheable = False  # already in memory; every tenant of the installation shares it

    def __init__(
        self,
        path: Path,
        *,
        verifier: LicenceVerifier,
        installation: InstallationCheck,
        clock: Clock = _utcnow,
    ) -> None:
        self._path = path
        self._verifier = verifier
        self._installation = installation
        self._clock = clock
        self.document = self._read()

    def _read(self) -> LicenceDocument:
        try:
            raw = self._path.read_bytes()
        except OSError as exc:
            raise LicenceRejectedError(reason="licence_unreadable", detail=str(self._path)) from exc
        document = parse_licence(raw)
        self._verifier.verify(document)
        return document

    def reload(self) -> None:
        """Re-read and re-verify the file.

        TODO(WP-013): call this every 15 minutes (§13.5) and after a licence import (§13.2), and
        record `licensing.entitlement.changed` (source "licence") when the result changed.
        """
        self.document = self._read()

    async def load(self, tenant_id: uuid.UUID, session: AsyncSession | None = None) -> Entitlement:
        """The installation licence, with the grace clock started by a failing binding check."""
        del (
            tenant_id,
            session,
        )  # one licence per installation (see entitlements.md, "Limits on-prem")
        entitlement = self.document.entitlement
        since = self._installation.degraded_since(self.document, self._clock())
        return entitlement if since is None else replace(entitlement, degraded_since=since)


class StaticProvider:
    """Fixed entitlements for tests; tenants not listed get `default`."""

    cacheable = True

    def __init__(
        self,
        entitlements: Mapping[uuid.UUID, Entitlement] | None = None,
        default: Entitlement | None = None,
    ) -> None:
        self.entitlements = dict(entitlements or {})
        self.default = default or Entitlement.none()
        self.loads = 0

    async def load(self, tenant_id: uuid.UUID, session: AsyncSession | None = None) -> Entitlement:
        """The configured entitlement."""
        del session
        self.loads += 1
        return self.entitlements.get(tenant_id, self.default)
