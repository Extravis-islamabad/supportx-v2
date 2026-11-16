"""A custom field's `sensitive` mark, switched on or off (WP-057 S3b-2b; REQ-SEC-040).

`sensitive` decides that a field's values are sealed at rest (ADR-050 addendum 2). The switch
moves `seal_state`; the stored values follow in the owning module's re-seal job, which reports
its progress and its end here:

- **On** (needs the `field_encryption` feature): `plain`/`opening` → `sealing`, then `sealed`.
  The owning module's port marks its search text for rebuilding in the switch's own
  transaction, so search stops finding the field's words at the commit (lane B, S3b-2b).
- **Off** (always allowed: removing protection never needs a licence, ADR-047 §13), the riskier
  direction, as values become readable at rest: a recent sign-in confirmation (the route), a
  typed reason and the field's English name typed back (lane B). `sealed`/`sealing` →
  `opening`, then `plain`. History written while sealed stays sealed (lane B's option b).
- Only entities whose module registered a seal port can be sensitive (work items today).

Every move is in the field's history and the audit log; events carry the state and counts,
never a value (the coordinator, S3b-2b).
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, EntitlementRequired
from app.modules.audit import WORKER, AuditActorType, record
from app.modules.licensing import Feature, has_feature
from app.modules.metadata.events import CustomFieldSealChanged, CustomFieldSealPaused
from app.modules.metadata.infra.models import CustomField
from app.modules.metadata.service.custom_fields import (
    RECORD_TYPE,
    _forget,
    _get,
    _problems,
    _same_version,
)
from app.shared.events import record_event
from app.shared.events.outbox import ProcessedEvent
from app.shared.history import Change, Source, record_changes

SealState = Literal["plain", "sealing", "sealed", "opening"]  # checked by the table
PLAIN, SEALING, SEALED, OPENING = "plain", "sealing", "sealed", "opening"
MOVING = frozenset({SEALING, OPENING})
FINAL = {SEALING: SEALED, OPENING: PLAIN}
REASON_MAX = 500


class SealPort(Protocol):
    """What the module that stores an entity's values does when a field's seal state moves."""

    async def mark(self, session: AsyncSession, entity: str, key: str, state: str) -> None:
        """Inside the switch's (or the job's last) transaction: search text and caches."""

    async def holding(self, session: AsyncSession, entity: str, key: str) -> int:
        """How many records hold a value of the field (the confirmation's impact)."""


_PORTS: dict[str, SealPort] = {}


def register_seal_port(entities: Iterable[str], port: SealPort) -> None:
    """The module storing these entities' custom values seals them (at import)."""
    for entity in entities:
        _PORTS[entity] = port


def sealable(entity: str) -> bool:
    """Whether a field of this entity can be marked sensitive."""
    return entity in _PORTS


@dataclass(frozen=True)
class Switched:
    """The switch's outcome: the field as now, the states either side, records affected."""

    row: CustomField
    before: str
    after: str
    records: int

    @property
    def changed(self) -> bool:
        """Whether anything moved (a repeat of the same choice is no change)."""
        return self.before != self.after


def _port(entity: str) -> SealPort:
    port = _PORTS.get(entity)
    if port is None:
        raise Conflict(code="custom_field_sensitive_unsupported")
    return port


async def impact(session: AsyncSession, field_id: uuid.UUID) -> tuple[CustomField, int]:
    """The field and how many records hold a value of it (what the confirmation states)."""
    row = await _get(session, field_id)
    return row, await _port(row.entity).holding(session, row.entity, row.key)


def _target(row: CustomField, *, sensitive: bool) -> str:
    if sensitive:
        return row.seal_state if row.seal_state in {SEALING, SEALED} else SEALING
    return row.seal_state if row.seal_state in {OPENING, PLAIN} else OPENING


def _off_problems(row: CustomField, reason: str | None, confirm: str | None) -> None:
    problems: list[tuple[str, str]] = []
    if not (reason or "").strip():
        problems.append(("reason", "required"))
    elif len(reason or "") > REASON_MAX:
        problems.append(("reason", "too_long"))
    english = (row.labels or {}).get("en", "")
    if (confirm or "").strip().casefold() != english.strip().casefold():
        problems.append(("confirm_name", "confirm_name_mismatch"))
    if problems:
        raise _problems(problems)


async def set_sensitive(  # noqa: PLR0913 - the choice, its confirmation and context, explicit
    session: AsyncSession,
    field_id: uuid.UUID,
    *,
    sensitive: bool,
    reason: str | None,
    confirm_name: str | None,
    expected_version: int,
    source: Source,
) -> Switched:
    """Mark the field sensitive (sealing starts) or not (opening starts); If-Match.

    The caller (the route) has confirmed a recent sign-in and records the audit entry.
    """
    row = await _get(session, field_id)
    await _same_version(session, row, expected_version)
    port = _port(row.entity)
    before, after = row.seal_state, _target(row, sensitive=sensitive)
    records = await port.holding(session, row.entity, row.key)
    if before == after and row.sensitive == sensitive:
        return Switched(row, before, after, records)
    if sensitive:
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        if not await has_feature(tenant, Feature.FIELD_ENCRYPTION):
            raise EntitlementRequired(params={"feature": Feature.FIELD_ENCRYPTION.value})
    else:
        _off_problems(row, reason, confirm_name)
    was_sensitive = row.sensitive
    row.sensitive = sensitive
    row.seal_state = after
    row.seal_cursor = None  # a reversal starts again from the first record
    row.version += 1
    await session.flush()
    _forget(session, row.entity)
    await port.mark(session, row.entity, row.key, after)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="updated",
        changes=[
            Change("sensitive", was_sensitive, sensitive),
            Change("seal_state", before, after),
        ],
        source=source,
        reason=None if sensitive else (reason or "").strip(),
    )
    await _event(session, row, records=records)
    return Switched(row, before, after, records)


