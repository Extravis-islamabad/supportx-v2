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

from app.core.config import Settings, get_settings
from app.core.errors import FieldError, ValidationFailed
from app.modules import metadata
from app.modules.work_items.domain import field_access as field_rules
from app.modules.work_items.infra.models import WorkItemFieldIndex
from app.shared.crypto.codec import TEXT_PREFIX
from app.shared.fields import Binding, field_cipher_for, purpose
from app.shared.history import Change
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
    record_id: uuid.UUID,
    custom: Mapping[str, Any] | None,
    *,
    unseen: field_rules.Unseen,
    settings: Settings | None = None,
) -> Visible:
    """The custom values this reader may see, sealed ones opened; withheld ones never opened."""
    shown = field_rules.without(custom, unseen.custom_keys())
    sealed = {key: value for key, value in shown.items() if is_sealed(value)}
    if not sealed:
        return Visible(shown)
    cipher = field_cipher_for(session, settings or get_settings())
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


async def opened(
    session: AsyncSession,
    record_id: uuid.UUID,
    custom: Mapping[str, Any] | None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """All of a record's custom values, sealed ones opened, for the system.

    Rules, copies and the erasure use it; never handed to a person as is. Unreadable ones are None.
    """
    found = await visible_custom(
        session, record_id, custom, unseen=field_rules.Unseen(), settings=settings
    )
    return found.values


async def visible_custom_many(
    session: AsyncSession,
    rows: Iterable[tuple[uuid.UUID, Mapping[str, Any] | None]],
    *,
    unseen: field_rules.Unseen,
    settings: Settings | None = None,
) -> dict[uuid.UUID, Visible]:
    """`visible_custom` for a page of records (the data keys cached for the page)."""
    found: dict[uuid.UUID, Visible] = {}
    for record_id, custom in rows:
        found[record_id] = await visible_custom(
            session, record_id, custom, unseen=unseen, settings=settings
        )
    return found


async def unchanged_sealed(
    session: AsyncSession,
    record_id: uuid.UUID,
    stored: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """`incoming` with every sealed value it did not change put back as stored ciphertext.

    A reader sends back the opened value of a field they did not touch: it must not count as a
    change, be sealed again, nor reach history (lane B's option b: ciphertext never rewritten).
    """
    out = dict(incoming)
    sealed = {k: v for k, v in (stored or {}).items() if is_sealed(v) and k in out}
    if not sealed:
        return out
    opened = await visible_custom(
        session, record_id, sealed, unseen=field_rules.Unseen(), settings=settings
    )
    for key, value in sealed.items():
        if key not in opened.unreadable and opened.values.get(key) == out[key]:
            out[key] = value
    return out


def history_binding(
    record_type: str, record_id: uuid.UUID, field_name: str, version: int, side: str
) -> Binding:
    """Where a sealed history value lives: one cell of one save (lane B, 2026-11-16).

    The history row's own ID exists only inside `record_changes`; one save per record type,
    record and version makes this unique per cell, so a value never opens in another row,
    version, field or side.
    """
    return Binding("field_changes", record_id, f"{record_type}:{field_name}@v{version}:{side}")


async def seal_history(  # noqa: PLR0913 - one save's parts, explicit
    session: AsyncSession,
    record_type: str,
    record_id: uuid.UUID,
    version: int,
    changes: list[Change],
    *,
    sealed_keys: frozenset[str] = frozenset(),
    settings: Settings | None = None,
) -> list[Change]:
    """History changes with sensitive custom values sealed for their history cell.

    A value stored sealed is opened from the record's binding and sealed again under the history
    one: the record's ciphertext is never copied into history (lane B's option b: history
    ciphertext is never rewritten after). A plain value of a key in `sealed_keys` (a rule's
    action) is sealed too. A value that does not open is written as None, never as text.
    """

    def touches(change: Change) -> bool:
        key = change.field.removeprefix("custom.")
        return change.field.startswith("custom.") and (
            key in sealed_keys or is_sealed(change.old) or is_sealed(change.new)
        )

    if not any(touches(c) for c in changes):
        return changes
    cipher = field_cipher_for(session, settings or get_settings())
    out: list[Change] = []
    for change in changes:
        if not touches(change):
            out.append(change)
            continue
        key = change.field.removeprefix("custom.")
        values: list[Any] = []
        for side, value in (("old", change.old), ("new", change.new)):
            if value is None:
                values.append(None)
                continue
            plain = (
                await cipher.open(CUSTOM, _binding(record_id, key), value)
                if is_sealed(value)
                else json.dumps(value, ensure_ascii=False, sort_keys=True)
            )
            values.append(
                None
                if plain is None
                else await cipher.seal(
                    CUSTOM,
                    history_binding(record_type, record_id, change.field, version, side),
                    plain,
                )
            )
        out.append(Change(change.field, values[0], values[1]))
    return out


async def sealing_keys(session: AsyncSession, entity: str) -> frozenset[str]:
    """The entity's custom fields whose values are written sealed now."""
    return frozenset(
        mark.key
        for mark in await metadata.field_marks(session, entity, retired=True)
        if mark.seal_state in SEALING_STATES
    )


@dataclass(frozen=True)
class Sealed:
    """Custom values as they are stored, and the blind-index changes to write after the save."""

    stored: dict[str, Any]
    # key -> (data key ID, digest) to write; key -> None to drop (the value was cleared).
    index: dict[str, tuple[uuid.UUID, str] | None] = field(default_factory=dict)


async def seal_custom(
    session: AsyncSession,
    record_id: uuid.UUID,
    custom: Mapping[str, Any] | None,
    *,
    sealed_keys: frozenset[str],
    settings: Settings | None = None,
) -> Sealed:
    """The values as stored: sealed for the keys in `sealed_keys`, with their index changes.

    A value already sealed is kept as it is (a save that did not change it): never re-sealed, so
    its index row stays too. A cleared value drops its row.
    """
    stored = dict(custom or {})
    if not sealed_keys:
        return Sealed(stored)
    cipher = field_cipher_for(session, settings or get_settings())
    index: dict[str, tuple[uuid.UUID, str] | None] = {}
    for key in sealed_keys:
        value = stored.get(key)
        if value is None:
            index[key] = None
            continue
        if is_sealed(value):
            continue
        plain = json.dumps(value, ensure_ascii=False, sort_keys=True)
        stored[key] = await cipher.seal(CUSTOM, _binding(record_id, key), plain)
        index[key] = await cipher.blind(CUSTOM, _blind_text(value))
    return Sealed(stored, index)


async def write_index(
    session: AsyncSession, record_id: uuid.UUID, index: Mapping[str, tuple[uuid.UUID, str] | None]
) -> None:
    """Apply a save's blind-index changes (after the record row exists)."""
    for key, entry in index.items():
        if entry is None:
            await session.execute(
                delete(WorkItemFieldIndex).where(
                    WorkItemFieldIndex.work_item_id == record_id,
                    WorkItemFieldIndex.field_key == key,
                )
            )
            continue
        key_id, digest = entry
        await session.execute(
            insert(WorkItemFieldIndex)
            .values(
                id=new_id(), work_item_id=record_id, field_key=key, key_id=key_id, digest=digest
            )
            .on_conflict_do_update(
                constraint="uq_work_item_field_index_place",
                set_={"key_id": key_id, "digest": digest},
            )
        )


def _blind_text(value: object) -> str:
    """What an exact-match filter compares: a text as itself, anything else as its JSON."""
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


async def not_plain_keys(session: AsyncSession, entity: str) -> frozenset[str]:
    """Fields that are sensitive or whose values are not all plain yet: never in search text."""
    return frozenset(
        mark.key
        for mark in await metadata.field_marks(session, entity, retired=True)
        if mark.sensitive or mark.seal_state != "plain"
    )


async def matching_records(
    session: AsyncSession,
    key: str,
    values: Iterable[object],
    *,
    settings: Settings | None = None,
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
    cipher = field_cipher_for(session, settings or get_settings())
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


NOT_FILTERABLE = "field_not_filterable_sealed"
NOTHING = "00000000-0000-0000-0000-000000000000"  # an ID no record has: "no match"


def _refused(name: str) -> ValidationFailed:
    return ValidationFailed(
        code="invalid_filter",
        errors=[
            FieldError(
                field="filter",
                code=NOT_FILTERABLE,
                message_key=f"errors.field.{NOT_FILTERABLE}",
                params={"field": name},
            )
        ],
    )


async def _seal_states(session: AsyncSession, entity: str) -> dict[str, str]:
    """`custom.<key>` -> seal state, for the entity's fields that are not plain."""
    return {
        f"custom.{mark.key}": mark.seal_state
        for mark in await metadata.field_marks(session, entity, retired=True)
        if mark.seal_state != "plain"
    }


class _SealedFilters:
    """Rewrites one list filter's sealed fields to their blind index (WP-057 S3b-2)."""

    def __init__(self, session: AsyncSession, states: Mapping[str, str]) -> None:
        self.session = session
        self.states = states

    async def ids(self, name: str, values: list[object]) -> list[str]:
        if self.states[name] != "sealed":
            raise _refused(name)
        found = await matching_records(self.session, name.removeprefix("custom."), values)
        return sorted(str(i) for i in found) or [NOTHING]

    async def node(self, node: Any) -> Any:  # noqa: ANN401 - one node of the DSL's JSON tree
        if not isinstance(node, dict):
            return node
        for group in ("and", "or"):
            if group in node:
                return {**node, group: [await self.node(child) for child in node[group]]}
        name = str(node.get("field"))
        if name not in self.states:
            return node
        op, value = node.get("op"), node.get("value")
        if op == "eq":
            return {"field": "id", "op": "in", "value": await self.ids(name, [value])}
        if op == "in" and isinstance(value, list):
            return {"field": "id", "op": "in", "value": await self.ids(name, list(value))}
        raise _refused(name)

    async def params(self, simple: dict[str, list[str]]) -> dict[str, list[str]]:
        kept: dict[str, list[str]] = {}
        matched: list[str] | None = None
        for name, values in simple.items():
            if name not in self.states:
                kept[name] = values
                continue
            found = await self.ids(name, list(values))
            matched = found if matched is None else sorted(set(matched) & set(found)) or [NOTHING]
        if matched is not None:
            kept["id"] = matched
        return kept


async def rewrite_sealed_filters(
    session: AsyncSession,
    entity: str,
    tree: Any,  # noqa: ANN401 - the filter DSL's parsed JSON tree
    simple: dict[str, list[str]],
) -> tuple[Any, dict[str, list[str]]]:
    """A list filter with every sealed field matched by its blind index (WP-057 S3b-2).

    `eq` and `in` on a sealed field become `id in [the records whose digest matches]`; any other
    operator on it, or any filter on a field still sealing or opening, is refused
    (`field_not_filterable_sealed`): a sealed value is never compared as stored text.
    """
    states = await _seal_states(session, entity)
    if not states:
        return tree, simple
    rewrite = _SealedFilters(session, states)
    rewritten = await rewrite.node(tree) if tree is not None else None
    return rewritten, await rewrite.params(simple)
