"""Custom field definitions: admin writes and what other modules use (WP-026; D-087).

Admin writes (settings.manage, audited in the routes): add, change (never the type), retire and
bring back, delete while never used, reorder, ask for an index. Each write records field history
and a `metadata.custom_field.changed` event in the same transaction; open screens reload live.

Other modules (work items now; assets, knowledge, people later) never read these tables: they
call `definitions`, `clean`, `mark_used` and `filter_fields` from the module's public interface.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.identity_access import display_names, user_names
from app.modules.metadata.domain.fields import (
    FIELDS_PER_ENTITY,
    HELP_MAX,
    LABEL_MAX,
    Choice,
    ChoiceDisplay,
    CustomFieldEntity,
    Definition,
    FieldType,
    IndexFailure,
    IndexState,
    Problem,
    Validation,
    clean_values,
    definition_problems,
    empty,
    is_key,
    key_from,
    labels_problems,
    missing_required,
    search_text,
)
from app.modules.metadata.domain.fields import (
    problem_params as field_problem_params,
)
from app.modules.metadata.events import CustomFieldChanged
from app.modules.metadata.infra.expressions import value_expression
from app.modules.metadata.infra.models import CustomField
from app.shared.api.filters import FieldType as FilterType
from app.shared.api.filters import FilterField
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, explain_conflict, record_changes

RECORD_TYPE = "custom_field"


class CustomFieldRepository(Repository[CustomField]):
    """Custom fields of the session's tenant."""

    model = CustomField


def _problems(problems: Sequence[Problem]) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(field=f"body.{p}", code=c, message_key=f"errors.field.{c}")
            for p, c in problems
        ]
    )


def _entity(value: str) -> CustomFieldEntity:
    if value not in set(CustomFieldEntity):
        raise NotFound(code="custom_field_entity_not_found")
    return CustomFieldEntity(value)


# --- rows ↔ domain --------------------------------------------------------------------------------


def _decimal(value: Any) -> Decimal | None:  # noqa: ANN401 - JSON
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def validation_of(raw: Mapping[str, Any] | None) -> Validation:
    """Stored validation (numbers as text) as the domain type."""
    raw = raw or {}
    return Validation(
        required=bool(raw.get("required", False)),
        min=_decimal(raw.get("min")),
        max=_decimal(raw.get("max")),
        min_length=raw.get("min_length"),
        max_length=raw.get("max_length"),
        pattern=raw.get("pattern") or None,
    )


def validation_json(rules: Validation) -> dict[str, Any]:
    """The domain type as stored (only what is set)."""
    out: dict[str, Any] = {"required": rules.required}
    for name in ("min", "max"):
        value = getattr(rules, name)
        if value is not None:
            out[name] = str(value)
    for name in ("min_length", "max_length", "pattern"):
        value = getattr(rules, name)
        if value is not None:
            out[name] = value
    return out


def choices_of(raw: Sequence[Mapping[str, Any]] | None) -> list[Choice]:
    """Stored choices as the domain type."""
    return [
        Choice(
            code=str(c.get("code")),
            labels=dict(c.get("labels") or {}),
            retired=bool(c.get("retired")),
        )
        for c in raw or []
    ]


def definition_of(row: CustomField) -> Definition:
    """A row as rules see it."""
    return Definition(
        key=row.key,
        type=FieldType(row.field_type),
        choices=tuple(choices_of(row.choices)),
        validation=validation_of(row.validation),
        retired=row.retired_at is not None,
    )


# --- reading --------------------------------------------------------------------------------------


async def list_fields(
    session: AsyncSession, entity: str, *, removed: bool = False
) -> list[CustomField]:
    """Every field of an entity in display order, retired ones included (marked).

    `removed`: also fields removed while in use, for history and old values (AC4).
    """
    kind = _entity(entity)
    query = select(CustomField).where(CustomField.entity == kind)
    if not removed:
        query = query.where(CustomField.deleted_at.is_(None))
    return list(
        await session.scalars(
            query.order_by(CustomField.sort_order, CustomField.created_at, CustomField.id)
        )
    )


async def definitions(session: AsyncSession, entity: str) -> dict[str, Definition]:
    """Every field of an entity by key (retired ones too: old values keep their rules)."""
    return {row.key: definition_of(row) for row in await list_fields(session, entity)}


async def _get(session: AsyncSession, field_id: uuid.UUID) -> CustomField:
    found = await session.scalar(
        select(CustomField).where(CustomField.id == field_id, CustomField.deleted_at.is_(None))
    )
    if found is None:
        raise NotFound(code="custom_field_not_found")
    return found


