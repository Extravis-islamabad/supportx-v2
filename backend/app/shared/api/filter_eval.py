"""The shared filter DSL evaluated in memory (WP-025, D-115 D6).

SLA policy conditions are checked against a record **inside its save**, before the row reaches
the database, so they cannot be a WHERE clause. This evaluator gives the same answer as
`compile_filter` (the SQL compiler) for every filter the compiler accepts; a property test in
`tests/db/test_filter_eval_parity.py` holds the two together on generated records and filters.

- Validation is the compiler's own: `evaluate` first compiles the tree (no database involved),
  so a filter is refused with exactly the same 422 field error in both places.
- SQL meaning, kept on purpose:
  - a comparison with a missing value is false (`NULL = x` is not true), except `ne` and
    `not_in`, which match missing values ("status is not X" includes records without one);
  - `contains` / `starts_with` ignore case (ILIKE), with no wildcards;
  - `between` includes both ends; date ranges are [start, end);
  - multiple-choice (array) fields: `eq` / `in` mean "includes", `ne` / `not_in` "excludes"
    (and match a missing value); `is_null` matches missing or empty.
"""

import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.shared.api.filters import (
    DEFAULT_LIMITS,
    LIST_OPERATORS,
    NO_VALUE_OPERATORS,
    FieldType,
    FilterField,
    FilterLimits,
    JsonValue,
    Op,
    ResourceFields,
    compile_filter,
    relative_range,
)

Record = Mapping[str, Any]


def evaluate(  # noqa: PLR0913 - the compiler's options, keyword-only
    tree: JsonValue,
    resource: ResourceFields,
    record: Record,
    *,
    now: datetime,
    limits: FilterLimits = DEFAULT_LIMITS,
    path: str = "filter",
) -> bool:
    """Whether `record` (field name -> value) matches the filter (422 for an invalid filter)."""
    compile_filter(tree, resource, now=now, limits=limits, path=path)  # the same validation
    return _node(tree, resource, record, now)


def _node(value: Any, resource: ResourceFields, record: Record, now: datetime) -> bool:  # noqa: ANN401 - validated JSON
    if "and" in value:
        return all(_node(child, resource, record, now) for child in value["and"])
    if "or" in value:
        return any(_node(child, resource, record, now) for child in value["or"])
    spec = resource.fields[value["field"]]
    return _condition(spec, Op(value["op"]), value.get("value"), record.get(value["field"]), now)


def _condition(spec: FilterField, op: Op, raw: Any, actual: Any, now: datetime) -> bool:  # noqa: ANN401, PLR0911 - validated JSON, one return per kind
    if spec.array:
        return _array(op, raw, actual)
    if op is Op.IS_NULL:
        return actual is None
    if op is Op.IS_NOT_NULL:
        return actual is not None
    if op in NO_VALUE_OPERATORS or op in {Op.LAST_N_DAYS, Op.NEXT_N_DAYS}:
        return _relative(op, raw, actual, now)
    if op in LIST_OPERATORS:
        return _listed(spec, op, raw, actual)
    if op is Op.NE:
        return actual is None or _typed(spec, actual) != _typed(spec, raw)
    if actual is None:
        return False
    return _compare(spec, op, raw, actual)


def _relative(op: Op, raw: Any, actual: Any, now: datetime) -> bool:  # noqa: ANN401 - validated JSON
    days = raw if op in {Op.LAST_N_DAYS, Op.NEXT_N_DAYS} else None
    start, end = relative_range(op, now, days)
    if actual is None:
        return False
    moment = _instant(actual)
    return (start is None or moment >= start) and (end is None or moment < end)


def _listed(spec: FilterField, op: Op, raw: Any, actual: Any) -> bool:  # noqa: ANN401 - validated JSON
    values = {_typed(spec, item) for item in raw}
    if op is Op.IN:
        return actual is not None and _typed(spec, actual) in values
    return actual is None or _typed(spec, actual) not in values


def _compare(spec: FilterField, op: Op, raw: Any, actual: Any) -> bool:  # noqa: ANN401 - validated JSON
    if op is Op.BETWEEN:
        low, high = _typed(spec, raw[0]), _typed(spec, raw[1])
        return bool(low <= _typed(spec, actual) <= high)
    if op in {Op.CONTAINS, Op.STARTS_WITH}:
        text, needle = str(actual).lower(), str(raw).lower()
        return needle in text if op is Op.CONTAINS else text.startswith(needle)
    return _COMPARE[op](_typed(spec, actual), _typed(spec, raw))


def _array(op: Op, raw: Any, actual: Any) -> bool:  # noqa: ANN401 - validated JSON
    held = set(actual or ())
    if op is Op.IS_NULL:
        return not held
    if op is Op.IS_NOT_NULL:
        return bool(held)
    wanted = set(raw) if op in LIST_OPERATORS else {raw}
    hit = bool(held & wanted)
    if op in {Op.EQ, Op.IN}:
        return hit
    return actual is None or not hit


_COMPARE: Mapping[Op, Callable[[Any, Any], bool]] = {
    Op.EQ: lambda a, b: bool(a == b),
    Op.GT: lambda a, b: bool(a > b),
    Op.GTE: lambda a, b: bool(a >= b),
    Op.LT: lambda a, b: bool(a < b),
    Op.LTE: lambda a, b: bool(a <= b),
}


def _instant(value: Any) -> datetime:  # noqa: ANN401 - a datetime or its ISO text
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _typed(spec: FilterField, value: Any) -> Any:  # noqa: ANN401, PLR0911 - one return per type
    """A record value or a filter value in the comparable Python type of the field."""
    if spec.type is FieldType.UUID:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    if spec.type is FieldType.DATETIME:
        return _instant(value)
    if spec.type is FieldType.DECIMAL:
        return Decimal(str(value))
    if spec.type is FieldType.DATE:
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    if spec.type is FieldType.INTEGER:
        return int(value)
    if spec.type is FieldType.BOOLEAN:
        return bool(value)
    return str(value)  # STRING, ENUM
