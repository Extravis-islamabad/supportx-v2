"""Recording the sign-in key ring at API start-up (D-162, ADR-048; migration 0146).

Every API replica runs `sync_session_keys` when it starts:

1. A key ID recorded before but no longer listed is checked with the key-users hook
   (app/shared/crypto/users.py): when a registered user still counts items under it, start-up
   refuses (`session_key_still_in_use`). Sessions register nothing, they expire on their own.
2. A listed key ID not yet recorded is inserted with ON CONFLICT DO NOTHING ... RETURNING. Only
   the replica whose insert returned the row writes `security.session_key_rotated`.
3. A recorded key ID no longer listed is retired with UPDATE ... WHERE retired_at IS NULL
   RETURNING. Only the replica whose update returned the row writes `security.session_key_retired`.

The very first start (nothing recorded yet: a new installation, or the upgrade to D-162) only
records the ring as it is. That is no rotation, so it writes no audit entry.

The audit log is per tenant (ADR-027) and the ring is the installation's, so the winning replica
writes the entry into every tenant's log (system actor, IDs and counts only, never material).
The claim's transaction stays open until every tenant's entry is written: a replica that dies
half-way leaves no claim, and the next start writes the entries again (at least once, never
lost). A replica starting meanwhile waits on the claimed row and then finds it taken.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit import WORKER, AuditActorType, record_alone
from app.modules.identity_access.infra.models import SessionKeyId
from app.shared.clock import Clock, system_clock
from app.shared.crypto import refuse_if_still_used

if TYPE_CHECKING:
    import uuid

log = get_logger(__name__)

RING = "session"
ROTATED = "security.session_key_rotated"
RETIRED = "security.session_key_retired"
OBJECT_TYPE = "session_key"


@dataclass
class KeySync:
    """What one start-up recorded: the key IDs this replica announced."""

    rotated: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)


async def sync_session_keys(
    database: Database, ring_ids: Sequence[str], *, clock: Clock = system_clock
) -> KeySync:
    """Record the ring (`ring_ids`, newest first); audit each change once across replicas."""
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
        async with database.platform_session() as claim:
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
            if (await claim.execute(statement)).scalar_one_or_none() is None:
                continue  # another replica recorded it
            details = {
                "key_id": key_id,
                "previous_key_id": previous,
                "readable_keys": len(ring_ids),
            }
            await _announce(database, ROTATED, key_id, details)
        done.rotated.append(key_id)
        log.info("session_key_recorded", key_id=key_id, readable_keys=len(ring_ids))

    for key_id in removed:
        if recorded[key_id] is not None:
            continue  # retired already
        now = clock.now()
        async with database.platform_session() as claim:
            won = (
                await claim.execute(
                    update(SessionKeyId)
                    .where(SessionKeyId.key_id == key_id, SessionKeyId.retired_at.is_(None))
                    .values(retired_at=now, updated_at=now)
                    .returning(SessionKeyId.key_id)
                )
            ).scalar_one_or_none()
            if won is None:
                continue
            await _announce(
                database, RETIRED, key_id, {"key_id": key_id, "readable_keys": len(ring_ids)}
            )
        done.retired.append(key_id)
        log.info("session_key_retired", key_id=key_id, readable_keys=len(ring_ids))
    return done


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


async def _announce(database: Database, action: str, key_id: str, details: dict[str, Any]) -> None:
    """One entry in every tenant's audit log, by the system (no person, no request)."""
    async with database.platform_session() as session:
        tenants: list[uuid.UUID] = list(
            (await session.scalars(text("SELECT audit_tenant_ids()"))).all()
        )
    for tenant in tenants:
        await record_alone(
            database,
            TenantContext(tenant),
            action_code=action,
            facts=WORKER,
            object_type=OBJECT_TYPE,
            object_id=key_id,
            details=details,
            actor=(AuditActorType.SYSTEM, None),
        )
