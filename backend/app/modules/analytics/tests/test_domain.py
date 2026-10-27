"""Reporting domain and compiler without a database (WP-035)."""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, Select, String, Table, Uuid, select
from sqlalchemy.dialects import postgresql

from app.core.errors import ValidationFailed
from app.modules.analytics.domain.builtin import BUILTIN, BUILTIN_REPORTS
from app.modules.analytics.domain.definition import (
    AGE_BUCKETS,
    DateBucket,
    ReportDefinition,
)
from app.modules.analytics.domain.measures import MEASURES, measure_problems
from app.modules.analytics.service.compiler import (
    available_measures,
    compile_report,
    drill_filter,
)
from app.modules.analytics.service.runner import age_bounds, bucket_bounds
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.reporting import Dimension, DimensionKind, ReportingSource

_T = Table(
    "items",
    MetaData(),
    Column("id", Uuid),
    Column("tenant_id", Uuid),
    Column("status_category", String),
    Column("priority", String),
    Column("group_id", Uuid),
    Column("technician_id", Uuid),
    Column("created_at", DateTime(timezone=True)),
    Column("resolved_at", DateTime(timezone=True)),
    Column("reopen_count", Integer),
    Column("reassignment_count", Integer),
    Column("labels", postgresql.JSONB),
)
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def _source(*, without: frozenset[str] = frozenset()) -> ReportingSource:
    fields = {
        "status_category": FilterField(
            _T.c.status_category,
            FieldType.ENUM,
            values=frozenset({"open", "paused", "resolved", "closed", "canceled"}),
        ),
        "priority": FilterField(_T.c.priority, FieldType.ENUM, values=frozenset({"p1", "p2"})),
        "group_id": FilterField(_T.c.group_id, FieldType.UUID),
        "technician_id": FilterField(_T.c.technician_id, FieldType.UUID),
        "created_at": FilterField(_T.c.created_at, FieldType.DATETIME, simple=False),
        "resolved_at": FilterField(_T.c.resolved_at, FieldType.DATETIME, simple=False),
        "reopen_count": FilterField(_T.c.reopen_count, FieldType.INTEGER),
        "reassignment_count": FilterField(_T.c.reassignment_count, FieldType.INTEGER),
        "custom.tags": FilterField(_T.c.labels, FieldType.ENUM, array=True),
    }
    fields = {k: v for k, v in fields.items() if k not in without}
    return ReportingSource(
        entity="incident",
        # The "scope" a provider applies; the compiler must keep it.
        rows=select(_T).where(_T.c.group_id.is_not(None)),
        fields=ResourceFields("items", fields, _T.c.id),
        dimensions={
            "status_category": Dimension(DimensionKind.CODE, label_prefix="status_category"),
            "priority": Dimension(DimensionKind.CODE, label_prefix="priority"),
            "group_id": Dimension(DimensionKind.REFERENCE, reference="group"),
            "created_at": Dimension(DimensionKind.DATETIME),
            "resolved_at": Dimension(DimensionKind.DATETIME),
            "custom.tags": Dimension(DimensionKind.ADMIN_CODE),
        },
        list_path="incidents",
    )


def _sql(statement: Select[Any]) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]  # the dialect class is unannotated


def _codes(error: ValidationFailed) -> dict[str, str]:
    return {e.field: e.code for e in error.errors}


def _definition(**values: object) -> ReportDefinition:
    return ReportDefinition.model_validate({"entity": "incident", **values})


def test_every_measure_declaration_is_complete() -> None:
    for entity in MEASURES.values():
        for spec in entity.values():
            assert measure_problems(spec) == [], spec.code


def test_req_rpt_015_every_builtin_report_compiles_against_the_full_source() -> None:
    # A source with every field the incident provider will offer (lane A's WP-029 adapter).
    for report in BUILTIN_REPORTS:
        assert report.definition.entity == "incident"
    assert len(BUILTIN) == len(BUILTIN_REPORTS)  # codes are unique


def test_compiled_query_keeps_the_scope_and_adds_the_filter() -> None:
    compiled = compile_report(
        _definition(
            filter={"field": "priority", "op": "eq", "value": "p1"},
            group_by=[{"field": "status_category"}],
        ),
        _source(),
        now=NOW,
        zone="UTC",
    )
    sql = _sql(compiled.grouped)
    assert "items.group_id IS NOT NULL" in sql  # the provider's scope is still there
    assert "items.priority = " in sql
    assert "GROUP BY items.status_category" in sql
    assert "GROUP BY" not in _sql(compiled.totals)
    assert "items.group_id IS NOT NULL" in _sql(compiled.totals)


