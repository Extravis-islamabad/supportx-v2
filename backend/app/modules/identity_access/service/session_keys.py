"""Recording the sign-in key ring at API start-up, and announcing its changes (D-162, ADR-048).

Start-up (`sync_session_keys`, every API replica) only claims what changed; it never writes a
tenant's audit log, so a SaaS installation with many tenants starts as fast as one with one:

1. A key ID recorded before but no longer listed is checked with the key-users hook
   (app/shared/crypto/users.py): when a registered user still counts items under it, start-up
   refuses (`session_key_still_in_use`). Sessions register nothing, they expire on their own.
2. A listed key ID not yet recorded is inserted with ON CONFLICT DO NOTHING ... RETURNING; a
   recorded key ID no longer listed is retired with UPDATE ... WHERE retired_at IS NULL
   RETURNING. Only the replica whose statement returned the row adds the change to
   `session_key_events`, in the same transaction, so each change is claimed exactly once.

The very first start (nothing recorded yet: a new installation, or the upgrade to D-162) only
records the ring as it is. That is no rotation, so it claims no change.

The audit log is per tenant (ADR-027) and the ring is the installation's, so the schedule
`announce_session_keys` (consumers worker) writes each change into every tenant's log: per
tenant, in one tenant transaction with app.tenant_id set, it inserts the tenant's row in
`session_key_announcements` (unique per tenant and change, ON CONFLICT DO NOTHING RETURNING) and
only when that insert returned the row writes the audit entry. Entry and marker commit together,
so a crash neither loses nor repeats a tenant's entry, and two runs at once write one. A tenant
created after the change is not told about it. Once every tenant is done the change is marked
announced and the schedule stops looking at it. Entries carry IDs and counts, never material.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit import WORKER, AuditActorType, record
from app.modules.identity_access.infra.models import (
    SessionKeyAnnouncement,
    SessionKeyEvent,
    SessionKeyId,
)
from app.shared.clock import Clock, system_clock
from app.shared.crypto import refuse_if_still_used
from app.shared.ids import new_id

log = get_logger(__name__)

RING = "session"
ROTATED = "security.session_key_rotated"
RETIRED = "security.session_key_retired"
OBJECT_TYPE = "session_key"


@dataclass
class KeySync:
    """What one start-up claimed: the key IDs whose change this replica recorded."""

    rotated: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)


async def sync_session_keys(
    database: Database, ring_ids: Sequence[str], *, clock: Clock = system_clock
) -> KeySync:
    """Record the ring (`ring_ids`, newest first); claim each change once across replicas."""
    async with database.platform_session() as session:
        rows = (await session.execute(select(SessionKeyId.key_id, SessionKeyId.retired_at))).all()
    recorded = {row.key_id: row.retired_at for row in rows}
    listed = set(ring_ids)
    removed = [key_id for key_id in recorded if key_id not in listed]
    await refuse_if_still_used(RING, removed)

    done = KeySync()
    if not recorded:
        await _record_baseline(database, ring_ids, clock)
        return done
    previous = next((k for k in ring_ids if k in recorded and recorded[k] is None), None)
    for key_id in ring_ids:
        if key_id in recorded and recorded[key_id] is None:
            continue  # listed and recorded: nothing changed
        now = clock.now()
        if key_id not in recorded:
            statement: Any = (
                insert(SessionKeyId)
                .values(key_id=key_id, first_seen_at=now, created_at=now, updated_at=now)
                .on_conflict_do_nothing(index_elements=[SessionKeyId.key_id])
                .returning(SessionKeyId.key_id)
            )
        else:  # retired before, listed again
            statement = (
                update(SessionKeyId)
                .where(SessionKeyId.key_id == key_id, SessionKeyId.retired_at.is_not(None))
                .values(retired_at=None, updated_at=now)
                .returning(SessionKeyId.key_id)
            )
        if await _claim(
            database,
            statement,
            action=ROTATED,
            key_id=key_id,
            previous=previous,
            readable=len(ring_ids),
            now=now,
        ):
            done.rotated.append(key_id)
            log.info("session_key_recorded", key_id=key_id, readable_keys=len(ring_ids))

    for key_id in removed:
        if recorded[key_id] is not None:
            continue  # retired already
        now = clock.now()
        statement = (
            update(SessionKeyId)
            .where(SessionKeyId.key_id == key_id, SessionKeyId.retired_at.is_(None))
            .values(retired_at=now, updated_at=now)
            .returning(SessionKeyId.key_id)
        )
        if await _claim(
            database,
            statement,
            action=RETIRED,
            key_id=key_id,
            previous=None,
            readable=len(ring_ids),
            now=now,
        ):
            done.retired.append(key_id)
            log.info("session_key_retired", key_id=key_id, readable_keys=len(ring_ids))
    return done


async def _claim(  # noqa: PLR0913 - the claim and every part of the change it records
    database: Database,
    statement: Any,  # noqa: ANN401 - an INSERT or UPDATE ... RETURNING
    *,
    action: str,
    key_id: str,
    previous: str | None,
    readable: int,
    now: datetime,
) -> bool:
    """Run the claim; when it won, record the change for the announcer in the same transaction."""
    async with database.platform_session() as claim:
        if (await claim.execute(statement)).scalar_one_or_none() is None:
            return False  # another replica claimed it
        claim.add(
            SessionKeyEvent(
                id=new_id(),
                key_id=key_id,
                action=action,
                previous_key_id=previous,
                readable_keys=readable,
                occurred_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    return True


async def _record_baseline(database: Database, ring_ids: Sequence[str], clock: Clock) -> None:
    now = clock.now()
    async with database.platform_session() as session:
        await session.execute(
            insert(SessionKeyId)
            .values(
                [
                    {"key_id": k, "first_seen_at": now, "created_at": now, "updated_at": now}
                    for k in ring_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=[SessionKeyId.key_id])
        )
    log.info("session_keys_recorded", key_ids=list(ring_ids))


# --- the announcer (schedule) ------------------------------------------------------------------


async def announce_session_keys(database: Database, settings: Settings) -> None:
    """Schedule: write each unannounced change into every tenant's audit log, once per tenant."""
    del settings
    await announce_pending(database)


