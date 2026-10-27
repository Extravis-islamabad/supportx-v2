"""The shared filter DSL (architecture.md §6.5, §10; WP-008).

One JSON grammar for list views, reports, business rules and SLAs:

    {"and": [
        {"field": "status", "op": "eq", "value": "active"},
        {"or": [
            {"field": "user_type", "op": "eq", "value": "technician"},
            {"field": "last_login_at", "op": "last_n_days", "value": 7}
        ]}
    ]}

A node is a condition `{field, op, value?}` or a group `{"and": [...]}` / `{"or": [...]}`.
Each resource publishes an allowlist of fields with a type; only those fields, and only the
operators that make sense for their type, are accepted. The compiler builds SQLAlchemy
expressions from columns and bound parameters: user input never becomes SQL text.

Limits (nesting depth, number of conditions, list sizes, string length, total size) are checked
while walking, before anything reaches the database. The first problem is reported as 422
`invalid_filter` with a field error whose `field` is the JSON path of the bad part, e.g.
`filter.and[1].or[0].op`.
"""

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, NoReturn

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, String, and_, func, not_, or_, true
from sqlalchemy.dialects.postgresql import array

from app.core.errors import FieldError, ParamValue, ValidationFailed

JsonValue = str | int | float | bool | None | list[Any] | dict[str, Any]


class FieldType(StrEnum):
    """Value type of a filterable field."""

    STRING = "string"
    ENUM = "enum"
    UUID = "uuid"
    DATETIME = "datetime"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DECIMAL = "decimal"  # WP-026: number fields with a fraction (custom fields)
    DATE = "date"  # WP-026: calendar dates without a time (custom fields)


class Op(StrEnum):
    """Every operator of the grammar."""

    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    BETWEEN = "between"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"
    # Relative dates (UTC; weeks start on Monday).
    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_WEEK = "this_week"
    LAST_WEEK = "last_week"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    LAST_N_DAYS = "last_n_days"
    NEXT_N_DAYS = "next_n_days"
    BEFORE_NOW = "before_now"
    AFTER_NOW = "after_now"


_EQUALITY = {Op.EQ, Op.NE, Op.IN, Op.NOT_IN, Op.IS_NULL, Op.IS_NOT_NULL}
_ORDERED = {Op.GT, Op.GTE, Op.LT, Op.LTE, Op.BETWEEN}
_RELATIVE = {
    Op.TODAY,
    Op.YESTERDAY,
    Op.THIS_WEEK,
    Op.LAST_WEEK,
    Op.THIS_MONTH,
    Op.LAST_MONTH,
    Op.LAST_N_DAYS,
    Op.NEXT_N_DAYS,
    Op.BEFORE_NOW,
    Op.AFTER_NOW,
}
OPERATORS: Mapping[FieldType, frozenset[Op]] = {
    FieldType.STRING: frozenset(_EQUALITY | {Op.CONTAINS, Op.STARTS_WITH}),
    FieldType.ENUM: frozenset(_EQUALITY),
    FieldType.UUID: frozenset(_EQUALITY),
    FieldType.DATETIME: frozenset(_EQUALITY | _ORDERED | _RELATIVE),
    FieldType.INTEGER: frozenset(_EQUALITY | _ORDERED),
    FieldType.BOOLEAN: frozenset({Op.EQ, Op.NE, Op.IS_NULL, Op.IS_NOT_NULL}),
    FieldType.DECIMAL: frozenset(_EQUALITY | _ORDERED),
    FieldType.DATE: frozenset(_EQUALITY | _ORDERED),
}
_NO_VALUE = {Op.IS_NULL, Op.IS_NOT_NULL} | (_RELATIVE - {Op.LAST_N_DAYS, Op.NEXT_N_DAYS})
_LIST = {Op.IN, Op.NOT_IN}
MAX_RELATIVE_DAYS = 3650
# Every field-error code the DSL and list parameters can return (labels: errors.field.<code>).
FIELD_ERROR_CODES = frozenset(
    {
        "filter_too_large",
        "invalid_json",
        "filter_too_deep",
        "invalid_node",
        "invalid_group",
        "too_many_conditions",
        "unknown_key",
        "unknown_field",
        "unknown_operator",
        "operator_not_allowed",
        "value_not_allowed",
        "invalid_value",
        "list_too_long",
        "invalid_range",
        "invalid_choice",
        "value_too_long",
        "unknown_parameter",
        "invalid_sort",
        "unknown_sort_field",
        "duplicate_sort_field",
        "out_of_range",
    }
)