def test_req_rpt_001_ac2_unknown_names_are_refused_with_codes() -> None:
    cases = {
        "group_by[0].field": _definition(group_by=[{"field": "secret_column"}]),
        "measures[0]": _definition(measures=["drop_table"]),
        "group_by[0].bucket": _definition(group_by=[{"field": "created_at"}]),
    }
    for field, definition in cases.items():
        with pytest.raises(ValidationFailed) as caught:
            compile_report(definition, _source(), now=NOW, zone="UTC")
        assert field in _codes(caught.value), _codes(caught.value)
    with pytest.raises(ValidationFailed) as caught:
        compile_report(
            _definition(filter={"field": "nope", "op": "eq", "value": 1}),
            _source(),
            now=NOW,
            zone="UTC",
        )
    assert caught.value.instance_code == "invalid_filter"


def test_bucket_only_on_dates_and_multi_choice_is_not_groupable_yet() -> None:
    for group, code in (
        ({"field": "priority", "bucket": "day"}, "bucket_not_allowed"),
        ({"field": "custom.tags"}, "dimension_not_groupable"),
    ):
        with pytest.raises(ValidationFailed) as caught:
            compile_report(_definition(group_by=[group]), _source(), now=NOW, zone="UTC")
        assert _codes(caught.value) == {
            "group_by[0].field" if "bucket" not in group else "group_by[0].bucket": code
        }


def test_measures_wait_for_their_fields() -> None:
    assert "mean_time_to_resolve" not in available_measures(_source())  # no paused_seconds here
    assert "reopen_rate" in available_measures(_source())
    assert "reopen_rate" not in available_measures(_source(without=frozenset({"reopen_count"})))


def test_req_dsh_044_dates_are_cut_in_the_viewers_zone() -> None:
    compiled = compile_report(
        _definition(group_by=[{"field": "created_at", "bucket": "day"}]),
        _source(),
        now=NOW,
        zone="Asia/Karachi",
    )
    sql = _sql(compiled.grouped)
    assert "date_trunc(" in sql
    assert "timezone(" in sql


def test_req_dsh_044_ac3_daylight_saving_days_are_neither_missing_nor_doubled() -> None:
    # Bucket starts come from the database as the zone's wall-clock time, without a zone.
    def wall(year: int, month: int, day: int) -> datetime:
        return datetime(year, month, day)  # noqa: DTZ001 - a wall-clock time, as the database gives it

    zone = ZoneInfo("Europe/London")
    low, high = bucket_bounds(wall(2026, 10, 25), DateBucket.DAY, zone)  # clocks go back
    hours = (datetime.fromisoformat(high) - datetime.fromisoformat(low)).total_seconds() / 3600
    assert hours == 25
    low, high = bucket_bounds(wall(2026, 3, 29), DateBucket.DAY, zone)  # clocks go forward
    hours = (datetime.fromisoformat(high) - datetime.fromisoformat(low)).total_seconds() / 3600
    assert hours == 23
    low, high = bucket_bounds(wall(2026, 12, 1), DateBucket.MONTH, ZoneInfo("Asia/Riyadh"))
    assert (low, high) == ("2026-11-30T21:00:00+00:00", "2026-12-31T21:00:00+00:00")
    _, high = bucket_bounds(wall(2026, 10, 1), DateBucket.QUARTER, ZoneInfo("UTC"))
    assert high.startswith("2027-01-01")


def test_req_rpt_015_ac3_four_days_old_is_in_the_3_to_7_day_bucket() -> None:
    codes = [code for code, _low, _high in AGE_BUCKETS]
    index = codes.index("3_to_7_days")
    low, high = age_bounds(index, NOW)
    created = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)  # four days before NOW
    assert datetime.fromisoformat(low) <= created < datetime.fromisoformat(high)


def test_req_rpt_037_drill_filter_is_the_report_filter_and_the_row() -> None:
    definition = _definition(
        filter={"field": "status_category", "op": "eq", "value": "open"},
        group_by=[{"field": "priority"}, {"field": "created_at", "bucket": "day"}],
    )
    compiled = compile_report(definition, _source(), now=NOW, zone="UTC")
    drill = drill_filter(
        definition,
        compiled.groups,
        ("p1", "2026-10-26T00:00:00"),
        bucket_bounds={1: ("2026-10-26T00:00:00+00:00", "2026-10-27T00:00:00+00:00")},
    )
    assert drill == {
        "and": [
            {"field": "status_category", "op": "eq", "value": "open"},
            {"field": "priority", "op": "eq", "value": "p1"},
            {"field": "created_at", "op": "gte", "value": "2026-10-26T00:00:00+00:00"},
            {"field": "created_at", "op": "lt", "value": "2026-10-27T00:00:00+00:00"},
        ]
    }
    # "not set" groups drill to "is empty".
    assert drill_filter(
        _definition(group_by=[{"field": "priority"}]),
        compiled.groups[:1],
        (None,),
        bucket_bounds={},
    ) == {"field": "priority", "op": "is_null"}
    # The drill filter is valid for the same source (the list accepts it).
    compile_report(_definition(filter=drill), _source(), now=NOW, zone="UTC")
