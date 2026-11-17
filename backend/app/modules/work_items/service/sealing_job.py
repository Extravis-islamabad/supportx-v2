"""The re-seal job: stored custom values follow a field's `sensitive` mark (WP-057 S3b-2b).

When an admin marks a work-item custom field sensitive, its stored values are sealed record by
record, with their blind-index rows; when they unmark it, opened back to plain JSON and the rows
deleted. The field's `seal_state` (metadata) says which: `sealing` or `opening`, then `sealed`
or `plain` once every record is done.

- **Batches** of `BATCH` records past the field's cursor (UUIDv7 order), one transaction each,
  rows locked `FOR UPDATE`: a person's save waits for the batch, then writes in the right form,
  since writers seal while `sealing`/`sealed` and write plain otherwise. Each row's update is
  also compare-and-set on the value the job read (lane B): a value changed in between is never
  overwritten.
- **No version, no history:** the stored form changes, never the value. History is never
  touched (lane B's option b: what was written sealed stays sealed).
- **Resumable:** the cursor commits with each batch. A reversal (on, then off, mid-run) resets
  it; already-moved values are skipped either way, so it converges.
- **Keys missing or locked** (`FieldKeysUnavailable`): the batch rolls back, the state stays as
  it is, the next tick tries again; the admins hear once per outage (lane B).
- **The licence** is not asked: a lapsed `field_encryption` never stops a field half-sealed.
- **Search:** the switch marks the type's search text for rebuilding at its commit (sealing) and
  the job's last batch does when the field is plain again (opening): a sealed field's words are
  never findable, and they return only once readable (lane B).
"""

import json
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules import metadata
from app.modules.work_items.domain.field_access import CUSTOM as CUSTOM_PREFIX
from app.modules.work_items.domain.types import TYPES
from app.modules.work_items.infra.models import WorkItem, WorkItemFieldIndex
from app.modules.work_items.service import custom_values, search_rebuild
from app.shared.crypto.codec import TEXT_PREFIX
from app.shared.fields import FieldKeysUnavailable, field_cipher_for

log = get_logger(__name__)
BATCH = 500
TICK_SECONDS = 20.0  # a tick's share of work before it lets the next tenant go
ENTITIES = tuple(sorted(t.value for t in TYPES))


class WorkItemSealPort:
    """What work items do when a field's seal state moves (registered with metadata)."""

    async def mark(self, session: AsyncSession, entity: str, key: str, state: str) -> None:
        """Sealing: out of search text now. Plain again: back in, once readable (lane B)."""
        if state in {metadata.SEALING, metadata.PLAIN}:
            await search_rebuild.mark(session, entity, f"{CUSTOM_PREFIX}{key}")

    async def holding(self, session: AsyncSession, entity: str, key: str) -> int:
        """Records of the type holding a value of the field (trashed ones too)."""
        count = await session.scalar(
            select(func.count())
            .select_from(WorkItem)
            .where(WorkItem.type == entity, WorkItem.custom.has_key(key))
        )
        return int(count or 0)


PORT = WorkItemSealPort()


def register() -> None:
    """The port for every work-item type (at import)."""
    metadata.register_seal_port(ENTITIES, PORT)


@dataclass(frozen=True)
class Batch:
    """One batch's outcome."""

    moved: int
    finished: bool


async def _rows(session: AsyncSession, field: metadata.Moving) -> list[tuple[uuid.UUID, object]]:
    query = (
        select(WorkItem.id, WorkItem.custom[field.key])
        .where(WorkItem.type == field.entity, WorkItem.custom.has_key(field.key))
        .order_by(WorkItem.id)
        .limit(BATCH)
        .with_for_update(of=WorkItem)
    )
    if field.cursor is not None:
        query = query.where(WorkItem.id > field.cursor)
    return [(row[0], row[1]) for row in (await session.execute(query)).all()]


async def _swap(
    session: AsyncSession, record_id: uuid.UUID, key: str, read: object, stored: object
) -> bool:
    """Compare-and-set: the value replaced only if it is still what the job read (lane B)."""
    # The key goes in as a bound parameter, never as SQL text.
    done = await session.execute(
        update(WorkItem)
        .where(WorkItem.id == record_id, WorkItem.custom[key] == literal(read, JSONB))
        .values(
            custom=WorkItem.custom.op("||")(func.jsonb_build_object(key, literal(stored, JSONB)))
        )
        .execution_options(synchronize_session=False)
    )
    return bool(getattr(done, "rowcount", 0))


async def _seal_one(session: AsyncSession, record_id: uuid.UUID, key: str, value: object) -> bool:
    if value is None or custom_values.is_sealed(value):
        return False
    sealed = await custom_values.seal_custom(
        session, record_id, {key: value}, sealed_keys=frozenset({key})
    )
    if not await _swap(session, record_id, key, value, sealed.stored[key]):
        return False
    await custom_values.write_index(session, record_id, sealed.index)
    return True


