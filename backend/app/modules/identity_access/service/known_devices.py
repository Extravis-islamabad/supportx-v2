"""Known browsers and devices, and the new-device notice (REQ-SEC-033; WP-057 S2b-1).

At every sign-in the person's fingerprint (domain/known_device.py) is looked up under each
known-device key. Seen before: its last-seen time moves and, after a ring rotation, it moves to
the newest key. Never seen: it is remembered and, unless this is the person's very first sign-in,
`NewDeviceSignedIn` goes to the outbox in the same transaction (rule b), which a locked security
notice turns into a message to the person. At most MAX_PER_PERSON devices are kept per person;
the oldest go first. The GDPR erasure job deletes a person's rows (`forget`).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.known_device import fingerprints
from app.modules.identity_access.events import NewDeviceSignedIn
from app.modules.identity_access.infra.models import KnownDevice
from app.shared.events import record_event
from app.shared.ids import new_id

MAX_PER_PERSON = 50


class Seen(StrEnum):
    """What a sign-in's device was to the person."""

    FIRST = "first"  # their first sign-in ever: remembered, nothing to tell
    KNOWN = "known"
    NEW = "new"  # remembered, and the person is told
    UNKNOWN = "unknown"  # nothing identifies it (no address, no device code, no key)


async def remember(
    session: AsyncSession,
    user_id: uuid.UUID,
    prints: Sequence[bytes],
    now: datetime,
    tenant_id: uuid.UUID,
) -> Seen:
    """Look the device up under every key (`prints`, newest first) and remember it."""
    if not prints:
        return Seen.UNKNOWN
    newest = prints[0]
    rows = list(
        await session.scalars(
            select(KnownDevice).where(
                KnownDevice.user_id == user_id, KnownDevice.fingerprint.in_(list(prints))
            )
        )
    )
    if rows:
        # The newest key's row if there is one; else move an older key's row to the newest.
        row = next((r for r in rows if r.fingerprint == newest), rows[0])
        row.fingerprint = newest
        row.last_seen_at = now
        return Seen.KNOWN
    first = not await session.scalar(select(exists().where(KnownDevice.user_id == user_id)))
    session.add(
        KnownDevice(
            tenant_id=tenant_id, id=new_id(), user_id=user_id, fingerprint=newest, last_seen_at=now
        )
    )
    await session.flush()
    await _trim(session, user_id)
    return Seen.FIRST if first else Seen.NEW


async def _trim(session: AsyncSession, user_id: uuid.UUID) -> None:
    count = await session.scalar(
        select(func.count()).select_from(KnownDevice).where(KnownDevice.user_id == user_id)
    )
    extra = int(count or 0) - MAX_PER_PERSON
    if extra <= 0:
        return
    oldest = (
        select(KnownDevice.id)
        .where(KnownDevice.user_id == user_id)
        .order_by(KnownDevice.last_seen_at, KnownDevice.id)
        .limit(extra)
    )
    await session.execute(delete(KnownDevice).where(KnownDevice.id.in_(oldest)))


async def on_sign_in(  # noqa: PLR0913 - the person, where and on what, keyword-only
    database: Database,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    keys: Sequence[bytes],
    device: str | None,
    ip: str | None,
    place: dict[str, Any] | None,
    now: datetime,
) -> Seen:
    """Remember this sign-in's device; a new one (not the first ever) tells the person."""
    prints = fingerprints(keys, user_id, device, ip)
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        seen = await remember(session, user_id, prints, now, tenant_id)
        if seen is Seen.NEW:
            await record_event(
                session,
                NewDeviceSignedIn(
                    user_id=user_id,
                    device=device,
                    place={k: str(v) for k, v in place.items()} if place else None,
                    signed_in_at=now,
                ),
                aggregate_id=user_id,
            )
    return seen


async def forget(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Erasure (GDPR): the person's known devices go."""
    result = await session.execute(delete(KnownDevice).where(KnownDevice.user_id == user_id))
    return int(getattr(result, "rowcount", 0) or 0)
