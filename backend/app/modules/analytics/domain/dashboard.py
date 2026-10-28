"""Dashboards (WP-036; parity file 09 REQ-DSH-*): widgets on a grid, built on report definitions.

A widget is a report definition shown one way (its `chart`: KPI tile, bar, doughnut ...), or a
reference to a built-in or saved report. Widgets run through the same engine as reports, so a
widget's number always equals the report's (REQ-DSH-008 AC3, REQ-DSH-009 AC1) and each viewer
sees their own scope (REQ-DSH-028).

The whole dashboard (its widgets, their places and the default filters) is one versioned
document: a copy is independent of its original (REQ-DSH-021 AC2) and every edit is one save
with If-Match. Built-in ("ready-made") dashboards ship as documents in code, read-only and
copyable (REQ-DSH-003), named by labels `dashboard.<code>` and their widgets by
`dashboard_widget.<code>`.

`ME` in a filter value stands for the viewer ("my open incidents"): the console puts the
viewer's id in before running, and saving checks the definition with the saver's id in its place.
"""

import uuid
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.analytics.domain.definition import ReportDefinition

ME = "@me"
GRID_COLUMNS = 12
MAX_WIDGETS = 24
BUILTIN_PREFIX = "builtin:"
_WIDGET_ID = r"^[a-z0-9][a-z0-9_-]{0,39}$"


class Placement(BaseModel):
    """Where a widget sits on the 12-column grid (REQ-DSH-019)."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0, le=GRID_COLUMNS - 1)
    y: int = Field(ge=0, le=500)
    w: int = Field(ge=1, le=GRID_COLUMNS)
    h: int = Field(ge=1, le=12)

    @model_validator(mode="after")
    def _fits(self) -> "Placement":
        if self.x + self.w > GRID_COLUMNS:
            message = "off_grid"
            raise ValueError(message)
        return self


class Widget(BaseModel):
    """One widget: a report definition (or a report reference) shown on the dashboard."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_WIDGET_ID)
    # A user's widget is titled in words; a built-in one by a label key (dashboard_widget.<code>).
    title: str | None = Field(default=None, min_length=1, max_length=120)
    title_key: str | None = Field(default=None, max_length=80)
    report: ReportDefinition | None = None
    report_ref: str | None = Field(default=None, max_length=100)
    place: Placement

    @model_validator(mode="after")
    def _one_source(self) -> "Widget":
        if (self.report is None) == (self.report_ref is None):
            message = "report_or_report_ref"
            raise ValueError(message)
        return self


class DashboardFilters(BaseModel):
    """The filter bar's defaults (REQ-DSH-022): site, group and a time range in days."""

    model_config = ConfigDict(extra="forbid")

    site_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    days: int | None = Field(default=None, ge=1, le=366)


class DashboardBody(BaseModel):
    """What a dashboard holds: its widgets and its filter defaults."""

    model_config = ConfigDict(extra="forbid")

    widgets: list[Widget] = Field(default_factory=list, max_length=MAX_WIDGETS)
    filters: DashboardFilters = Field(default_factory=DashboardFilters)

    @field_validator("widgets")
    @classmethod
    def _unique_ids(cls, widgets: list[Widget]) -> list[Widget]:
        ids = [w.id for w in widgets]
        if len(ids) != len(set(ids)):
            message = "duplicate_widget_id"
            raise ValueError(message)
        return widgets


def with_viewer(value: Any, user_id: uuid.UUID) -> Any:  # noqa: ANN401 - a filter DSL tree
    """`value` with every `ME` replaced by the viewer's id (for checking and running)."""
    if value == ME:
        return str(user_id)
    if isinstance(value, list):
        return [with_viewer(v, user_id) for v in value]
    if isinstance(value, dict):
        return {k: with_viewer(v, user_id) for k, v in value.items()}
    return value


# --- built-in dashboards ----------------------------------------------------------------------

_OPEN = {"field": "status_category", "op": "in", "value": ["open", "paused"]}
_MINE = {"field": "technician_id", "op": "eq", "value": ME}


def _report(**definition: Any) -> dict[str, Any]:  # noqa: ANN401 - definition fields
    return {"entity": "incident", **definition}