@dataclass(frozen=True)
class FilterLimits:
    """Bounds that keep filters cheap to compile and to run."""

    max_chars: int = 8_000
    max_depth: int = 5
    max_conditions: int = 30
    max_list_items: int = 100
    max_string_length: int = 200


DEFAULT_LIMITS = FilterLimits()


@dataclass(frozen=True)
class FilterField:
    """One field a resource exposes for filtering and/or sorting."""

    column: Any  # an ORM column attribute (InstrumentedAttribute); Any: SQLAlchemy's generics
    type: FieldType
    values: frozenset[str] = frozenset()  # allowed codes for ENUM fields
    filterable: bool = True
    sortable: bool = False
    simple: bool = True  # also usable as `?name=value`
    # A JSONB array of codes (multiple choice): eq / in mean "includes", ne / not_in "excludes".
    array: bool = False


@dataclass(frozen=True)
class ResourceFields:
    """The allowlist of one list endpoint (filter, simple parameters and sort)."""

    name: str
    fields: Mapping[str, FilterField]
    id_column: Any  # tie-breaker for sorting and cursors; Any: SQLAlchemy column attribute
    default_sort: tuple[str, ...] = ("-created_at",)

    def get(self, name: str) -> FilterField | None:
        """A field by its public name."""
        return self.fields.get(name)


# --- schema published in OpenAPI (generated TypeScript types for the frontend) -------------------


class FilterCondition(BaseModel):
    """`{field, op, value?}`. Which fields and operators are allowed depends on the endpoint."""

    model_config = ConfigDict(extra="forbid", title="FilterCondition")

    field: str = Field(max_length=64)
    op: Op
    value: JsonValue = Field(
        default=None,
        description="Scalar; list for in/not_in; [low, high] for between; days for *_n_days.",
    )


class FilterAnd(BaseModel):
    """All of the nodes."""

    model_config = ConfigDict(extra="forbid", title="FilterAnd")

    and_: list["FilterNode"] = Field(alias="and", min_length=1)


class FilterOr(BaseModel):
    """Any of the nodes."""

    model_config = ConfigDict(extra="forbid", title="FilterOr")

    or_: list["FilterNode"] = Field(alias="or", min_length=1)


FilterNode = FilterCondition | FilterAnd | FilterOr
FilterAnd.model_rebuild()
FilterOr.model_rebuild()


class FilterExpression(BaseModel):
    """Wrapper whose schema is the DSL: one condition or group (sent as the `filter` parameter)."""

    model_config = ConfigDict(title="FilterExpression")

    root: FilterNode


# --- compiler ------------------------------------------------------------------------------------


def _fail(path: str, code: str, **params: ParamValue) -> NoReturn:
    raise ValidationFailed(
        code="invalid_filter",
        errors=[
            FieldError(field=path, code=code, message_key=f"errors.field.{code}", params=params)
        ],
    )


def _short(text: object) -> str:
    """User input echoed in an error: short and printable only."""
    return "".join(ch for ch in str(text) if ch.isprintable())[:64]


def _start_of_day(day: date, zone: tzinfo = UTC) -> datetime:
    """Midnight of `day` in `zone`, as a UTC instant."""
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def relative_range(
    op: Op, now: datetime, days: int | None = None
) -> tuple[datetime | None, datetime | None]:
    """[start, end) for a relative-date operator, as UTC instants.

    Calendar operators ("today", "this week" …) use the days of `now`'s time zone: pass
    `now` in the user's zone so "today" is the user's today (WP-012 follow-up); a UTC `now`
    gives UTC days.
    """
    zone = now.tzinfo or UTC
    today = now.date()
    monday = today - timedelta(days=today.weekday())

    def day(value: date) -> datetime:
        return _start_of_day(value, zone)

    ranges: dict[Op, Callable[[], tuple[datetime | None, datetime | None]]] = {
        Op.TODAY: lambda: (day(today), day(today + timedelta(days=1))),
        Op.YESTERDAY: lambda: (day(today - timedelta(days=1)), day(today)),
        Op.THIS_WEEK: lambda: (day(monday), day(monday + timedelta(days=7))),
        Op.LAST_WEEK: lambda: (day(monday - timedelta(days=7)), day(monday)),
        Op.THIS_MONTH: lambda: (day(_month_start(today)), day(_next_month(today))),
        Op.LAST_MONTH: lambda: (
            day(_month_start(_month_start(today) - timedelta(days=1))),
            day(_month_start(today)),
        ),
        Op.LAST_N_DAYS: lambda: (now - timedelta(days=days or 0), now),
        Op.NEXT_N_DAYS: lambda: (now, now + timedelta(days=days or 0)),
        Op.BEFORE_NOW: lambda: (None, now),
        Op.AFTER_NOW: lambda: (now, None),
    }
    return ranges[op]()