async def _same_version(session: AsyncSession, row: CustomField, expected: int) -> None:
    """409 when the field was saved since `expected`, naming who changed what (QA BUG-01)."""
    if row.version == expected:
        return
    raise await explain_conflict(
        session,
        Conflict(
            code="version_conflict",
            params={"expected_version": expected, "current_version": row.version},
        ),
        record_type=RECORD_TYPE,
        record_id=row.id,
        names=lambda ids: display_names(session, ids),
    )


async def editors(session: AsyncSession, rows: Sequence[CustomField]) -> dict[uuid.UUID, str]:
    """Who saved each field last, by display name (an open editor says "changed by")."""
    ids = sorted({str(r.updated_by) for r in rows if r.updated_by is not None})
    names = await user_names(session, ids) if ids else {}
    return {r.id: names[str(r.updated_by)] for r in rows if str(r.updated_by) in names}


# --- admin writes ---------------------------------------------------------------------------------


def _clean_text(raw: Any) -> dict[str, str] | None:  # noqa: ANN401 - JSON
    if raw is None:
        return None
    kept = {k: " ".join(str(v).split()) for k, v in dict(raw).items() if v is not None}
    kept = {k: v for k, v in kept.items() if v}
    return kept or None


def _choices_in(
    raw: Sequence[Mapping[str, Any]] | None, existing: Sequence[Choice]
) -> tuple[list[Choice], list[Problem]]:
    """Choices as sent: known codes keep theirs; new ones get a code from their English label.

    A choice that existed and is no longer sent is kept, retired: values on records keep their
    label (REQ-ADM-043 rule for every pick list).
    """
    problems: list[Problem] = []
    taken = {c.code for c in existing}
    out: list[Choice] = []
    sent: set[str] = set()
    for i, item in enumerate(raw or []):
        labels = _clean_text(item.get("labels"))
        problems += labels_problems(labels, f"choices[{i}].labels", required=True, limit=LABEL_MAX)
        code = item.get("code")
        if code is None:
            code = key_from((labels or {}).get("en", "choice"), taken | sent)
        elif not isinstance(code, str) or (code not in taken and not is_key(code)):
            problems.append((f"choices[{i}].code", "invalid_choice"))
            continue
        sent.add(code)
        out.append(Choice(code=code, labels=labels or {}, retired=bool(item.get("retired"))))
    out += [
        Choice(code=c.code, labels=c.labels, retired=True) for c in existing if c.code not in sent
    ]
    return out, problems


def _choices_json(choices: Sequence[Choice]) -> list[dict[str, Any]]:
    return [{"code": c.code, "labels": dict(c.labels), "retired": c.retired} for c in choices]


def _validation_in(raw: Mapping[str, Any] | None) -> tuple[Validation, list[Problem]]:
    raw = raw or {}
    problems: list[Problem] = []
    numbers: dict[str, Decimal | None] = {}
    for name in ("min", "max"):
        value = raw.get(name)
        numbers[name] = None if value is None else _decimal(value)
        if value is not None and numbers[name] is None:
            problems.append((f"validation.{name}", "invalid_value"))
    lengths: dict[str, int | None] = {}
    for name in ("min_length", "max_length"):
        value = raw.get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            problems.append((f"validation.{name}", "invalid_value"))
            value = None
        lengths[name] = value
    pattern = raw.get("pattern")
    if pattern is not None and (not isinstance(pattern, str) or len(pattern) > 200):  # noqa: PLR2004 - a sane pattern
        problems.append(("validation.pattern", "invalid_pattern"))
        pattern = None
    return (
        Validation(
            required=bool(raw.get("required", False)),
            min=numbers["min"],
            max=numbers["max"],
            min_length=lengths["min_length"],
            max_length=lengths["max_length"],
            pattern=pattern or None,
        ),
        problems,
    )


