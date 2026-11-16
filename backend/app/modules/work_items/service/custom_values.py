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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import delete, exists, false, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import SESSION_SETTINGS_KEY, SESSION_TENANT_KEY
from app.core.errors import FieldError, ValidationFailed
from app.modules import metadata
from app.modules.work_items.domain import field_access as field_rules
from app.modules.work_items.infra.models import WorkItem, WorkItemFieldIndex
from app.shared.api.filters import FieldType, FilterField
from app.shared.crypto.codec import TEXT_PREFIX
from app.shared.db.models import utc_now
from app.shared.fields import Binding, field_cipher_for, purpose
from app.shared.history import Change, HistoryEntry
from app.shared.ids import new_id

CUSTOM = purpose(module="work_items", what="custom")
TABLE = "work_items"
SEALING_STATES = frozenset({"sealing", "sealed"})  # values are written sealed in these


@dataclass(frozen=True)
class Visible:
    """A record's custom values for one reader: what they may see, opened, and what did not open."""

    values: dict[str, Any]
    unreadable: frozenset[str] = field(default_factory=frozenset)


def _settings(session: AsyncSession, settings: Settings | None) -> Settings:
    """The running process's settings (the app's, a worker's); the global only for a script."""
    if settings is not None:
        return settings
    found = session.info.get(SESSION_SETTINGS_KEY)
    return found if isinstance(found, Settings) else get_settings()


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
    cipher = field_cipher_for(session, _settings(session, settings))
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


HIDDEN_LINE: dict[str, bool] = {"masked": True}  # the history page's "hidden" line (as MASKED)


async def open_sealed_changes(  # noqa: PLR0913 - one save's parts, explicit
    session: AsyncSession,
    record_type: str,
    record_id: uuid.UUID,
    version: int,
    changes: Sequence[Change],
    *,
    settings: Settings | None = None,
) -> list[Change]:
    """One save's changes with sealed values opened for their own cell (lane B's #520 review).

    Call it after the reader's own field rules have been applied, so only what they may see is
    opened. A line whose value does not open (moved, tampered with, or its key gone) becomes
    the hidden line (`HIDDEN_LINE` both sides): no `sx2:` text ever reaches a reader. Public as
    `work_items.open_sealed_changes` for other modules' history readers (the audit viewer).
    """
    if not any(is_sealed(c.old) or is_sealed(c.new) for c in changes):
        return list(changes)
    cipher = field_cipher_for(session, _settings(session, settings))

    async def side(change: Change, name: str, value: object) -> tuple[bool, object]:
        if not is_sealed(value):
            return True, value
        binding = history_binding(record_type, record_id, change.field, version, name)
        opened = await cipher.open(CUSTOM, binding, str(value))
        return (False, None) if opened is None else (True, json.loads(opened))

    shown: list[Change] = []
    for change in changes:
        old_ok, old = await side(change, "old", change.old)
        new_ok, new = await side(change, "new", change.new)
        if old_ok and new_ok:
            shown.append(Change(change.field, old, new))
        else:
            shown.append(Change(change.field, HIDDEN_LINE, HIDDEN_LINE))
    return shown


async def open_history(
    session: AsyncSession,
    record_type: str,
    record_id: uuid.UUID,
    entries: list[HistoryEntry],
    *,
    settings: Settings | None = None,
) -> list[HistoryEntry]:
    """History entries with sealed values opened per save (`open_sealed_changes`)."""
    return [
        replace(
            entry,
            changes=await open_sealed_changes(
                session, record_type, record_id, entry.version, entry.changes, settings=settings
            ),
        )
        for entry in entries
    ]


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
    cipher = field_cipher_for(session, _settings(session, settings))
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
    cipher = field_cipher_for(session, _settings(session, settings))
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
        index[key] = await cipher.blind(CUSTOM, _blind_text(value), field=f"custom.{key}")
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
                tenant_id=session.info[SESSION_TENANT_KEY].tenant_id,
                id=new_id(),
                work_item_id=record_id,
                field_key=key,
                key_id=key_id,
                digest=digest,
            )
            .on_conflict_do_update(
                constraint="uq_work_item_field_index_place",
                set_={"key_id": key_id, "digest": digest, "updated_at": utc_now()},
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


NOT_FILTERABLE = "field_not_filterable_sealed"
SEALED_PREFIX = "sealed."  # the rewritten filter's own field: one per sealed key matched


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
    """Rewrites one list filter's sealed fields to their blind index (WP-057 S3b-2).

    Each match becomes a field of its own, `sealed.<n>`: EXISTS a row of the index for this record,
    this key and one of the (data key, digest) pairs the values digest to. A subquery, never a list
    of IDs, so a common value costs no more than a rare one (lane A).
    """

    def __init__(self, session: AsyncSession, states: Mapping[str, str]) -> None:
        self.session = session
        self.states = states
        self.added: dict[str, FilterField] = {}

    async def field(self, name: str, values: list[object]) -> str:
        if self.states[name] != "sealed":
            raise _refused(name)
        key = name.removeprefix("custom.")
        key_ids = list(
            await self.session.scalars(
                select(WorkItemFieldIndex.key_id)
                .where(WorkItemFieldIndex.field_key == key)
                .distinct()
            )
        )
        cipher = field_cipher_for(self.session, _settings(self.session, None))
        pairs = [
            (key_id, digest)
            for value in values
            for key_id, digest in (
                await cipher.blind_under(CUSTOM, _blind_text(value), key_ids, field=name)
            ).items()
        ]
        index = WorkItemFieldIndex.__table__.alias()
        matches = (
            exists().where(
                index.c.work_item_id == WorkItem.id,
                index.c.field_key == key,
                tuple_(index.c.key_id, index.c.digest).in_(pairs),
            )
            if pairs
            else false()
        )
        added = f"{SEALED_PREFIX}{len(self.added)}"
        self.added[added] = FilterField(matches, FieldType.BOOLEAN)
        return added

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
            return {"field": await self.field(name, [value]), "op": "eq", "value": True}
        if op == "in" and isinstance(value, list):
            return {"field": await self.field(name, list(value)), "op": "eq", "value": True}
        raise _refused(name)

    async def params(self, simple: dict[str, list[str]]) -> dict[str, list[str]]:
        kept: dict[str, list[str]] = {}
        for name, values in simple.items():
            if name not in self.states:
                kept[name] = values
                continue
            kept[await self.field(name, list(values))] = ["true"]
        return kept


async def rewrite_sealed_filters(
    session: AsyncSession,
    entity: str,
    tree: Any,  # noqa: ANN401 - the filter DSL's parsed JSON tree
    simple: dict[str, list[str]],
    withheld: frozenset[str],
) -> tuple[Any, dict[str, list[str]], Mapping[str, FilterField]]:
    """A list filter with every sealed field matched by its blind index (WP-057 S3b-2).

    `eq` and `in` on a sealed field become an EXISTS on the index; any other operator on it, or
    any filter on a field still sealing or opening, is refused (`field_not_filterable_sealed`).
    A field the caller's roles withhold is left as it is, so it stays refused as any withheld
    field is: the index is never an oracle for a value they may not read (lane A).
    """
    states = {
        name: state
        for name, state in (await _seal_states(session, entity)).items()
        if name not in withheld
    }
    if not states:
        return tree, simple, {}
    rewrite = _SealedFilters(session, states)
    rewritten = await rewrite.node(tree) if tree is not None else None
    kept = await rewrite.params(simple)
    return rewritten, kept, rewrite.added
