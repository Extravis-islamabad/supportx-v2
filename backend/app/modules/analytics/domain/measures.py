"""Standard measures: one definition each, used by every report, widget and counter (REQ-RPT-004).

A measure is declared over field *names* of an entity's reporting source, never over columns, so
the owning module keeps its tables to itself and the meaning of "mean time to resolve" lives in
exactly one place. Filters inside a measure use the shared filter DSL. Labels:
`measure.<entity>.<code>` (name) and `measure.<entity>.<code>.help` (what it counts, shown next
to the number), in en, ar and ur.

Choices from parity file 09 Appendix A: response and resolution times are calendar time with
paused time excluded; SLA measures (business time) arrive with WP-025.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class MeasureKind(StrEnum):
    """How the number is worked out over the visible records."""

    COUNT = "count"  # records
    COUNT_WHERE = "count_where"  # records matching `where`
    RATE = "rate"  # share of records matching `where`, 0-100
    AVERAGE = "average"  # mean of a number field
    TOTAL = "total"  # sum of a number field
    AVERAGE_DURATION = "average_duration"  # mean seconds from `start` to `end`, minus `minus`


class Unit(StrEnum):
    """What the number means, so the UI formats it (count, duration, percent)."""

    COUNT = "count"
    SECONDS = "seconds"
    PERCENT = "percent"
    NUMBER = "number"


class Better(StrEnum):
    """Which direction is good, for trend colours on KPI tiles (REQ-DSH-008 AC2)."""

    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class MeasureSpec:
    """A named measure of one entity."""

    code: str
    kind: MeasureKind
    unit: Unit
    better: Better = Better.NEUTRAL
    field: str | None = None  # AVERAGE, TOTAL
    start: str | None = None  # AVERAGE_DURATION
    end: str | None = None  # AVERAGE_DURATION (records without an end are not averaged)
    minus: str | None = None  # AVERAGE_DURATION: a seconds field to subtract (paused time)
    where: Any = None  # COUNT_WHERE, RATE: a filter DSL tree over the same fields


_OPEN = {"field": "status_category", "op": "in", "value": ["open", "paused"]}

INCIDENT_MEASURES: tuple[MeasureSpec, ...] = (
    MeasureSpec("count", MeasureKind.COUNT, Unit.COUNT),
    MeasureSpec("open_count", MeasureKind.COUNT_WHERE, Unit.COUNT, Better.DOWN, where=_OPEN),
    MeasureSpec(
        "unassigned_open_count",
        MeasureKind.COUNT_WHERE,
        Unit.COUNT,
        Better.DOWN,
        where={
            "and": [
                _OPEN,
                {"field": "group_id", "op": "is_null"},
                {"field": "technician_id", "op": "is_null"},
            ]
        },
    ),
    # D-114 key numbers for dashboards (open records only, like the queue they describe).
    MeasureSpec(
        "overdue_count",
        MeasureKind.COUNT_WHERE,
        Unit.COUNT,
        Better.DOWN,
        where={"and": [_OPEN, {"field": "resolution_due_at", "op": "before_now"}]},
    ),
    MeasureSpec(
        "due_today_count",
        MeasureKind.COUNT_WHERE,
        Unit.COUNT,
        Better.DOWN,
        where={"and": [_OPEN, {"field": "resolution_due_at", "op": "today"}]},
    ),
    MeasureSpec(
        "awaiting_response_count",
        MeasureKind.COUNT_WHERE,
        Unit.COUNT,
        Better.DOWN,
        where={"and": [_OPEN, {"field": "first_responded_at", "op": "is_null"}]},
    ),
    MeasureSpec(
        "reopened_count",
        MeasureKind.COUNT_WHERE,
        Unit.COUNT,
        Better.DOWN,
        where={"field": "reopen_count", "op": "gt", "value": 0},
    ),
    MeasureSpec(
        "resolved_count",
        MeasureKind.COUNT_WHERE,
        Unit.COUNT,
        Better.UP,
        where={"field": "resolved_at", "op": "is_not_null"},
    ),
    MeasureSpec(
        "mean_time_to_assign",
        MeasureKind.AVERAGE_DURATION,
        Unit.SECONDS,
        Better.DOWN,
        start="created_at",
        end="first_assigned_at",
    ),
    MeasureSpec(
        "mean_time_to_respond",
        MeasureKind.AVERAGE_DURATION,
        Unit.SECONDS,
        Better.DOWN,
        start="created_at",
        end="first_responded_at",
        minus="paused_seconds",
    ),
    MeasureSpec(
        "mean_time_to_resolve",
        MeasureKind.AVERAGE_DURATION,
        Unit.SECONDS,
        Better.DOWN,
        start="created_at",
        end="resolved_at",
        minus="paused_seconds",
    ),
    MeasureSpec(
        "reopen_rate",
        MeasureKind.RATE,
        Unit.PERCENT,
        Better.DOWN,
        where={"field": "reopen_count", "op": "gt", "value": 0},
    ),
    MeasureSpec(
        "reassigned_count",
        MeasureKind.COUNT_WHERE,
        Unit.COUNT,
        Better.DOWN,
        where={"field": "reassignment_count", "op": "gt", "value": 0},
    ),
    MeasureSpec(
        "average_reassignments",
        MeasureKind.AVERAGE,
        Unit.NUMBER,
        Better.DOWN,
        field="reassignment_count",
    ),
)

# Flow measures (D-114): only in a flow report, which counts per bucket over three timestamps.
FLOW_MEASURES: tuple[MeasureSpec, ...] = (
    MeasureSpec("flow_created", MeasureKind.COUNT, Unit.COUNT),
    MeasureSpec("flow_resolved", MeasureKind.COUNT, Unit.COUNT, Better.UP),
    MeasureSpec("flow_backlog", MeasureKind.COUNT, Unit.COUNT, Better.DOWN),
)
FLOW: Mapping[str, MeasureSpec] = MappingProxyType({m.code: m for m in FLOW_MEASURES})

MEASURES: Mapping[str, Mapping[str, MeasureSpec]] = MappingProxyType(
    {"incident": MappingProxyType({m.code: m for m in INCIDENT_MEASURES})}
)


def measures_of(entity: str) -> Mapping[str, MeasureSpec]:
    """The standard measures of `entity` (empty when it has none yet)."""
    return MEASURES.get(entity, MappingProxyType({}))


def measure_problems(spec: MeasureSpec) -> list[str]:
    """Shape errors in a declaration (programming errors; checked by the domain tests)."""
    needs = {
        MeasureKind.COUNT: (),
        MeasureKind.COUNT_WHERE: ("where",),
        MeasureKind.RATE: ("where",),
        MeasureKind.AVERAGE: ("field",),
        MeasureKind.TOTAL: ("field",),
        MeasureKind.AVERAGE_DURATION: ("start", "end"),
    }[spec.kind]
    return [f"{spec.code}: {name} missing" for name in needs if getattr(spec, name) is None]
