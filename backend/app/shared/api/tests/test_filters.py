"""Filter DSL: grammar, allowlist, limits and safe compilation. Pure, no database."""

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Uuid
from sqlalchemy.dialects import postgresql

from app.core.errors import ValidationFailed
from app.shared.api.filters import (
    FieldType,
    FilterField,
    FilterLimits,
    Op,
    ResourceFields,
    compile_filter,
    compile_simple,
    parse_filter_json,
    relative_range,
)
from tooling import timing

table = Table(
    "things",
    MetaData(),
    Column("id", Uuid),
    Column("title", String),
    Column("status", String),
    Column("owner_id", Uuid),
    Column("priority", Integer),
    Column("created_at", DateTime(timezone=True)),
)
c = table.c
THINGS = ResourceFields(
    name="things",
    fields={
        "title": FilterField(c.title, FieldType.STRING, sortable=True),
        "status": FilterField(c.status, FieldType.ENUM, values=frozenset({"open", "closed"})),
        "owner_id": FilterField(c.owner_id, FieldType.UUID),
        "priority": FilterField(c.priority, FieldType.INTEGER, sortable=True),
        "created_at": FilterField(c.created_at, FieldType.DATETIME, sortable=True, simple=False),
    },
    id_column=c.id,
)
NOW = datetime(2026, 10, 23, 15, 30, tzinfo=UTC)  # a Friday


def sql(tree: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:  # noqa: ANN401 - JSON input
    compiled = compile_filter(tree, THINGS, now=NOW, **kwargs).compile(
        dialect=postgresql.dialect()  # type: ignore[no-untyped-call]  # SQLAlchemy dialect factory
    )
    return str(compiled), dict(compiled.params)


def problem(tree: Any, **kwargs: Any) -> tuple[str, str, dict[str, Any]]:  # noqa: ANN401
    with pytest.raises(ValidationFailed) as caught:
        compile_filter(tree, THINGS, now=NOW, **kwargs)
    assert caught.value.instance_code == "invalid_filter"
    (error,) = caught.value.errors
    return error.field, error.code, error.params


def cond(field: str, op: str, value: Any = None, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    node: dict[str, Any] = {"field": field, "op": op}
    if value is not None:
        node["value"] = value
    return {**node, **extra}


# --- what it compiles to -------------------------------------------------------------------------


def test_groups_and_operators_compile_to_bound_parameters() -> None:
    text, params = sql(
        {
            "and": [
                cond("status", "in", ["open", "closed"]),
                {"or": [cond("priority", "gte", 3), cond("title", "contains", "printer")]},
                cond("created_at", "between", ["2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z"]),
            ]
        }
    )
    assert "things.status IN" in text
    assert "things.priority >= %(priority_1)s" in text
    assert "things.title ILIKE" in text
    assert "BETWEEN" in text
    assert " OR " in text
    assert params["priority_1"] == 3
    assert "%printer%" in params.values()


@pytest.mark.parametrize(
    "attack",
    [
        "x'; DROP TABLE users; --",
        "' OR 1=1 --",
        "\\'); SELECT pg_sleep(10); --",
        "%' OR title LIKE '%",
    ],
)
def test_sql_in_values_only_ever_becomes_a_parameter(attack: str) -> None:
    text, params = sql({"or": [cond("title", "eq", attack), cond("title", "contains", attack)]})
    assert attack not in text
    assert "DROP" not in text
    assert "pg_sleep" not in text
    assert attack in params.values()


def test_like_wildcards_in_values_are_escaped() -> None:
    _, params = sql(cond("title", "starts_with", "50%_off\\"))
    assert "50\\%\\_off\\\\%" in params.values()


def test_ne_and_not_in_include_nulls() -> None:
    assert "IS DISTINCT FROM" in sql(cond("status", "ne", "open"))[0]
    text, _ = sql(cond("status", "not_in", ["open"]))
    assert "things.status IS NULL OR" in text
    assert "NOT IN" in text


def test_null_checks_take_no_value() -> None:
    assert "things.owner_id IS NULL" in sql(cond("owner_id", "is_null"))[0]
    assert "IS NOT NULL" in sql(cond("owner_id", "is_not_null"))[0]
    assert problem(cond("owner_id", "is_null", "x")) == (
        "filter.value",
        "value_not_allowed",
        {"op": "is_null"},
    )


@pytest.mark.parametrize(
    ("op", "days", "start", "end"),
    [
        (Op.TODAY, None, datetime(2026, 10, 23, tzinfo=UTC), datetime(2026, 10, 24, tzinfo=UTC)),
        (
            Op.YESTERDAY,
            None,
            datetime(2026, 10, 22, tzinfo=UTC),
            datetime(2026, 10, 23, tzinfo=UTC),
        ),
        (
            Op.THIS_WEEK,
            None,
            datetime(2026, 10, 19, tzinfo=UTC),
            datetime(2026, 10, 26, tzinfo=UTC),
        ),
        (
            Op.LAST_WEEK,
            None,
            datetime(2026, 10, 12, tzinfo=UTC),
            datetime(2026, 10, 19, tzinfo=UTC),
        ),
        (Op.THIS_MONTH, None, datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)),
        (Op.LAST_MONTH, None, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)),
        (Op.LAST_N_DAYS, 7, datetime(2026, 10, 16, 15, 30, tzinfo=UTC), NOW),
        (Op.NEXT_N_DAYS, 2, NOW, datetime(2026, 10, 25, 15, 30, tzinfo=UTC)),
        (Op.BEFORE_NOW, None, None, NOW),
        (Op.AFTER_NOW, None, NOW, None),
    ],
)
def test_relative_dates(
    op: Op, days: int | None, start: datetime | None, end: datetime | None
) -> None:
    assert relative_range(op, NOW, days) == (start, end)
    _, params = sql(cond("created_at", op.value, days))
    assert (start in params.values()) is (start is not None)
    assert (end in params.values()) is (end is not None)


