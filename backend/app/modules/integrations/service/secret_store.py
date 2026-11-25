"""The connector secrets store for other modules (WP-053 S6: monitoring_integrations' MonetX token).

The public face of `secrets.put_owned` and its companions: a module owns its connectors' rows by
`owner_kind`, and only ever holds the reference. Sealed with the installation key ring;
values are never logged or returned except to the owner that stored them.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.integrations.service import secrets
from app.modules.integrations.service.connections import key_ring
from app.modules.integrations.service.mailboxes import KeyRingMissing
from app.modules.integrations.service.secrets import SecretInfo


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
    session: AsyncSession, settings: Settings, ref: uuid.UUID | None
) -> str | None:
    """A secret by reference; None when there's none, no key ring, or it no longer opens."""
    ring = key_ring(settings)
    if ring is None:
        return None
    return await secrets.read_owned(session, ring, ref)


async def forget_connector_secrets(
    session: AsyncSession, *, owner_kind: str, owner_id: uuid.UUID
) -> None:
    """Forget every secret of a removed connector."""
    await secrets.drop_owned(session, owner_kind=owner_kind, owner_id=owner_id)


async def connector_secret_info(session: AsyncSession, ref: uuid.UUID | None) -> SecretInfo | None:
    """What may be shown about a secret (never its value)."""
    return await secrets.credential_info_of(session, ref)


__all__ = [
    "SecretInfo",
    "connector_secret_info",
    "forget_connector_secrets",
    "read_connector_secret",
    "store_connector_secret",
]
