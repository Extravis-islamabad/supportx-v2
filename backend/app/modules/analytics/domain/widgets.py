"""The dashboard widget catalogue (D-114): what "Add widget" offers, grouped by module and section.

Each entry is a widget template: a report definition, a reference to a built-in report, or a
short list of records, with a default size. Every built-in report is in the catalogue too. All
of them run through the same engine (or the entity's own list), so each viewer sees only what
they may see (REQ-DSH-028).

Titles and descriptions are labels: `dashboard_widget.<code>` and
`dashboard_widget.<code>.description`; sections `widget_section.<code>`. Entries whose data
arrives with a later work package (SLA, approvals) are listed under "coming later" with the
package that brings them, and cannot be added yet.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.modules.analytics.domain.builtin import BUILTIN_REPORTS, INCIDENTS
from app.modules.analytics.domain.dashboard import ME, MY_GROUPS, DashboardBody, Widget

KEY_NUMBERS = "key_numbers"
OPEN_WORK = "open_work"
QUEUES = "queues"
TRENDS = "trends"
TIME = "time"
REPORTS = "reports"
COMING_LATER = "coming_later"
SECTIONS = (KEY_NUMBERS, OPEN_WORK, QUEUES, TRENDS, TIME, REPORTS, COMING_LATER)

KPI_SIZE = (3, 2)
CHART_SIZE = (6, 4)
LIST_SIZE = (6, 4)

_OPEN = {"field": "status_category", "op": "in", "value": ["open", "paused"]}
_MINE = {"field": "technician_id", "op": "eq", "value": ME}
_MY_GROUPS = {"field": "group_id", "op": "in", "value": MY_GROUPS}
_UNASSIGNED = {
    "and": [
        _OPEN,
        {"field": "group_id", "op": "is_null"},
        {"field": "technician_id", "op": "is_null"},
    ]
}
_OVERDUE = {"and": [_OPEN, {"field": "resolution_due_at", "op": "before_now"}]}
_DUE_TODAY = {"and": [_OPEN, {"field": "resolution_due_at", "op": "today"}]}


@dataclass(frozen=True)
class WidgetTemplate:
    """One catalogue entry."""

    code: str
    module: str  # report folder code: `report_folder.<module>`
    section: str
    size: tuple[int, int]
    source: Mapping[str, Any]  # {"report": ...} | {"report_ref": ...} | {"records": ...}
    coming_with: str | None = None  # the work package that brings its data (not addable yet)
    title_key: str | None = None  # default: dashboard_widget.<code>

    def widget(
        self, widget_id: str, x: int, y: int, w: int | None = None, h: int | None = None
    ) -> Widget:
        """The template as a widget placed on the grid."""
        width, height = self.size
        return Widget.model_validate(
            {
                "id": widget_id,
                "title_key": self.title_key or f"dashboard_widget.{self.code}",
                **self.source,
                "place": {"x": x, "y": y, "w": w or width, "h": h or height},
            }
        )


def _report(**definition: Any) -> dict[str, Any]:  # noqa: ANN401 - definition fields
    return {"report": {"entity": "incident", **definition}}


def _kpi(code: str, measure: str, **definition: Any) -> WidgetTemplate:  # noqa: ANN401 - fields
    return WidgetTemplate(
        code,
        INCIDENTS,
        KEY_NUMBERS,
        KPI_SIZE,
        _report(measures=[measure], chart="kpi", **definition),
    )


def _chart(code: str, section: str, **definition: Any) -> WidgetTemplate:  # noqa: ANN401 - fields
    return WidgetTemplate(code, INCIDENTS, section, CHART_SIZE, _report(**definition))


def _open_by(field: str, chart: str = "bar") -> WidgetTemplate:
    return _chart(
        f"open_by_{field.removesuffix('_id')}",
        OPEN_WORK,
        filter=_OPEN,
        group_by=[{"field": field}],
        order="value_desc" if chart == "bar" else "key",
        chart=chart,
    )


def _records(code: str, sort: str, **records: Any) -> WidgetTemplate:  # noqa: ANN401 - fields
    return WidgetTemplate(
        code,
        INCIDENTS,
        QUEUES,
        LIST_SIZE,
        {"records": {"entity": "incident", "sort": sort, **records}},
    )


def _later(code: str, package: str) -> WidgetTemplate:
    # Its source is a placeholder report so the entry validates; it cannot be added.
    return WidgetTemplate(
        code,
        INCIDENTS,
        COMING_LATER,
        CHART_SIZE,
        _report(measures=["count"], chart="kpi"),
        coming_with=package,
    )


CURATED: tuple[WidgetTemplate, ...] = (
    # Key numbers, each with the previous period beside it (REQ-DSH-008).
    _kpi("open", "open_count"),
    _kpi("unassigned_open", "unassigned_open_count"),
    _kpi("overdue", "overdue_count"),
    _kpi("due_today", "due_today_count"),
    _kpi(
        "received_today", "count", filter={"field": "created_at", "op": "last_n_days", "value": 1}
    ),
    _kpi(
        "resolved_today", "count", filter={"field": "resolved_at", "op": "last_n_days", "value": 1}
    ),
    _kpi("awaiting_response", "awaiting_response_count"),
    _kpi(
        "reopened_30_days",
        "reopened_count",
        filter={"field": "created_at", "op": "last_n_days", "value": 30},
    ),
    _kpi(
        "time_to_resolve_30_days",
        "mean_time_to_resolve",
        filter={"field": "resolved_at", "op": "last_n_days", "value": 30},
    ),
    _kpi("my_open", "open_count", filter=_MINE),
    _kpi("my_overdue", "overdue_count", filter=_MINE),
    _kpi(
        "my_resolved_week",
        "count",
        filter={"and": [_MINE, {"field": "resolved_at", "op": "last_n_days", "value": 7}]},
    ),
    # Open work by ...
    _open_by("status", "doughnut"),
    _open_by("priority", "doughnut"),
    _open_by("group_id"),
    _chart(
        "open_by_technician",
        OPEN_WORK,
        filter=_OPEN,
        group_by=[{"field": "technician_id"}, {"field": "status_category"}],
        order="value_desc",
        chart="stacked_bar",
    ),
    _open_by("category_id"),
    _open_by("channel", "doughnut"),
    _open_by("site_id"),
    _open_by("level"),
    _chart(
        "unassigned_by_site",
        OPEN_WORK,
        filter=_UNASSIGNED,
        group_by=[{"field": "site_id"}],
        order="value_desc",
        chart="bar",
    ),
    # Queues: lists of records and the viewer's own work.
    _records("unassigned_list", "created", filter=_UNASSIGNED),
    _records("overdue_list", "due", filter=_OVERDUE),
    _records("due_today_list", "due", filter=_DUE_TODAY),
    _records(
        "awaiting_response_list",
        "created",
        filter={"and": [_OPEN, {"field": "first_responded_at", "op": "is_null"}]},
    ),
    _records("my_open_list", "priority", filter={"and": [_OPEN, _MINE]}),
    _records("recently_updated", "updated"),
    _chart(
        "my_groups_queue",
        QUEUES,
        filter={"and": [_OPEN, _MY_GROUPS]},
        group_by=[{"field": "group_id"}, {"field": "priority"}],
        chart="stacked_bar",
    ),
    _chart(
        "my_open_by_priority",
        QUEUES,
        filter={"and": [_OPEN, _MINE]},
        group_by=[{"field": "priority"}],
        chart="doughnut",
    ),
    # Trends.
    _chart(
        "created_vs_resolved",
        TRENDS,
        measures=["flow_created", "flow_resolved"],
        flow={"days": 30, "bucket": "day"},
        chart="line",
    ),
    _chart(
        "backlog_trend",
        TRENDS,
        measures=["flow_backlog"],
        flow={"days": 90, "bucket": "week"},
        chart="area",
    ),
    _chart(
        "received_per_day",
        TRENDS,
        filter={"field": "created_at", "op": "last_n_days", "value": 20},
        group_by=[{"field": "created_at", "bucket": "day"}],
        chart="line",
    ),
    _chart(
        "resolved_per_day",
        TRENDS,
        filter={"field": "resolved_at", "op": "last_n_days", "value": 20},
        group_by=[{"field": "resolved_at", "bucket": "day"}],
        chart="line",
    ),
    _chart(
        "reopened_by_group",
        TRENDS,
        filter={
            "and": [
                {"field": "created_at", "op": "last_n_days", "value": 30},
                {"field": "reopen_count", "op": "gt", "value": 0},
            ]
        },
        group_by=[{"field": "group_id"}],
        order="value_desc",
        chart="bar",
    ),
    # Time.
    _chart(
        "open_ageing",
        TIME,
        filter=_OPEN,
        group_by=[{"field": "created_at", "bucket": "age"}],
        chart="bar",
    ),
    _chart(
        "my_open_ageing",
        TIME,
        filter={"and": [_OPEN, _MINE]},
        group_by=[{"field": "created_at", "bucket": "age"}],
        chart="bar",
    ),
    _chart(
        "first_response_by_group",
        TIME,
        filter={"field": "created_at", "op": "last_n_days", "value": 30},
        group_by=[{"field": "group_id"}],
        measures=["mean_time_to_respond"],
        chart="bar",
    ),
    _chart(
        "resolution_by_priority",
        TIME,
        filter={"field": "resolved_at", "op": "last_n_days", "value": 30},
        group_by=[{"field": "priority"}],
        measures=["mean_time_to_resolve"],
        chart="bar",
    ),
    # Coming later: shown so people looking for them see they are planned (D-114).
    _later("sla_breached", "sla"),
    _later("sla_at_risk", "sla"),
    _later("sla_breaches_by_technician", "sla"),
    _later("first_response_sla", "sla"),
    _later("pending_approvals", "approvals"),
)

# Every built-in report, as a chart or table widget (product owner, 2026-10-28).
FROM_REPORTS: tuple[WidgetTemplate, ...] = tuple(
    WidgetTemplate(
        f"report_{r.code}",
        r.folder,
        REPORTS,
        KPI_SIZE if r.definition.chart == "kpi" else CHART_SIZE,
        {"report_ref": f"builtin:{r.code}"},
        title_key=f"report.{r.code}",
    )
    for r in BUILTIN_REPORTS
)

CATALOGUE: Mapping[str, WidgetTemplate] = MappingProxyType(
    {t.code: t for t in (*CURATED, *FROM_REPORTS)}
)


def _place(*rows: tuple[str, int, int, int, int]) -> DashboardBody:
    """A built-in dashboard: catalogue widgets at (x, y, w, h); the widget id is the code."""
    return DashboardBody(
        widgets=[CATALOGUE[code].widget(code, x, y, w, h) for code, x, y, w, h in rows]
    )


# Built-in ("ready-made") dashboards (REQ-DSH-003), placed from the catalogue (D-114). SLA
# widgets join with SLA (WP-025, lane A).
BUILTIN_DASHBOARDS: Mapping[str, DashboardBody] = MappingProxyType(
    {
        # The service desk: key numbers, flow, where open work sits, and what needs a hand.
        "service_desk": _place(
            ("open", 0, 0, 3, 2),
            ("unassigned_open", 3, 0, 3, 2),
            ("overdue", 6, 0, 3, 2),
            ("due_today", 9, 0, 3, 2),
            ("received_today", 0, 2, 3, 2),
            ("resolved_today", 3, 2, 3, 2),
            ("awaiting_response", 6, 2, 3, 2),
            ("time_to_resolve_30_days", 9, 2, 3, 2),
            ("created_vs_resolved", 0, 4, 6, 4),
            ("backlog_trend", 6, 4, 6, 4),
            ("open_by_technician", 0, 8, 6, 4),
            ("open_by_priority", 6, 8, 3, 4),
            ("open_by_channel", 9, 8, 3, 4),
            ("open_by_group", 0, 12, 6, 4),
            ("open_ageing", 6, 12, 6, 4),
            ("overdue_list", 0, 16, 6, 4),
            ("unassigned_list", 6, 16, 6, 4),
        ),
        # "My work": a technician's own queue (the technician role's home, REQ-DSH-002).
        "my_work": _place(
            ("my_open", 0, 0, 3, 2),
            ("my_overdue", 3, 0, 3, 2),
            ("my_resolved_week", 6, 0, 3, 2),
            ("unassigned_open", 9, 0, 3, 2),
            ("my_open_list", 0, 2, 6, 4),
            ("my_groups_queue", 6, 2, 6, 4),
            ("my_open_by_priority", 0, 6, 6, 4),
            ("my_open_ageing", 6, 6, 6, 4),
            ("recently_updated", 0, 10, 12, 4),
        ),
    }
)

# Home dashboards of the built-in roles until an admin sets others (REQ-DSH-002 AC1).
ROLE_HOMES: Mapping[str, str] = MappingProxyType(
    {"tenant_admin": "service_desk", "technician": "my_work"}
)
FALLBACK_HOME = "my_work"
