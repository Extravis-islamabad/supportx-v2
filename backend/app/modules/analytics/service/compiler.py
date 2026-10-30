"""Report definition + reporting source → one SELECT (architecture.md §6.10, ADR-033).

The SELECT is the source's own scope-filtered list query with its columns replaced by groupings
and aggregates, the report's filter added, and nothing removed. Every name in the definition is
resolved against the source; user input becomes bound parameters through the filter DSL, never
SQL text. PostgreSQL dialect only for now; ClickHouse comes as a second dialect at V1 (ADR-008).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NoReturn

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    DateTime,
    Float,
    Select,
    and_,
    case,
    cast,
    column,
    func,
    literal,
    or_,
    select,
    true,
    values,
)
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.core.errors import FieldError, ValidationFailed
from app.modules.analytics.domain.definition import (
    AGE_BUCKETS,
    DateBucket,
    FlowSpec,
    ReportDefinition,
    ResultOrder,
)
from app.modules.analytics.domain.measures import FLOW, MeasureKind, MeasureSpec, measures_of
from app.shared.api.filters import FieldType, compile_filter
from app.shared.reporting import Dimension, DimensionKind, ReportingSource


@dataclass(frozen=True)
class CompiledGroup:
    """One grouping of the compiled query."""

    field: str
    dimension: Dimension
    bucket: DateBucket | None


@dataclass(frozen=True)
class CompiledReport:
    """What the runner executes and how to read its rows."""

    grouped: Select[Any]  # one row per group: keys..., measures...
    where: ColumnElement[bool]  # the report's filter (records exports reuse it)
    totals: Select[Any]  # one row: measures over every visible record
    groups: tuple[CompiledGroup, ...]
    measures: tuple[MeasureSpec, ...]


def _invalid(field: str, code: str) -> NoReturn:
    raise ValidationFailed(
        code="invalid_report",
        errors=[FieldError(field=field, code=code, message_key=f"errors.field.{code}")],
    )


def _check_records(definition: ReportDefinition, source: ReportingSource) -> None:
    """Chosen record columns and sort keys must be fields of the entity, each once."""
    fields = source.fields.fields
    for index, name in enumerate(definition.columns or []):
        if name not in fields:
            _invalid(f"columns[{index}]", "unknown_column")
    if definition.columns is not None and len(set(definition.columns)) != len(definition.columns):
        _invalid("columns", "duplicate_column")
    for index, key in enumerate(definition.sort):
        if key.field not in fields:
            _invalid(f"sort[{index}].field", "unknown_column")


def _filter_fields(tree: Any) -> list[str]:  # noqa: ANN401 - filter DSL JSON tree
    if isinstance(tree, dict):
        if "field" in tree:
            return [str(tree["field"])]
        nodes = tree.get("and") or tree.get("or") or []
        return [name for node in nodes for name in _filter_fields(node)]
    return []


def available_measures(source: ReportingSource) -> dict[str, MeasureSpec]:
    """Standard measures whose fields this source offers (others wait for their module's data)."""
    out: dict[str, MeasureSpec] = {}
    for code, spec in measures_of(source.entity).items():
        names = [n for n in (spec.field, spec.start, spec.end, spec.minus) if n is not None]
        names += _filter_fields(spec.where)
        if all(source.fields.get(n) is not None for n in names):
            out[code] = spec
    return out


def _aged(column: Any, now: datetime) -> ColumnElement[Any]:  # noqa: ANN401 - SQLAlchemy column
    # Index into AGE_BUCKETS (0 = youngest), so the natural order is the age order.
    whens = [
        (column > now - timedelta(days=high), index)
        for index, (_code, _low, high) in enumerate(AGE_BUCKETS)
        if high is not None
    ]
    return case(*whens, else_=len(AGE_BUCKETS) - 1)


def _bucketed(column: Any, bucket: DateBucket, zone: str, week_start: str) -> ColumnElement[Any]:  # noqa: ANN401 - SQLAlchemy column
    # The day, week... of the viewer's zone: `timezone(zone, t)` turns the UTC instant into the
    # zone's wall-clock time, which date_trunc then cuts (REQ-DSH-044 AC1, AC3). PostgreSQL weeks
    # start on Monday; a Sunday week (the tenant setting, Appendix A) is the Monday week of the
    # next day, moved back one day.
    local = func.timezone(zone, column)
    if bucket == DateBucket.WEEK and week_start == "sunday":
        day = timedelta(days=1)
        return func.date_trunc("week", local + day) - day
    return func.date_trunc(bucket.value, local)


def _column(source: ReportingSource, name: str | None, path: str) -> Any:  # noqa: ANN401 - SQLAlchemy column
    field = source.fields.get(name or "")
    if field is None:  # available_measures() keeps these out; a guard for programming errors
        _invalid(path, "measure_not_available")
    return field.column


def _measure_sql(
    spec: MeasureSpec, source: ReportingSource, now: datetime, path: str
) -> ColumnElement[Any]:
    if spec.kind in {MeasureKind.COUNT_WHERE, MeasureKind.RATE}:
        matched = func.count().filter(
            compile_filter(spec.where, source.fields, now=now, path=f"{path}.where")
        )
        if spec.kind == MeasureKind.COUNT_WHERE:
            return matched
        return case((func.count() == 0, None), else_=100.0 * cast(matched, Float) / func.count())
    if spec.kind == MeasureKind.AVERAGE:
        return func.avg(_column(source, spec.field, path))
    if spec.kind == MeasureKind.TOTAL:
        return func.sum(_column(source, spec.field, path))
    if spec.kind == MeasureKind.AVERAGE_DURATION:
        end = _column(source, spec.end, path)
        seconds: ColumnElement[Any] = func.extract("epoch", end - _column(source, spec.start, path))
        if spec.minus is not None:
            minus = _column(source, spec.minus, path)
            seconds = seconds - func.coalesce(minus, literal(0, BigInteger))
        return func.avg(seconds).filter(end.is_not(None))
    return func.count()


def _groups(definition: ReportDefinition, source: ReportingSource) -> list[CompiledGroup]:
    groups: list[CompiledGroup] = []
    seen: set[str] = set()
    for index, group in enumerate(definition.group_by):
        path = f"group_by[{index}]"
        field = source.fields.get(group.field)
        dimension = source.dimensions.get(group.field)
        if field is None or dimension is None:
            _invalid(f"{path}.field", "unknown_dimension")
        if group.field in seen:
            _invalid(f"{path}.field", "duplicate_dimension")
        seen.add(group.field)
        if field.array:
            # Multiple choice counts a record once per chosen value; grouping by it needs the
            # report to say so on screen. Not at MVP (REQ-RPT-013 covers single choice).
            _invalid(f"{path}.field", "dimension_not_groupable")
        is_date = dimension.kind == DimensionKind.DATETIME or field.type in {
            FieldType.DATETIME,
            FieldType.DATE,
        }
        if is_date and group.bucket is None:
            _invalid(f"{path}.bucket", "bucket_required")
        if not is_date and group.bucket is not None:
            _invalid(f"{path}.bucket", "bucket_not_allowed")
        groups.append(CompiledGroup(group.field, dimension, group.bucket))
    return groups


# A flow report reads these fields; an entity without them has no flow report (D-114).
FLOW_FIELDS = ("created_at", "resolved_at", "closed_at", "status_category", "status_changed_at")


def flow_buckets(flow: FlowSpec, now: datetime, week_start: str) -> list[tuple[datetime, datetime]]:
    """Wall-clock starts of the flow's buckets in `now`'s zone, oldest first, with their ends.

    The current (unfinished) bucket is the last; a bucket ends where the next one starts, so a
    daylight-saving change gives a 23- or 25-hour day (REQ-DSH-044 AC3).
    """
    local = now.replace(tzinfo=None)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    first_day = today - timedelta(days=flow.days - 1)
    if flow.bucket == "day":
        start, step = first_day, "day"
    elif flow.bucket == "week":
        weekday = first_day.weekday() if week_start == "monday" else (first_day.weekday() + 1) % 7
        start, step = first_day - timedelta(days=weekday), "week"
    else:
        start, step = first_day.replace(day=1), "month"
    out: list[tuple[datetime, datetime]] = []
    while start <= local:
        if step == "day":
            end = start + timedelta(days=1)
        elif step == "week":
            end = start + timedelta(days=7)
        else:
            index = start.year * 12 + start.month
            end = start.replace(year=index // 12, month=index % 12 + 1)
        out.append((start, end))
        start = end
    return out


def compile_flow(
    definition: ReportDefinition,
    source: ReportingSource,
    *,
    now: datetime,
    week_start: str = "monday",
) -> CompiledReport:
    """Per bucket: created, resolved and the backlog at its end, over the viewer's own rows."""
    flow = definition.flow
    if flow is None:  # pragma: no cover - compile_report() routes only flow reports here
        _invalid("flow", "flow_required")
    if definition.group_by:
        _invalid("group_by", "flow_without_groupings")
    for index, code in enumerate(definition.measures):
        if code not in FLOW:
            _invalid(f"measures[{index}]", "unknown_measure")
    if len(set(definition.measures)) != len(definition.measures):
        _invalid("measures", "duplicate_measure")
    fields = source.fields.fields
    if any(name not in fields for name in FLOW_FIELDS):
        _invalid("flow", "flow_not_available")
    zone = now.tzinfo
    buckets = flow_buckets(flow, now, week_start)
    # Wall-clock start (the grouping key the UI shows and drills by) and the bucket's UTC bounds.
    bounds = values(
        column("k", DateTime()),
        column("s", DateTime(timezone=True)),
        column("e", DateTime(timezone=True)),
        name="flow_buckets",
    ).data([(k, k.replace(tzinfo=zone), e.replace(tzinfo=zone)) for k, e in buckets])
    created = fields["created_at"].column
    resolved = fields["resolved_at"].column
    left = func.least(
        resolved,
        fields["closed_at"].column,
        case(
            (fields["status_category"].column == "canceled", fields["status_changed_at"].column),
            else_=None,
        ),
    )
    first, last = buckets[0][0].replace(tzinfo=zone), buckets[-1][1].replace(tzinfo=zone)
    where = (
        compile_filter(definition.filter_json(), source.fields, now=now)
        if definition.filter is not None
        else true()
    )
    rows = (
        source.rows.where(where, created < last, or_(left.is_(None), left >= first))
        .with_only_columns(
            created.label("c"), resolved.label("r"), left.label("l"), maintain_column_froms=True
        )
        .subquery("flow_rows")
    )
    measure_sql = {
        "flow_created": func.count(rows.c.c).filter(
            and_(rows.c.c >= bounds.c.s, rows.c.c < bounds.c.e)
        ),
        "flow_resolved": func.count(rows.c.r).filter(
            and_(rows.c.r >= bounds.c.s, rows.c.r < bounds.c.e)
        ),
        "flow_backlog": func.count(rows.c.c).filter(
            and_(rows.c.c < bounds.c.e, or_(rows.c.l.is_(None), rows.c.l >= bounds.c.e))
        ),
    }
    grouped = (
        select(
            bounds.c.k.label("k0"),
            *[measure_sql[code].label(f"m{i}") for i, code in enumerate(definition.measures)],
        )
        .select_from(bounds)
        .outerjoin(rows, true())
        .group_by(bounds.c.k)
        .order_by(bounds.c.k)
    )
    # Totals: created and resolved over the whole range; the backlog as it is at the end.
    per_bucket = grouped.subquery("flow_per_bucket")
    totals = select(
        *[
            (
                func.array_agg(aggregate_order_by(per_bucket.c[f"m{i}"], per_bucket.c.k0.desc()))[1]
                if code == "flow_backlog"
                else func.sum(per_bucket.c[f"m{i}"])
            )
            for i, code in enumerate(definition.measures)
        ]
    )
    group = CompiledGroup("created_at", source.dimensions["created_at"], DateBucket(flow.bucket))
    specs = tuple(FLOW[code] for code in definition.measures)
    return CompiledReport(grouped, where, totals, (group,), specs)


def _specs(definition: ReportDefinition, source: ReportingSource) -> list[MeasureSpec]:
    available = available_measures(source)
    specs: list[MeasureSpec] = []
    for index, code in enumerate(definition.measures):
        spec = available.get(code)
        if spec is None:
            _invalid(f"measures[{index}]", "unknown_measure")
        specs.append(spec)
    if len(set(definition.measures)) != len(definition.measures):
        _invalid("measures", "duplicate_measure")
    return specs


def compile_report(
    definition: ReportDefinition,
    source: ReportingSource,
    *,
    now: datetime,
    zone: str,
    week_start: str = "monday",
) -> CompiledReport:
    """Validate `definition` against `source` and build its queries (422 invalid_report)."""
    if definition.entity != source.entity:  # the caller picked the source by entity
        _invalid("entity", "unknown_entity")
    if definition.flow is not None:
        return compile_flow(definition, source, now=now, week_start=week_start)
    specs = _specs(definition, source)
    groups = _groups(definition, source)
    _check_records(definition, source)

    where = (
        compile_filter(definition.filter_json(), source.fields, now=now)
        if definition.filter is not None
        else true()
    )
    keys: list[ColumnElement[Any]] = []
    for index, group in enumerate(groups):
        column = source.fields.fields[group.field].column
        if group.bucket == DateBucket.AGE:
            expression = _aged(column, now)
        elif group.bucket is not None:
            expression = _bucketed(column, group.bucket, zone, week_start)
        else:
            expression = column
        keys.append(expression.label(f"k{index}"))
    values = [
        _measure_sql(spec, source, now, f"measures[{i}]").label(f"m{i}")
        for i, spec in enumerate(specs)
    ]
    base = source.rows.where(where)
    totals = base.with_only_columns(*values, maintain_column_froms=True)
    grouped = totals
    if keys:
        grouped = base.with_only_columns(*keys, *values, maintain_column_froms=True).group_by(
            *[k.element for k in keys]
        )
        grouped = grouped.order_by(*_order(definition.order, keys, values))
        limit = definition.limit
        if limit is not None:
            grouped = grouped.limit(limit + 1)  # one extra row tells the caller it was cut
    return CompiledReport(grouped, where, totals, tuple(groups), tuple(specs))


def _order(
    order: ResultOrder, keys: Sequence[ColumnElement[Any]], values: Sequence[ColumnElement[Any]]
) -> list[ColumnElement[Any]]:
    natural: list[ColumnElement[Any]] = [k.asc().nulls_last() for k in keys]
    if order == ResultOrder.KEY:
        return natural
    first = values[0]
    by_value = first.desc().nulls_last() if order == ResultOrder.VALUE_DESC else first.asc()
    return [by_value, *natural]


def drill_filter(
    definition: ReportDefinition,
    groups: Sequence[CompiledGroup],
    keys: Sequence[Any],
    *,
    bucket_bounds: Mapping[int, tuple[str, str]],
) -> Any:  # noqa: ANN401 - filter DSL JSON tree
    """The list filter behind one row (REQ-RPT-037): the report's filter AND each group's value.

    Opening the entity's list with it shows exactly the records counted in that row, because the
    list applies the same scope and the same DSL. `bucket_bounds[i]` is the [from, to) of a date
    bucket as ISO instants.
    """
    parts: list[Any] = []
    if definition.filter is not None:
        parts.append(definition.filter_json())
    for index, (group, key) in enumerate(zip(groups, keys, strict=True)):
        if group.bucket is not None:
            low, high = bucket_bounds[index]
            parts.extend(
                [
                    {"field": group.field, "op": "gte", "value": low},
                    {"field": group.field, "op": "lt", "value": high},
                ]
            )
        elif key is None:
            parts.append({"field": group.field, "op": "is_null"})
        else:
            parts.append({"field": group.field, "op": "eq", "value": key})
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {"and": parts}