async def _changed(  # noqa: PLR0913 - the row, its change and context
    session: AsyncSession,
    row: CustomField,
    changes: list[Change],
    *,
    kind: str,
    change: str,
    source: Source,
) -> None:
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.id,
        version=row.version,
        kind=kind,  # type: ignore[arg-type]  # "created", "updated" or "deleted": ChangeKind values
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        CustomFieldChanged(
            custom_field_id=row.id,
            entity=row.entity,
            key=row.key,
            change=change,
            changed_fields=sorted(c.field for c in changes),
        ),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def create_field(
    session: AsyncSession, entity: str, values: Mapping[str, Any], *, source: Source
) -> CustomField:
    """A new field at the end of the entity's list; its key comes from the English name."""
    kind_of_entity = _entity(entity)
    existing = await list_fields(session, kind_of_entity)
    if len(existing) >= FIELDS_PER_ENTITY:
        raise Conflict(code="custom_field_limit_reached", params={"limit": FIELDS_PER_ENTITY})
    problems: list[Problem] = []
    field_type = values.get("field_type")
    if field_type not in set(FieldType):
        raise _problems([("field_type", "invalid_choice")])
    kind = FieldType(field_type)
    labels = _clean_text(values.get("labels"))
    problems += labels_problems(labels, "labels", required=True, limit=LABEL_MAX)
    help_text = _clean_text(values.get("help"))
    problems += labels_problems(help_text, "help", required=False, limit=HELP_MAX)
    choices, codes = _choices_in(values.get("choices"), [])
    problems += codes
    rules, codes = _validation_in(values.get("validation"))
    problems += codes
    display = values.get("display") or ChoiceDisplay.LIST
    if display not in set(ChoiceDisplay):
        problems.append(("display", "invalid_choice"))
    english = (labels or {}).get("en", "").casefold()
    if any((row.labels or {}).get("en", "").casefold() == english for row in existing):
        problems.append(("labels", "duplicate_name"))
    currency = values.get("currency")
    problems += definition_problems(
        kind, choices=choices, validation=rules, default=values.get("default"), currency=currency
    )
    if problems:
        raise _problems(problems)
    # Removed fields keep their key: records and history still hold values under it.
    taken = {row.key for row in await list_fields(session, kind_of_entity, removed=True)}
    key = values.get("key") or key_from((labels or {})["en"], taken)
    if not is_key(key) or key in taken:
        raise _problems([("key", "invalid_key")])
    probe = Definition(key=key, type=kind, choices=tuple(choices), validation=rules)
    default = None
    if not empty(values.get("default")):
        default = clean_values({key: probe}, {key: values["default"]})[0].get(key)
    order = await session.scalar(
        select(func.coalesce(func.max(CustomField.sort_order), -1) + 1).where(
            CustomField.entity == kind_of_entity
        )
    )
    row = CustomField(
        entity=kind_of_entity,
        key=key,
        field_type=kind,
        labels=labels,
        help=help_text,
        choices=_choices_json(choices),
        display=display,
        default_value=default,
        validation=validation_json(rules),
        currency=currency,
        sort_order=int(order or 0),
    )
    await CustomFieldRepository(session).add(row)
    await _changed(
        session,
        row,
        [Change("labels", None, labels), Change("field_type", None, kind.value)],
        kind="created",
        change="created",
        source=source,
    )
    return row


async def update_field(  # noqa: C901, PLR0912, PLR0915 - one rule per setting, flat
    session: AsyncSession,
    field_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> CustomField:
    """Labels, help, choices, display, default, validation, currency; retire or bring back.

    The type and the key never change: a field of another type is a new field (D-087).
    """
    row = await _get(session, field_id)
    await _same_version(session, row, expected_version)
    if "field_type" in values and values["field_type"] != row.field_type:
        raise _problems([("field_type", "type_cannot_change")])
    if "key" in values and values["key"] != row.key:
        raise _problems([("key", "key_cannot_change")])
    kind = FieldType(row.field_type)
    current = definition_of(row)
    problems: list[Problem] = []
    changes: dict[str, Any] = {}
    if "labels" in values:
        labels = _clean_text(values["labels"])
        problems += labels_problems(labels, "labels", required=True, limit=LABEL_MAX)
        english = (labels or {}).get("en", "").casefold()
        others = [r for r in await list_fields(session, row.entity) if r.id != row.id]
        if any((r.labels or {}).get("en", "").casefold() == english for r in others):
            problems.append(("labels", "duplicate_name"))
        changes["labels"] = labels
    if "help" in values:
        help_text = _clean_text(values["help"])
        problems += labels_problems(help_text, "help", required=False, limit=HELP_MAX)
        changes["help"] = help_text
    choices = list(current.choices)
    if "choices" in values:
        choices, codes = _choices_in(values["choices"], current.choices)
        problems += codes
        changes["choices"] = _choices_json(choices)
    rules = current.validation
    if "validation" in values:
        rules, codes = _validation_in(values["validation"])
        problems += codes
        changes["validation"] = validation_json(rules)
    if "display" in values:
        if values["display"] not in set(ChoiceDisplay):
            problems.append(("display", "invalid_choice"))
        changes["display"] = values["display"]
    currency = values.get("currency", row.currency)
    if "currency" in values:
        changes["currency"] = currency
    default = values.get("default", row.default_value)
    problems += definition_problems(
        kind, choices=choices, validation=rules, default=default, currency=currency
    )
    if "default" in values and not problems:
        probe = Definition(key=row.key, type=kind, choices=tuple(choices), validation=rules)
        changes["default_value"] = (
            None
            if empty(default)
            else clean_values({row.key: probe}, {row.key: default})[0].get(row.key)
        )
    if "retired" in values:
        retired = bool(values["retired"])
        if retired != (row.retired_at is not None):
            changes["retired_at"] = datetime.now(UTC) if retired else None
    if "sort_order" in values:
        changes["sort_order"] = int(values["sort_order"])
    if problems:
        raise _problems(problems)
    before = {k: getattr(row, k) for k in changes}
    changes = {k: v for k, v in changes.items() if before[k] != v}
    if not changes:
        return row
    updated = await CustomFieldRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )

    def shown(name: str, value: Any) -> Any:  # noqa: ANN401 - JSON values
        return value is not None if name == "retired_at" else value

    change = "updated"
    if "retired_at" in changes:
        change = "retired" if changes["retired_at"] is not None else "restored"
    await _changed(
        session,
        updated,
        [
            Change(
                "retired" if k == "retired_at" else "default" if k == "default_value" else k,
                shown(k, before[k]),
                shown(k, v),
            )
            for k, v in changes.items()
        ],
        kind="updated",
        change=change,
        source=source,
    )
    return updated


