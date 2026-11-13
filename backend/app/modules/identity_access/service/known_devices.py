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
from sqlalchemy.dialects.postgresql import insert
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
    known = await session.scalar(
        select(exists().where(KnownDevice.user_id == user_id, KnownDevice.fingerprint.in_(prints)))
    )
    if known:
        # Seen before, maybe under an older ring key: upsert the newest key's row, then drop the
        # older keys' rows. Both are conflict-free, so two sign-ins at once never collide.
        await session.execute(
            insert(KnownDevice)
            .values(
                tenant_id=tenant_id,
                id=new_id(),
                user_id=user_id,
                fingerprint=newest,
                last_seen_at=now,
            )
            .on_conflict_do_update(constraint="uq_known_devices_print", set_={"last_seen_at": now})
        )
        if len(prints) > 1:
            await session.execute(
                delete(KnownDevice).where(
                    KnownDevice.user_id == user_id, KnownDevice.fingerprint.in_(prints[1:])
                )
            )
        return Seen.KNOWN
    first = not await session.scalar(select(exists().where(KnownDevice.user_id == user_id)))
    # ON CONFLICT DO NOTHING (lane B, #486): another sign-in from the same new device at the same
    # moment (console and portal after SSO, two tabs) inserted it first. No row back means that
    # one tells the person; this one is KNOWN and raises nothing, never a 500.
    added = await session.scalar(
        insert(KnownDevice)
        .values(
            tenant_id=tenant_id, id=new_id(), user_id=user_id, fingerprint=newest, last_seen_at=now
        )
        .on_conflict_do_nothing(constraint="uq_known_devices_print")
        .returning(KnownDevice.id)
    )
    if added is None:
        return Seen.KNOWN
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