async def _event(
    session: AsyncSession, row: CustomField, *, records: int, unreadable: int = 0
) -> None:
    await record_event(
        session,
        CustomFieldSealChanged(
            custom_field_id=row.id,
            entity=row.entity,
            key=row.key,
            seal_state=cast("SealState", row.seal_state),
            records=records,
            unreadable=unreadable,
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


@dataclass(frozen=True)
class Moving:
    """A field whose stored values the job is still moving (sealing or opening)."""

    id: uuid.UUID
    entity: str
    key: str
    state: str
    cursor: uuid.UUID | None


async def moving(session: AsyncSession, entities: Iterable[str]) -> list[Moving]:
    """The tenant's fields of these entities being sealed or opened, oldest change first."""
    rows = await session.scalars(
        select(CustomField)
        .where(
            CustomField.entity.in_(list(entities)),
            CustomField.seal_state.in_(sorted(MOVING)),
            CustomField.deleted_at.is_(None),
        )
        .order_by(CustomField.updated_at, CustomField.id)
    )
    return [Moving(r.id, r.entity, r.key, r.seal_state, r.seal_cursor) for r in rows]


async def advance(session: AsyncSession, field: Moving, cursor: uuid.UUID) -> bool:
    """The job's place after a batch; False when the field's state moved meanwhile.

    No version bump and no history: the field's settings did not change, only where the job
    stands (an admin's If-Match still matches).
    """
    done = await session.execute(
        update(CustomField)
        .where(CustomField.id == field.id, CustomField.seal_state == field.state)
        .values(seal_cursor=cursor)
    )
    return bool(getattr(done, "rowcount", 0))


async def finish(session: AsyncSession, field: Moving, *, records: int, unreadable: int) -> bool:
    """`sealing` → `sealed` or `opening` → `plain` once every record is done; audited.

    False when the state moved meanwhile (a reversal): the job then follows the new state.
    """
    row = await session.scalar(
        select(CustomField)
        .where(CustomField.id == field.id, CustomField.seal_state == field.state)
        .with_for_update()
    )
    if row is None:
        return False
    final = FINAL[field.state]
    row.seal_state = final
    row.seal_cursor = None
    row.version += 1
    await session.flush()
    _forget(session, row.entity)
    await _PORTS[row.entity].mark(session, row.entity, row.key, final)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind="updated",
        changes=[Change("seal_state", field.state, final)],
        source="system",
    )
    await _event(session, row, records=records, unreadable=unreadable)
    await record(
        session,
        action_code="metadata.custom_field_sealed"
        if final == SEALED
        else "metadata.custom_field_opened",
        facts=WORKER,
        actor=(AuditActorType.SYSTEM, None),
        object_type=RECORD_TYPE,
        object_id=row.id,
        details={
            "entity": row.entity,
            "key": row.key,
            "records": records,
            "unreadable": unreadable,
        },
    )
    return True


# The pause notice goes once per outage: its claim, keyed by the field, is made when the job
# pauses and dropped by the next batch that runs (the consumers' own idempotency table).
PAUSE_CLAIM = "metadata__seal_paused"


async def paused(session: AsyncSession, field: Moving) -> bool:
    """The keys are unavailable: tell the admins, the first time of this outage only."""
    claimed = await session.execute(
        insert(ProcessedEvent)
        .values(
            tenant_id=session.info[SESSION_TENANT_KEY].tenant_id,
            consumer=PAUSE_CLAIM,
            event_id=field.id,
        )
        .on_conflict_do_nothing()
    )
    if not getattr(claimed, "rowcount", 0):
        return False
    await record_event(
        session,
        CustomFieldSealPaused(
            custom_field_id=field.id,
            entity=field.entity,
            key=field.key,
            seal_state=cast("Literal['sealing', 'opening']", field.state),
        ),
        aggregate_id=field.id,
    )
    return True


async def resumed(session: AsyncSession, field: Moving) -> None:
    """A batch ran: the outage (if any) is over, so a later one is told again."""
    await session.execute(
        delete(ProcessedEvent).where(
            ProcessedEvent.consumer == PAUSE_CLAIM, ProcessedEvent.event_id == field.id
        )
    )


__all__ = [
    "MOVING",
    "OPENING",
    "PLAIN",
    "SEALED",
    "SEALING",
    "Moving",
    "SealPort",
    "Switched",
    "advance",
    "finish",
    "impact",
    "moving",
    "paused",
    "register_seal_port",
    "resumed",
    "sealable",
    "set_sensitive",
]