def test_last_month_in_january_wraps_to_december() -> None:
    january = datetime(2027, 1, 10, tzinfo=UTC)
    assert relative_range(Op.LAST_MONTH, january) == (
        datetime(2026, 12, 1, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
    )


def test_naive_datetimes_are_utc() -> None:
    _, params = sql(cond("created_at", "gte", "2026-10-01T08:00:00"))
    assert datetime(2026, 10, 1, 8, tzinfo=UTC) in params.values()


# --- what it refuses -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tree", "path", "code"),
    [
        (cond("password_hash", "eq", "x"), "filter.field", "unknown_field"),
        (cond("title; DROP TABLE x", "eq", "x"), "filter.field", "unknown_field"),
        (cond("title", "regex", ".*"), "filter.op", "unknown_operator"),
        (cond("title", "gt", "a"), "filter.op", "operator_not_allowed"),
        (cond("status", "contains", "op"), "filter.op", "operator_not_allowed"),
        (cond("priority", "eq", "3"), "filter.value", "invalid_value"),
        (cond("priority", "eq", value=True), "filter.value", "invalid_value"),
        (cond("priority", "eq", 3.5), "filter.value", "invalid_value"),
        (cond("status", "eq", "deleted"), "filter.value", "invalid_choice"),
        (cond("owner_id", "eq", "not-a-uuid"), "filter.value", "invalid_value"),
        (cond("created_at", "gt", "yesterday"), "filter.value", "invalid_value"),
        (cond("title", "eq", {"$ne": 1}), "filter.value", "invalid_value"),
        (cond("title", "eq", ["a"]), "filter.value", "invalid_value"),
        (cond("title", "in", "a"), "filter.value", "invalid_value"),
        (cond("title", "in", []), "filter.value", "invalid_value"),
        (cond("priority", "between", [5, 1]), "filter.value", "invalid_range"),
        (cond("priority", "between", [1]), "filter.value", "invalid_value"),
        (cond("created_at", "last_n_days", 0), "filter.value", "invalid_value"),
        (cond("created_at", "last_n_days", 99999), "filter.value", "invalid_value"),
        (cond("title", "eq", None), "filter.value", "invalid_value"),
        ({"field": "title", "op": "eq", "value": "a", "sql": "1=1"}, "filter.sql", "unknown_key"),
        ({"and": []}, "filter.and", "invalid_group"),
        ({"and": [cond("title", "eq", "a")], "or": []}, "filter", "invalid_node"),
        ({"not": cond("title", "eq", "a")}, "filter", "invalid_node"),
        ([cond("title", "eq", "a")], "filter", "invalid_node"),
        ("title = 'a'", "filter", "invalid_node"),
        (
            {"and": [cond("title", "eq", "a"), {"or": [cond("x", "eq", 1)]}]},
            "filter.and[1].or[0].field",
            "unknown_field",
        ),
    ],
)
def test_bad_filters_point_at_the_problem(tree: Any, path: str, code: str) -> None:  # noqa: ANN401
    assert problem(tree)[:2] == (path, code)


