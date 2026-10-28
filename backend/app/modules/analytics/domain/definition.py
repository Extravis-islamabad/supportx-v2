"""Report definitions: one versioned JSON format for built-in reports, saved reports and widgets.

See architecture.md §6.10 and REQ-RPT-011. A definition names an entity, a filter in the shared
filter DSL (the same JSON a list view saves, REQ-RPT-029), up to two groupings, up to four
measures and a chart. It never names a table or column: the compiler resolves every name
against the entity's reporting source and refuses anything else (REQ-RPT-001 AC2).
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.api.filters import FilterNode

SCHEMA_VERSION: Literal[1] = 1
MAX_GROUPS = 2
MAX_MEASURES = 4
# Records exports (WP-020d's list export reuses them): chosen fields and sort.
MAX_COLUMNS = 40
MAX_SORT = 3
MAX_GROUP_ROWS = 500  # rows of a grouped result shown at once (Appendix A: viewer page sizes)


class DateBucket(StrEnum):
    """How a date grouping is cut, in the viewer's time zone (REQ-DSH-044)."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    AGE = "age"  # how long ago, in AGE_BUCKETS (ageing reports, REQ-RPT-015)


# Ageing buckets in days, [from, to) (parity file 09 Appendix A); codes label `age_bucket.<code>`.
AGE_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("under_1_day", 0, 1),
    ("1_to_3_days", 1, 3),
    ("3_to_7_days", 3, 7),
    ("7_to_30_days", 7, 30),
    ("over_30_days", 30, None),
)


class ChartType(StrEnum):
    """MVP chart types (REQ-RPT-044 AC3); the rest follow at V1."""

    BAR = "bar"
    STACKED_BAR = "stacked_bar"
    LINE = "line"
    AREA = "area"
    DOUGHNUT = "doughnut"
    GAUGE = "gauge"
    KPI = "kpi"
    TABLE = "table"


class ResultOrder(StrEnum):
    """Order of grouped rows."""

    KEY = "key"  # by the grouping value (dates oldest first, codes in their natural order)
    VALUE_DESC = "value_desc"  # largest first measure first (top-N)
    VALUE_ASC = "value_asc"


class RecordSort(BaseModel):
    """One sort key of a records export: a field, ascending unless `desc`."""

    model_config = ConfigDict(extra="forbid", title="RecordSort")

    field: str = Field(max_length=64)
    desc: bool = False


class ReportGroupBy(BaseModel):
    """One grouping: a field of the entity; date fields also need a bucket."""

    model_config = ConfigDict(extra="forbid", title="ReportGroupBy")

    field: str = Field(max_length=64)
    bucket: DateBucket | None = None


class ReportDefinition(BaseModel):
    """A report as stored and as sent to `POST /reports/run`."""

    model_config = ConfigDict(extra="forbid", title="ReportDefinition")

    schema_version: Literal[1] = SCHEMA_VERSION
    entity: str = Field(max_length=40)
    filter: FilterNode | None = None
    group_by: list[ReportGroupBy] = Field(default_factory=list, max_length=MAX_GROUPS)
    measures: list[str] = Field(
        default_factory=lambda: ["count"], min_length=1, max_length=MAX_MEASURES
    )
    order: ResultOrder = ResultOrder.KEY
    limit: int | None = Field(default=None, ge=1, le=MAX_GROUP_ROWS)
    chart: ChartType = ChartType.BAR
    percent: bool = False  # show shares of the total instead of numbers (REQ-DSH-009 AC2)
    # Records exports only: which fields to list, in order (built-in names and custom.<key>;
    # default: the groupings, then the entity's usual list), and how to sort them.
    columns: list[str] | None = Field(default=None, min_length=1, max_length=MAX_COLUMNS)
    sort: list[RecordSort] = Field(default_factory=list, max_length=MAX_SORT)

    def filter_json(self) -> Any:  # noqa: ANN401 - the filter DSL's JSON tree
        """The filter as the DSL compiler reads it (`and`/`or` keys, not Python names)."""
        if self.filter is None:
            return None
        return self.filter.model_dump(by_alias=True, exclude_none=False)