def _widget(
    code: str,
    place: tuple[int, int, int, int],
    **definition: Any,  # noqa: ANN401 - fields
) -> dict[str, Any]:
    x, y, w, h = place
    return {
        "id": code,
        "title_key": f"dashboard_widget.{code}",
        "report": _report(**definition),
        "place": {"x": x, "y": y, "w": w, "h": h},
    }


def _kpi(code: str, place: tuple[int, int, int, int], measure: str, **rest: Any) -> dict[str, Any]:  # noqa: ANN401 - definition fields
    return _widget(code, place, measures=[measure], chart="kpi", **rest)


# The service desk dashboard (REQ-DSH-003): open work and its flow. SLA widgets (breaches by
# technician, approaching breach) join with SLA (WP-025, lane A).
_SERVICE_DESK = {
    "widgets": [
        _kpi("open", (0, 0, 3, 2), "open_count"),
        _kpi("unassigned_open", (3, 0, 3, 2), "unassigned_open_count"),
        _kpi(
            "received_today",
            (6, 0, 3, 2),
            "count",
            filter={"field": "created_at", "op": "last_n_days", "value": 1},
        ),
        _kpi(
            "resolved_today",
            (9, 0, 3, 2),
            "count",
            filter={"field": "resolved_at", "op": "last_n_days", "value": 1},
        ),
        _widget(
            "open_by_technician",
            (0, 2, 6, 4),
            filter=_OPEN,
            group_by=[{"field": "technician_id"}, {"field": "status_category"}],
            order="value_desc",
            chart="stacked_bar",
        ),
        _widget(
            "open_by_priority",
            (6, 2, 3, 4),
            filter=_OPEN,
            group_by=[{"field": "priority"}],
            chart="doughnut",
        ),
        _widget(
            "open_by_channel",
            (9, 2, 3, 4),
            filter=_OPEN,
            group_by=[{"field": "channel"}],
            chart="doughnut",
        ),
        _widget(
            "received_per_day",
            (0, 6, 6, 4),
            filter={"field": "created_at", "op": "last_n_days", "value": 20},
            group_by=[{"field": "created_at", "bucket": "day"}],
            chart="line",
        ),
        _widget(
            "resolved_per_day",
            (6, 6, 6, 4),
            filter={"field": "resolved_at", "op": "last_n_days", "value": 20},
            group_by=[{"field": "resolved_at", "bucket": "day"}],
            chart="line",
        ),
        _widget(
            "unassigned_by_site",
            (0, 10, 12, 4),
            filter={
                "and": [
                    _OPEN,
                    {"field": "group_id", "op": "is_null"},
                    {"field": "technician_id", "op": "is_null"},
                ]
            },
            group_by=[{"field": "site_id"}],
            order="value_desc",
            chart="bar",
        ),
    ],
}

# "My work": a technician's own queue (the technician role's home by default, REQ-DSH-002).
_MY_WORK = {
    "widgets": [
        _kpi("my_open", (0, 0, 4, 2), "open_count", filter=_MINE),
        _kpi(
            "my_resolved_week",
            (4, 0, 4, 2),
            "count",
            filter={"and": [_MINE, {"field": "resolved_at", "op": "last_n_days", "value": 7}]},
        ),
        _kpi("unassigned_open", (8, 0, 4, 2), "unassigned_open_count"),
        _widget(
            "my_open_by_priority",
            (0, 2, 6, 4),
            filter={"and": [_OPEN, _MINE]},
            group_by=[{"field": "priority"}],
            chart="doughnut",
        ),
        _widget(
            "my_open_ageing",
            (6, 2, 6, 4),
            filter={"and": [_OPEN, _MINE]},
            group_by=[{"field": "created_at", "bucket": "age"}],
            chart="bar",
        ),
    ],
}

BUILTIN_DASHBOARDS: Mapping[str, DashboardBody] = MappingProxyType(
    {
        "service_desk": DashboardBody.model_validate(_SERVICE_DESK),
        "my_work": DashboardBody.model_validate(_MY_WORK),
    }
)

# Home dashboards of the built-in roles until an admin sets others (REQ-DSH-002 AC1).
ROLE_HOMES: Mapping[str, str] = MappingProxyType(
    {"tenant_admin": "service_desk", "technician": "my_work"}
)
FALLBACK_HOME = "my_work"


def builtin_ref(code: str) -> str:
    """The reference of a built-in dashboard ("builtin:service_desk")."""
    return f"{BUILTIN_PREFIX}{code}"
