"""Custom values as people may read them, and sealed at rest when sensitive (WP-057 S3b-2; SEC-040).

The one place a work item's custom values leave for a reader (lane A, 2026-11-15): first ADR-047's
strip (`field_rules.without`: hidden and masked keys out, never opened), then what is left is
opened when it is sealed. A sealed value is `sx2:` text (ADR-050's FieldCipher, purpose
`field.work_items.custom`, bound to the record and `custom.<key>`), holding the value as JSON so
numbers, dates and lists come back as they went in. A value that does not open comes back as
None and its key is listed as unreadable: never shown empty, never an error page (ADR-050).

Writers seal the values of fields whose seal state is `sealing` or `sealed`, and keep the blind
index (`work_item_field_index`) of each in step, for exact-match list filters.
"""

import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules import metadata
from app.modules.work_items.domain import field_access as field_rules
from app.modules.work_items.infra.models import WorkItemFieldIndex
from app.shared.crypto.codec import TEXT_PREFIX
from app.shared.fields import Binding, field_cipher_for, purpose
from app.shared.ids import new_id

CUSTOM = purpose(module="work_items", what="custom")
TABLE = "work_items"
SEALING_STATES = frozenset({"sealing", "sealed"})  # values are written sealed in these


@dataclass(frozen=True)
class Visible:
    """A record's custom values for one reader: what they may see, opened, and what did not open."""

    values: dict[str, Any]
    unreadable: frozenset[str] = field(default_factory=frozenset)


def is_sealed(value: object) -> bool:
    """Whether a stored custom value is sealed text."""
    return isinstance(value, str) and value.startswith(TEXT_PREFIX)


def _binding(record_id: uuid.UUID, key: str) -> Binding:
    return Binding(TABLE, record_id, f"custom.{key}")


async def visible_custom(
    session: AsyncSession,
    settings: Settings,
    record_id: uuid.UUID,
    custom: Mapping[str, Any] | None,
    *,
    unseen: field_rules.Unseen,
) -> Visible:
    """The custom values this reader may see, sealed ones opened; withheld ones never opened."""
    shown = field_rules.without(custom, unseen.custom_keys())
    sealed = {key: value for key, value in shown.items() if is_sealed(value)}
    if not sealed:
        return Visible(shown)
    cipher = field_cipher_for(session, settings)
    unreadable: set[str] = set()
    for key, value in sealed.items():
        opened = await cipher.open(CUSTOM, _binding(record_id, key), value)
        if opened is None:
            shown[key] = None
            unreadable.add(key)
            continue
        try:
            shown[key] = json.loads(opened)
        except ValueError:
            shown[key] = None
            unreadable.add(key)
    return Visible(shown, frozenset(unreadable))


async def visible_custom_many(
    session: AsyncSession,
    settings: Settings,
    rows: Iterable[tuple[uuid.UUID, Mapping[str, Any] | None]],
    *,
    unseen: field_rules.Unseen,
) -> dict[uuid.UUID, Visible]:
    """`visible_custom` for a page of records (one cipher; keys cached for the page)."""
    found: dict[uuid.UUID, Visible] = {}
    for record_id, custom in rows:
        found[record_id] = await visible_custom(session, settings, record_id, custom, unseen=unseen)
    return found


async def sealing_keys(session: AsyncSession, entity: str) -> frozenset[str]:
    """The entity's custom fields whose values are written sealed now."""
    return frozenset(
        mark.key
        for mark in await metadata.field_marks(session, entity, retired=True)
        if mark.seal_state in SEALING_STATES
    )


async def seal_custom(
    session: AsyncSession,
    settings: Settings,
    record_id: uuid.UUID,
    custom: Mapping[str, Any] | None,
    *,
    sealed_keys: frozenset[str],
) -> dict[str, Any]:
    """The values as stored: sealed for the keys in `sealed_keys`, the blind index kept in step.

    A value already sealed is kept as it is (a save that did not change it). None removes the
    key's index row.
    """
    stored = dict(custom or {})
    if not sealed_keys:
        return stored
    cipher = field_cipher_for(session, settings)
    for key in sealed_keys:
        if key not in stored or stored[key] is None:
            await session.execute(
                delete(WorkItemFieldIndex).where(
                    WorkItemFieldIndex.work_item_id == record_id,
                    WorkItemFieldIndex.field_key == key,
                )
            )
            continue
        value = stored[key]
        if is_sealed(value):
            continue
        plain = json.dumps(value, ensure_ascii=False, sort_keys=True)
        stored[key] = await cipher.seal(CUSTOM, _binding(record_id, key), plain)
        key_id, digest = await cipher.blind(CUSTOM, _blind_text(value))
        await session.execute(
            insert(WorkItemFieldIndex)
            .values(
                id=new_id(),
                work_item_id=record_id,
                field_key=key,
                key_id=key_id,
                digest=digest,
            )
            .on_conflict_do_update(
                constraint="uq_work_item_field_index_place",
                set_={"key_id": key_id, "digest": digest},
            )
        )
    return stored


def _blind_text(value: object) -> str:
    """What an exact-match filter compares: a text as itself, anything else as its JSON."""
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


async def matching_records(
    session: AsyncSession,
    settings: Settings,
    key: str,
    values: Iterable[object],
) -> frozenset[uuid.UUID]:
    """Records whose sealed `key` equals any of `values` (an `eq` / `in` filter, WP-057 S3b-2).

    Each index row keeps the data key its digest was made under, so the values are digested once
    per data key in use for that field: a data-key rotation needs no immediate rebuild.
    """
    key_ids = list(
        await session.scalars(
            select(WorkItemFieldIndex.key_id).where(WorkItemFieldIndex.field_key == key).distinct()
        )
    )
    if not key_ids:
        return frozenset()
    cipher = field_cipher_for(session, settings)
    pairs: list[tuple[uuid.UUID, str]] = []
    for value in values:
        for key_id, digest in (
            await cipher.blind_under(CUSTOM, _blind_text(value), key_ids)
        ).items():
            pairs.append((key_id, digest))
    if not pairs:
        return frozenset()
    found: set[uuid.UUID] = set()
    for key_id, digest in pairs:
        found.update(
            await session.scalars(
                select(WorkItemFieldIndex.work_item_id).where(
                    WorkItemFieldIndex.field_key == key,
                    WorkItemFieldIndex.key_id == key_id,
                    WorkItemFieldIndex.digest == digest,
                )
            )
        )
    return frozenset(found)
