"""The connector secrets store for other modules (WP-053 S6: monitoring_integrations' MonetX token).

The public face of `secrets.put_owned` and its companions, **owner-scoped** (lane A's and lane
C's S6 reviews):
- **Only external owner kinds** (`EXTERNAL_OWNER_KINDS`) may be used here. Integrations' own
  connectors (mailboxes, directories) keep their secrets through integrations alone, so another
  module can never store over, read, or forget a mailbox's OAuth secret or a bind password.
- **Every read names its owner:** a secret is returned only when its row matches the reference
  **and** the owner kind and ID. A known or guessed reference of someone else's opens nothing.
- **Metadata only, except the one read:** `connector_secret_info` gives the type and when it was
  set, never the value or any part of it. The plaintext comes only from `read_connector_secret`,
  to server code, and is never logged.
Sealed with the installation key ring, per tenant under RLS.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.integrations.infra.models import ConnectorSecret
from app.modules.integrations.service import secrets
from app.modules.integrations.service.connections import key_ring
from app.modules.integrations.service.mailboxes import KeyRingMissing

# The owner kinds another module may keep secrets for here (closed; add one per new module).
EXTERNAL_OWNER_KINDS = frozenset({"monitoring_connection"})


@dataclass(frozen=True, slots=True)
class ConnectorSecretInfo:
    """What may be shown about a stored secret: never its value, nor any part of it."""

    secret_type: str
    set_at: datetime


def _external(owner_kind: str) -> None:
    if owner_kind not in EXTERNAL_OWNER_KINDS:
        msg = f"owner kind {owner_kind!r} is not an external connector's"
        raise ValueError(msg)


async def _owned(
    session: AsyncSession, ref: uuid.UUID | None, owner_kind: str, owner_id: uuid.UUID
) -> ConnectorSecret | None:
    """The live row only when it is this owner's (the tenant is RLS's)."""
    if ref is None:
        return None
    return await session.scalar(
        select(ConnectorSecret).where(
            ConnectorSecret.id == ref,
            ConnectorSecret.owner_kind == owner_kind,
            ConnectorSecret.owner_id == owner_id,
            ConnectorSecret.deleted_at.is_(None),
        )
    )


async def store_connector_secret(  # noqa: PLR0913 - the owner, the role and the value, explicit
    session: AsyncSession,
    settings: Settings,
    *,
    owner_kind: str,
    owner_id: uuid.UUID,
    role: str,
    secret_type: str,
    value: str,
) -> uuid.UUID:
    """Store (or rotate) one secret; its reference. No key ring: `KeyRingMissing` (503)."""
    _external(owner_kind)
    ring = key_ring(settings)
    if ring is None:
        raise KeyRingMissing
    return await secrets.put_owned(
        session,
        ring,
        owner_kind=owner_kind,
        owner_id=owner_id,
        role=role,
        secret_type=secret_type,
        value=value,
    )


async def read_connector_secret(
    session: AsyncSession,
    settings: Settings,
    ref: uuid.UUID | None,
    *,
    owner_kind: str,
    owner_id: uuid.UUID,
) -> str | None:
    """The owner's secret by reference; None when it isn't theirs, gone, or no key ring."""
    _external(owner_kind)
    ring = key_ring(settings)
    if ring is None or await _owned(session, ref, owner_kind, owner_id) is None:
        return None
    return await secrets.read_owned(session, ring, ref)


async def forget_connector_secrets(
    session: AsyncSession, *, owner_kind: str, owner_id: uuid.UUID
) -> None:
    """Forget every secret of a removed external connector."""
    _external(owner_kind)
    await secrets.drop_owned(session, owner_kind=owner_kind, owner_id=owner_id)


async def connector_secret_info(
    session: AsyncSession, ref: uuid.UUID | None, *, owner_kind: str, owner_id: uuid.UUID
) -> ConnectorSecretInfo | None:
    """The owner's secret's type and when it was set (never its value or a part of it)."""
    _external(owner_kind)
    row = await _owned(session, ref, owner_kind, owner_id)
    return None if row is None else ConnectorSecretInfo(row.secret_type, row.set_at)


__all__ = [
    "EXTERNAL_OWNER_KINDS",
    "ConnectorSecretInfo",
    "connector_secret_info",
    "forget_connector_secrets",
    "read_connector_secret",
    "store_connector_secret",
]