@dataclass
class _Compiler:
    resource: ResourceFields
    limits: FilterLimits
    now: datetime
    conditions: int = 0
    _coercers: dict[FieldType, Callable[[Any, str, FilterField], Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._coercers = {
            FieldType.STRING: self._string,
            FieldType.ENUM: self._enum,
            FieldType.UUID: self._uuid,
            FieldType.DATETIME: self._datetime,
            FieldType.INTEGER: self._integer,
            FieldType.BOOLEAN: self._boolean,
            FieldType.DECIMAL: self._decimal,
            FieldType.DATE: self._date,
        }

    # nodes

    def node(self, value: Any, path: str, depth: int) -> ColumnElement[bool]:  # noqa: ANN401 - untrusted JSON
        if depth > self.limits.max_depth:
            _fail(path, "filter_too_deep", max_depth=self.limits.max_depth)
        if not isinstance(value, dict):
            _fail(path, "invalid_node")
        if set(value) in ({"and"}, {"or"}):
            (kind,) = value
            children = value[kind]
            if not isinstance(children, list) or not children:
                _fail(f"{path}.{kind}", "invalid_group")
            parts = [
                self.node(child, f"{path}.{kind}[{i}]", depth + 1)
                for i, child in enumerate(children)
            ]
            return and_(*parts) if kind == "and" else or_(*parts)
        if "field" in value:
            return self.condition(value, path)
        _fail(path, "invalid_node")

    def condition(self, value: dict[str, Any], path: str) -> ColumnElement[bool]:
        self.conditions += 1
        if self.conditions > self.limits.max_conditions:
            _fail(path, "too_many_conditions", max_conditions=self.limits.max_conditions)
        unknown = set(value) - {"field", "op", "value"}
        if unknown:
            _fail(f"{path}.{_short(min(unknown))}", "unknown_key")
        name, op_name = value.get("field"), value.get("op")
        spec = self.resource.get(name) if isinstance(name, str) else None
        if spec is None or not spec.filterable:
            _fail(f"{path}.field", "unknown_field", field=_short(name))
        if not isinstance(op_name, str) or op_name not in Op.__members__.values():
            _fail(f"{path}.op", "unknown_operator", op=_short(op_name))
        op = Op(op_name)
        if op not in OPERATORS[spec.type]:
            _fail(f"{path}.op", "operator_not_allowed", op=op.value, type=spec.type.value)
        return self.expression(
            spec, op, value.get("value"), present="value" in value, path=f"{path}.value"
        )

    # expressions

    def expression(  # noqa: PLR0911 - one return per kind of condition, flat
        self,
        spec: FilterField,
        op: Op,
        raw: Any,  # noqa: ANN401 - untrusted JSON, typed by `spec` below
        *,
        present: bool,
        path: str,
    ) -> ColumnElement[bool]:
        """One condition's SQL expression (columns and bound parameters only)."""
        if op in _NO_VALUE:
            if present and raw is not None:
                _fail(path, "value_not_allowed", op=op.value)
            if spec.array:
                empty = or_(spec.column.is_(None), func.jsonb_array_length(spec.column) == 0)
                return empty if op is Op.IS_NULL else not_(empty)
            return self._no_value(spec.column, op)
        if spec.array:
            return self._array(spec, op, raw, path)
        if op in {Op.LAST_N_DAYS, Op.NEXT_N_DAYS}:
            if type(raw) is not int or not 1 <= raw <= MAX_RELATIVE_DAYS:
                _fail(path, "invalid_value", expected="days", max=MAX_RELATIVE_DAYS)
            return self._range(spec.column, *relative_range(op, self.now, raw))
        if op in _LIST:
            return self._list(spec, op, raw, path)
        if op is Op.BETWEEN:
            return self._between(spec, raw, path)
        return self._compare(spec.column, op, self._coerce(spec, raw, path))

    def _array(self, spec: FilterField, op: Op, raw: Any, path: str) -> ColumnElement[bool]:  # noqa: ANN401 - untrusted JSON
        if op in _LIST:
            if not isinstance(raw, list) or not raw:
                _fail(path, "invalid_value", expected="list")
            if len(raw) > self.limits.max_list_items:
                _fail(path, "list_too_long", max_items=self.limits.max_list_items)
            codes = [self._coerce(spec, item, f"{path}[{i}]") for i, item in enumerate(raw)]
            hit = spec.column.has_any(array(codes, type_=String))
        else:
            hit = spec.column.has_key(self._coerce(spec, raw, path))
        if op in {Op.EQ, Op.IN}:
            return hit  # type: ignore[no-any-return]  # Any column attribute
        # "does not include" also matches records without the field, like ne elsewhere.
        return or_(spec.column.is_(None), not_(hit))

    def _no_value(self, column: Any, op: Op) -> ColumnElement[bool]:  # noqa: ANN401 - column
        if op is Op.IS_NULL:
            return column.is_(None)  # type: ignore[no-any-return]  # Any column attribute
        if op is Op.IS_NOT_NULL:
            return column.is_not(None)  # type: ignore[no-any-return]  # Any column attribute
        return self._range(column, *relative_range(op, self.now))

    def _list(self, spec: FilterField, op: Op, raw: Any, path: str) -> ColumnElement[bool]:  # noqa: ANN401 - untrusted JSON
        if not isinstance(raw, list) or not raw:
            _fail(path, "invalid_value", expected="list")
        if len(raw) > self.limits.max_list_items:
            _fail(path, "list_too_long", max_items=self.limits.max_list_items)
        values = [self._coerce(spec, item, f"{path}[{i}]") for i, item in enumerate(raw)]
        if op is Op.IN:
            return spec.column.in_(values)  # type: ignore[no-any-return]  # Any column attribute
        # not_in (like ne) also matches NULL: "status is not X" includes rows without one.
        return or_(spec.column.is_(None), spec.column.not_in(values))

    def _between(self, spec: FilterField, raw: Any, path: str) -> ColumnElement[bool]:  # noqa: ANN401 - untrusted JSON
        if not isinstance(raw, list) or len(raw) != 2:  # noqa: PLR2004 - [low, high]
            _fail(path, "invalid_value", expected="[low, high]")
        low = self._coerce(spec, raw[0], f"{path}[0]")
        high = self._coerce(spec, raw[1], f"{path}[1]")
        if low > high:
            _fail(path, "invalid_range")
        return spec.column.between(low, high)  # type: ignore[no-any-return]  # Any column

    @staticmethod
    def _compare(column: Any, op: Op, value: Any) -> ColumnElement[bool]:  # noqa: ANN401 - column, typed value
        if op in {Op.CONTAINS, Op.STARTS_WITH}:
            # LIKE wildcards in the value are escaped: "50%" matches the text "50%" only.
            escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%" if op is Op.CONTAINS else f"{escaped}%"
            return column.ilike(pattern, escape="\\")  # type: ignore[no-any-return]  # Any column
        comparisons: dict[Op, Callable[[Any], ColumnElement[bool]]] = {
            Op.EQ: lambda v: column == v,
            Op.NE: column.is_distinct_from,  # matches NULL too, see _list
            Op.GT: lambda v: column > v,
            Op.GTE: lambda v: column >= v,
            Op.LT: lambda v: column < v,
            Op.LTE: lambda v: column <= v,
        }
        return comparisons[op](value)

    @staticmethod
    def _range(column: Any, start: datetime | None, end: datetime | None) -> ColumnElement[bool]:  # noqa: ANN401 - column attribute
        parts = []
        if start is not None:
            parts.append(column >= start)
        if end is not None:
            parts.append(column < end)
        return and_(true(), *parts)

    # values

    def _coerce(self, spec: FilterField, raw: Any, path: str) -> Any:  # noqa: ANN401 - typed by spec
        if raw is None:
            _fail(path, "invalid_value", expected=spec.type.value)
        return self._coercers[spec.type](raw, path, spec)

    def _string(self, raw: Any, path: str, _spec: FilterField) -> str:  # noqa: ANN401
        if not isinstance(raw, str):
            _fail(path, "invalid_value", expected="string")
        if len(raw) > self.limits.max_string_length:
            _fail(path, "value_too_long", max_length=self.limits.max_string_length)
        return raw

    def _enum(self, raw: Any, path: str, spec: FilterField) -> str:  # noqa: ANN401
        if not isinstance(raw, str) or raw not in spec.values:
            _fail(path, "invalid_choice", value=_short(raw))
        return raw

    @staticmethod
    def _uuid(raw: Any, path: str, _spec: FilterField) -> uuid.UUID:  # noqa: ANN401
        if not isinstance(raw, str):
            _fail(path, "invalid_value", expected="uuid")
        try:
            return uuid.UUID(raw)
        except ValueError:
            _fail(path, "invalid_value", expected="uuid")

    @staticmethod
    def _datetime(raw: Any, path: str, _spec: FilterField) -> datetime:  # noqa: ANN401
        if not isinstance(raw, str) or len(raw) > 40:  # noqa: PLR2004 - longest ISO 8601 form
            _fail(path, "invalid_value", expected="datetime")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            _fail(path, "invalid_value", expected="datetime")
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _integer(raw: Any, path: str, _spec: FilterField) -> int:  # noqa: ANN401
        if type(raw) is not int or abs(raw) > 2**63 - 1:
            _fail(path, "invalid_value", expected="integer")
        return raw

    @staticmethod
    def _boolean(raw: Any, path: str, _spec: FilterField) -> bool:  # noqa: ANN401
        if not isinstance(raw, bool):
            _fail(path, "invalid_value", expected="boolean")
        return raw

    @staticmethod
    def _decimal(raw: Any, path: str, _spec: FilterField) -> Decimal:  # noqa: ANN401
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            _fail(path, "invalid_value", expected="decimal")
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            _fail(path, "invalid_value", expected="decimal")
        if not value.is_finite() or abs(value) > Decimal(10) ** 15:
            _fail(path, "invalid_value", expected="decimal")
        return value

    @staticmethod
    def _date(raw: Any, path: str, _spec: FilterField) -> date:  # noqa: ANN401
        if not isinstance(raw, str) or len(raw) != 10:  # noqa: PLR2004 - YYYY-MM-DD
            _fail(path, "invalid_value", expected="date")
        try:
            return date.fromisoformat(raw)
        except ValueError:
            _fail(path, "invalid_value", expected="date")


def parse_filter_json(text: str, limits: FilterLimits = DEFAULT_LIMITS) -> JsonValue:
    """Decode the `filter` parameter; size is checked before parsing."""
    if len(text) > limits.max_chars:
        _fail("filter", "filter_too_large", max_chars=limits.max_chars)
    try:
        value: JsonValue = json.loads(text)
    except (ValueError, RecursionError):
        _fail("filter", "invalid_json")
    return value


def compile_filter(
    tree: JsonValue,
    resource: ResourceFields,
    *,
    now: datetime,
    limits: FilterLimits = DEFAULT_LIMITS,
    path: str = "filter",
) -> ColumnElement[bool]:
    """SQLAlchemy WHERE expression for a parsed filter (422 invalid_filter on any problem)."""
    return _Compiler(resource, limits, now).node(tree, path, 1)


def compile_simple(
    params: Mapping[str, Sequence[str]],
    resource: ResourceFields,
    *,
    limits: FilterLimits = DEFAULT_LIMITS,
) -> ColumnElement[bool]:
    """`?status=active&user_type=technician&user_type=requester`: eq for one value, in for many.

    Values arrive as strings and are converted with the field's type.
    """
    compiler = _Compiler(resource, limits, datetime.now(UTC))
    parts: list[ColumnElement[bool]] = []
    for name, raw_values in params.items():
        spec = resource.get(name)
        if spec is None or not spec.simple or not spec.filterable:
            _fail(name, "unknown_parameter", parameter=_short(name))
        values = [_from_query(spec.type, v) for v in raw_values]
        op = Op.EQ if len(values) == 1 else Op.IN
        parts.append(
            compiler.expression(
                spec, op, values[0] if op is Op.EQ else values, present=True, path=name
            )
        )
    return and_(true(), *parts) if parts else true()


def _from_query(field_type: FieldType, text: str) -> object:
    """Query-string text → the JSON type the compiler expects for this field type."""
    if field_type is FieldType.INTEGER:
        try:
            return int(text)
        except ValueError:
            return text  # rejected by the compiler with a typed error
    if field_type is FieldType.BOOLEAN:
        return {"true": True, "false": False}.get(text, text)
    if field_type is FieldType.DECIMAL:
        return text  # the decimal coercer reads text too
    return text