async def _open_one(
    session: AsyncSession, record_id: uuid.UUID, key: str, value: object, settings: Settings
) -> bool:
    if not custom_values.is_sealed(value):
        return False
    cipher = field_cipher_for(session, settings)
    opened = await cipher.open(
        custom_values.CUSTOM, custom_values.record_binding(record_id, key), str(value)
    )
    if opened is None:
        return False  # tampered or moved: left sealed and counted at the end (unreadable)
    try:
        plain = json.loads(opened)
    except ValueError:
        return False
    if not await _swap(session, record_id, key, value, plain):
        return False
    await session.execute(
        delete(WorkItemFieldIndex).where(
            WorkItemFieldIndex.work_item_id == record_id, WorkItemFieldIndex.field_key == key
        )
    )
    return True


async def _unreadable(session: AsyncSession, field: metadata.Moving) -> int:
    """Values still sealed when opening ends: they did not open (counted, never shown)."""
    count = await session.scalar(
        select(func.count())
        .select_from(WorkItem)
        .where(
            WorkItem.type == field.entity,
            WorkItem.custom[field.key].astext.startswith(TEXT_PREFIX),
        )
    )
    return int(count or 0)


async def run_batch(session: AsyncSession, field: metadata.Moving, settings: Settings) -> Batch:
    """One batch of one field, in the caller's transaction (it commits the batch and cursor).

    Nothing is written when the field moved since it was read (a reversal): the caller reads
    it again and follows the new state (lane B, #526).
    """
    if not await metadata.hold_seal(session, field):
        return Batch(0, finished=False)
    rows = await _rows(session, field)
    moved = 0
    for record_id, value in rows:
        if field.state == metadata.SEALING:
            moved += await _seal_one(session, record_id, field.key, value)
        else:
            moved += await _open_one(session, record_id, field.key, value, settings)
    if len(rows) == BATCH:
        await metadata.advance_seal(session, field, rows[-1][0])
        return Batch(moved, finished=False)
    if field.state == metadata.OPENING:
        # Fully plain: no index row of the field may stay behind (lane B).
        # Only this type's rows: another type may have a field with the same key (lane B).
        await session.execute(
            delete(WorkItemFieldIndex).where(
                WorkItemFieldIndex.field_key == field.key,
                WorkItemFieldIndex.work_item_id.in_(
                    select(WorkItem.id).where(WorkItem.type == field.entity)
                ),
            )
        )
    records = await PORT.holding(session, field.entity, field.key)
    unreadable = await _unreadable(session, field) if field.state == metadata.OPENING else 0
    await metadata.finish_seal(session, field, records=records, unreadable=unreadable)
    return Batch(moved, finished=True)


async def run_tenant(database: Database, tenant: uuid.UUID, settings: Settings) -> int:
    """The tenant's moving fields, batch after batch, for up to TICK_SECONDS; values moved."""
    started = time.monotonic()
    moved = 0
    async with database.tenant_session(TenantContext(tenant)) as session:
        fields = await metadata.fields_being_sealed(session, ENTITIES)
    for field in fields:
        current: metadata.Moving | None = field
        while current is not None and time.monotonic() - started < TICK_SECONDS:
            async with database.tenant_session(TenantContext(tenant)) as session:
                batch = await run_batch(session, current, settings)
                moved += batch.moved
                current = None if batch.finished else await _again(session, current)
    return moved


async def _again(session: AsyncSession, field: metadata.Moving) -> metadata.Moving | None:
    """The field as it stands after a batch (its state may have moved: a reversal)."""
    for found in await metadata.fields_being_sealed(session, ENTITIES):
        if found.id == field.id:
            return found
    return None


async def seal_schedule(database: Database, settings: Settings) -> None:
    """Every tenant with a field being sealed or opened (`work_items__custom_field_seal`)."""
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        try:
            moved = await run_tenant(database, tenant, settings)
        except FieldKeysUnavailable:
            # Paused, state unchanged; the next tick tries again (lane B). The notice: below.
            log.warning("custom_field_seal_paused_keys", tenant_id=str(tenant))
            await keys_unavailable(database, tenant)
            continue
        if moved:
            log.info("custom_field_seal_batch", tenant_id=str(tenant), moved=moved)


async def keys_unavailable(database: Database, tenant: uuid.UUID) -> None:
    """Tell the tenant's admins once per outage that sealing is paused (lane B).

    In its own transaction, as the batch's rolled back; the fields' states are untouched.
    """
    async with database.tenant_session(TenantContext(tenant)) as session:
        for field in await metadata.fields_being_sealed(session, ENTITIES):
            await metadata.seal_paused(session, field)


__all__ = ["BATCH", "PORT", "Batch", "WorkItemSealPort", "register", "run_batch", "seal_schedule"]
