"""Ports of the licensing module: implemented in infra/, chosen by configuration (WP-009).

`EntitlementProvider` is the one seam between "where licence data lives" and everything else.
`LicenceVerifier` and `InstallationCheck` are where WP-013 plugs in the Rust licence core
(Ed25519 signature, hardware fingerprint, clock rollback); see docs/architecture/entitlements.md.
"""

import uuid
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.licensing.domain.entitlement import Entitlement
from app.modules.licensing.domain.licence import LicenceDocument


class EntitlementProvider(Protocol):
    """Reads a tenant's entitlement from wherever the deployment keeps it."""

    # Whether results may be shared through the Valkey cache. A provider that already holds its
    # data in memory (the licence file) says False.
    cacheable: bool

    async def load(self, tenant_id: uuid.UUID, session: AsyncSession | None = None) -> Entitlement:
        """The tenant's entitlement; `Entitlement.none()` when it has none (fail closed).

        `session` is the caller's open tenant session, if any. A provider that reads the database
        must use it: opening a second connection while the caller holds a seat lock can starve
        the connection pool (every pooled transaction waiting on the lock its holder cannot
        finish without a connection).
        """
        ...


class LicenceVerifier(Protocol):
    """Decides whether a licence document is authentic. WP-013: Ed25519 via licence-core."""

    def verify(self, document: LicenceDocument) -> None:
        """Return if the licence may be used; raise LicenceRejectedError otherwise."""
        ...


class InstallationCheck(Protocol):
    """Binds a licence to this installation. WP-013: fingerprint (3 of 5) and clock rollback."""

    def degraded_since(self, document: LicenceDocument, now: datetime) -> datetime | None:
        """When the binding started failing (starts the grace period), or None if it holds."""
        ...