async def announce_pending(database: Database) -> int:
    """How many entries this run wrote. Quick when nothing is pending: one query."""
    async with database.platform_session() as session:
        pending = list(
            (
                await session.scalars(
                    select(SessionKeyEvent)
                    .where(SessionKeyEvent.announced_at.is_(None))
                    .order_by(SessionKeyEvent.occurred_at, SessionKeyEvent.id)
                )
            ).all()
        )
        if not pending:
            return 0
        tenants: list[uuid.UUID] = list(
            (await session.scalars(text("SELECT audit_tenant_ids()"))).all()
        )
    written = 0
    failed = 0
    for tenant in tenants:
        # One tenant that fails never holds back the others (lane A's #418 review): it is
        # logged, and the change stays pending, so the next run tries that tenant again (the
        # others already have their marker and write nothing a second time).
        try:
            written += await _announce_to_tenant(database, tenant, pending)
        except Exception:
            failed += 1
            log.exception("session_key_announce_failed", tenant_id=str(tenant))
    if failed:
        return written
    async with database.platform_session() as session:
        await session.execute(
            update(SessionKeyEvent)
            .where(
                SessionKeyEvent.id.in_([event.id for event in pending]),
                SessionKeyEvent.announced_at.is_(None),
            )
            .values(announced_at=system_clock.now(), updated_at=system_clock.now())
        )
    if written:
        log.info("session_key_changes_announced", entries=written)
    return written


async def _announce_to_tenant(
    database: Database, tenant: uuid.UUID, pending: Sequence[SessionKeyEvent]
) -> int:
    """One tenant transaction: each change's marker and its audit entry commit together."""
    written = 0
    async with database.tenant_session(TenantContext(tenant)) as session:
        created = await session.scalar(
            text("SELECT created_at FROM tenants WHERE id = :tenant"), {"tenant": tenant}
        )
        for event in pending:
            if created is not None and created > event.occurred_at:
                continue  # the tenant did not exist yet: not its history
            marked = await session.scalar(
                insert(SessionKeyAnnouncement)
                .values(
                    tenant_id=tenant,
                    event_id=event.id,
                    key_id=event.key_id,
                    action=event.action,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        SessionKeyAnnouncement.tenant_id,
                        SessionKeyAnnouncement.event_id,
                    ]
                )
                .returning(SessionKeyAnnouncement.event_id)
            )
            if marked is None:
                continue  # announced by an earlier or a concurrent run
            details: dict[str, Any] = {
                "key_id": event.key_id,
                "readable_keys": event.readable_keys,
            }
            if event.action == ROTATED:
                details["previous_key_id"] = event.previous_key_id
            await record(
                session,
                action_code=event.action,
                facts=WORKER,
                object_type=OBJECT_TYPE,
                object_id=event.key_id,
                details=details,
                actor=(AuditActorType.SYSTEM, None),
            )
            written += 1
    return written