async def delete_field(
    session: AsyncSession,
    field_id: uuid.UUID,
    *,
    expected_version: int,
    confirmed: bool,
    source: Source,
) -> None:
    """Remove a field; one records hold values in needs `confirmed` (REQ-INC-014 AC4).

    Its values stay on the records and in their history, hidden from forms, lists and filters;
    its key is never reused.
    """
    row = await _get(session, field_id)
    await _same_version(session, row, expected_version)
    if row.first_used_at is not None and not confirmed:
        raise Conflict(code="custom_field_in_use", params={"key": row.key})
    removed = await CustomFieldRepository(session).soft_delete(
        row.id, expected_version=expected_version
    )
    await _changed(
        session,
        removed,
        [Change(field="deleted", old=None, new=True)],
        kind="deleted",
        change="deleted",
        source=source,
    )


async def reorder(
    session: AsyncSession, entity: str, ids: Sequence[uuid.UUID], *, source: Source
) -> list[CustomField]:
    """The new order of every field of an entity (forms and pickers follow it at once)."""
    rows = await list_fields(session, entity)
    if sorted(str(r.id) for r in rows) != sorted(str(i) for i in ids) or len(set(ids)) != len(ids):
        raise _problems([("ids", "order_must_list_every_value")])
    by_id = {r.id: r for r in rows}
    for order, field_id in enumerate(ids):
        row = by_id[field_id]
        if row.sort_order != order:
            await session.execute(
                update(CustomField)
                .where(CustomField.id == field_id)
                .values(sort_order=order, version=CustomField.version + 1)
            )
    session.expire_all()
    fresh = await list_fields(session, entity)
    if fresh:
        await _changed(
            session,
            fresh[0],
            [Change("order", [str(r.id) for r in rows], [str(i) for i in ids])],
            kind="updated",
            change="reordered",
            source=source,
        )
    return fresh


async def request_index(
    session: AsyncSession, field_id: uuid.UUID, *, expected_version: int, source: Source
) -> CustomField:
    """Ask for an index on a field filtered often (REQ-INC-014 AC2).

    The index worker picks it up within a minute or so (D-088); a failed one can be asked again.
    """
    row = await _get(session, field_id)
    await _same_version(session, row, expected_version)
    if row.index_state in {IndexState.PENDING, IndexState.BUILDING, IndexState.ACTIVE}:
        return row
    updated = await CustomFieldRepository(session).update(
        row.id,
        expected_version=expected_version,
        changes={"index_state": IndexState.PENDING, "index_error": None},
    )
    await _changed(
        session,
        updated,
        [Change("index_state", row.index_state, IndexState.PENDING.value)],
        kind="updated",
        change="index_requested",
        source=source,
    )
    return updated


async def indexes_waiting(session: AsyncSession) -> list[CustomField]:
    """The tenant's fields whose index is pending, or was building when a worker stopped.

    Called only by the worker holding the index lock, so a "building" field here belongs to a run
    that ended (crash, restart) and is built again.
    """
    rows = await session.scalars(
        select(CustomField)
        .where(
            CustomField.index_state.in_([IndexState.PENDING, IndexState.BUILDING]),
            CustomField.deleted_at.is_(None),
        )
        .order_by(CustomField.entity, CustomField.sort_order)
    )
    return list(rows)