def test_value_and_list_limits() -> None:
    limits = FilterLimits(max_list_items=3, max_string_length=5)
    assert problem(cond("title", "in", ["a", "b", "c", "d"]), limits=limits)[1] == "list_too_long"
    assert problem(cond("title", "eq", "toolong"), limits=limits)[1] == "value_too_long"


def test_deep_nesting_is_refused_at_the_limit_without_recursing_further() -> None:
    tree: Any = cond("title", "eq", "a")
    for _ in range(5000):  # far deeper than Python's default recursion limit would allow
        tree = {"and": [tree]}
    started = time.perf_counter()
    path, code, params = problem(tree)
    assert time.perf_counter() - started < 0.05
    assert code == "filter_too_deep"
    assert params == {"max_depth": 5}
    assert path == "filter" + ".and[0]" * 5


def test_too_many_conditions_is_refused() -> None:
    tree = {"or": [cond("priority", "eq", i) for i in range(31)]}
    assert problem(tree)[1:] == ("too_many_conditions", {"max_conditions": 30})


def test_raw_text_size_and_json_validity_are_checked_before_parsing() -> None:
    huge = json.dumps({"or": [cond("title", "eq", "x" * 100)] * 200})
    started = time.perf_counter()
    with pytest.raises(ValidationFailed) as too_large:
        parse_filter_json(huge)
    assert time.perf_counter() - started < 0.01
    assert too_large.value.errors[0].code == "filter_too_large"
    with pytest.raises(ValidationFailed) as broken:
        parse_filter_json('{"field": "title",')
    assert broken.value.errors[0].code == "invalid_json"
    assert parse_filter_json('{"field": "title", "op": "eq", "value": "a"}') == cond(
        "title", "eq", "a"
    )


def test_error_params_never_echo_long_or_unprintable_input() -> None:
    _, code, params = problem(cond("x" * 500 + "\u0000\n", "eq", 1))
    assert code == "unknown_field"
    assert params["field"] == "x" * 64


# --- simple query parameters ---------------------------------------------------------------------


def test_simple_parameters_become_eq_or_in() -> None:
    owner = uuid.uuid4()
    compiled = compile_simple(
        {"status": ["open"], "priority": ["1", "2"], "owner_id": [str(owner)]}, THINGS
    ).compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]  # SQLAlchemy factory
    text = str(compiled)
    assert "things.status = " in text
    assert "things.priority IN" in text
    assert owner in compiled.params.values()


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"colour": ["red"]}, "unknown_parameter"),
        ({"created_at": ["2026-10-01"]}, "unknown_parameter"),  # not a simple field
        ({"priority": ["high"]}, "invalid_value"),
        ({"status": ["gone"]}, "invalid_choice"),
    ],
)
def test_simple_parameters_are_validated_like_the_dsl(
    params: dict[str, list[str]], code: str
) -> None:
    with pytest.raises(ValidationFailed) as caught:
        compile_simple(params, THINGS)
    assert caught.value.errors[0].code == code


@pytest.mark.timing
def test_compiling_a_full_size_filter_is_fast() -> None:
    tree = {
        "and": [
            {"or": [cond("priority", "gte", i), cond("title", "contains", f"t{i}")]}
            for i in range(15)
        ]
    }
    # The best of several batches, in this process's CPU time: compiling is pure computation, so
    # its fastest batch is its real cost. CI runs four test workers on two vCPUs with coverage
    # tracing; one batch there absorbs cache and frequency noise from its neighbours (5.8 ms
    # against 0.2 ms locally), the fastest of five does not.
    batches, runs = 5, 40
    timings = []
    for _ in range(batches):
        started = time.process_time()
        for _ in range(runs):
            compile_filter(tree, THINGS, now=NOW)
        timings.append(time.process_time() - started)
    per_filter_ms = min(timings) / runs * 1000
    print(f"\n[perf] filter_compile: conditions=30 depth=3 ms_per_filter={per_filter_ms:.3f}")  # noqa: T201
    # 5 ms, strictly in the nightly run (no coverage, its own machine); ten times that in pull
    # requests, where coverage tracing and shared 2-vCPU runners cost several times over.
    timing.record("filter_compile_ms", per_filter_ms)
    assert per_filter_ms < timing.limit(5)