async def index_progress(
    session: AsyncSession,
    field_id: uuid.UUID,
    state: IndexState,
    failure: IndexFailure | None = None,
) -> None:
    """The worker's progress on one field: building, then active or failed with the reason."""
    row = await _get(session, field_id)
    if row.index_state == state and row.index_error == failure:
        return
    updated = await CustomFieldRepository(session).update(
        row.id,
        expected_version=row.version,
        changes={"index_state": state, "index_error": failure},
    )
    await _changed(
        session,
        updated,
        [Change("index_state", row.index_state, state.value)],
        kind="updated",
        change=f"index_{state.value}",
        source="system",
    )


# --- what other modules use -----------------------------------------------------------------------


async def clean(  # noqa: PLR0913 - the values and how they are being saved
    session: AsyncSession,
    entity: str,
    values: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None = None,
    creating: bool,
    defaults: bool = False,
) -> tuple[dict[str, Any], list[Problem]]:
    """Checked values by key (None = cleared) and problems as (`custom.<key>`, code).

    `defaults`: on create, fields with a default and no value sent start from it.
    """
    known = await definitions(session, entity)
    rows = {r.key: r for r in await list_fields(session, entity)} if defaults else {}
    sent = dict(values)
    if defaults:
        for key, row in rows.items():
            if key not in sent and row.default_value is not None and row.retired_at is None:
                sent[key] = row.default_value
    cleaned, problems = clean_values(known, sent, current=current)
    problems += missing_required(known, cleaned, creating=creating, current=current)
    people = {
        key: value
        for key, value in cleaned.items()
        if value is not None
        and known[key].type == FieldType.PERSON
        and value != (current or {}).get(key)
    }
    if people:
        found = await user_names(session, list(people.values()))
        problems += [(f"custom.{k}", "user_not_found") for k, v in people.items() if v not in found]
    return cleaned, problems


async def problem_params(
    session: AsyncSession, entity: str, problems: Sequence[Problem]
) -> dict[str, dict[str, str | int]]:
    """The limits value problems name, by `custom.<key>` (for the caller's field errors)."""
    known = await definitions(session, entity)
    found: dict[str, dict[str, str | int]] = {}
    for path, code in problems:
        found_def = known.get(path.removeprefix("custom."))
        if found_def is not None and (params := field_problem_params(found_def, code)):
            found[path] = params
    return found


async def mark_used(session: AsyncSession, entity: str, keys: Sequence[str]) -> None:
    """Stamp fields that now hold a value somewhere: from then on they can only be retired."""
    if not keys:
        return
    await session.execute(
        update(CustomField)
        .where(
            CustomField.entity == _entity(entity),
            CustomField.key.in_(list(keys)),
            CustomField.first_used_at.is_(None),
            CustomField.deleted_at.is_(None),
        )
        .values(first_used_at=datetime.now(UTC))
    )


_FILTER_TYPES: Mapping[FieldType, FilterType] = {
    FieldType.INTEGER: FilterType.DECIMAL,
    FieldType.DECIMAL: FilterType.DECIMAL,
    FieldType.CURRENCY: FilterType.DECIMAL,
    FieldType.DATE: FilterType.DATE,
    FieldType.DATETIME: FilterType.DATETIME,
    FieldType.CHOICE: FilterType.ENUM,
    FieldType.MULTI_CHOICE: FilterType.ENUM,
    FieldType.YES_NO: FilterType.BOOLEAN,
    FieldType.PERSON: FilterType.UUID,
}


async def filter_fields(session: AsyncSession, entity: str, table: str) -> dict[str, FilterField]:
    """`custom.<key>` filter fields of an entity whose values live in `table.custom`."""
    out: dict[str, FilterField] = {}
    for row in await list_fields(session, entity):
        kind = FieldType(row.field_type)
        if kind == FieldType.PERSON:
            column = value_expression(table, row.key, FieldType.TEXT)
        else:
            column = value_expression(table, row.key, kind)
        out[f"custom.{row.key}"] = FilterField(
            column,
            _FILTER_TYPES.get(kind, FilterType.STRING),
            values=frozenset(c["code"] for c in row.choices),
            sortable=kind not in {FieldType.MULTI_CHOICE, FieldType.LONG_TEXT},
            simple=True,
            array=kind == FieldType.MULTI_CHOICE,
        )
    return out


async def text_for_search(
    session: AsyncSession, entity: str, values: Mapping[str, Any]
) -> str | None:
    """The free text of a record's custom values (what search reads), or None."""
    return search_text(await definitions(session, entity), values) or None
