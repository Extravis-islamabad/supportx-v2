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
from collections.abc import Collection
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.analytics.domain.definition import ReportDefinition
from app.shared.api.filters import FilterNode

ME = "@me"
# The viewer's groups (D-114), for `{"field": "group_id", "op": "in", "value": "@my_groups"}`.
# Resolved on the server from the signed-in session, so a browser cannot claim other groups.
MY_GROUPS = "@my_groups"
# Stands in for "no groups": `in` needs a value, and no record has this group.
NO_GROUP = "00000000-0000-0000-0000-000000000000"
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


class RecordsSpec(BaseModel):
    """A short list of records (D-114), read through the entity's own list in the viewer's scope.

    Its filter may say `@me` (the console puts the viewer in); `@my_groups` is for report
    widgets, which the server resolves.
    """

    model_config = ConfigDict(extra="forbid", title="DashboardRecords")

    entity: str = Field(max_length=40)
    filter: FilterNode | None = None
    # Newest change first, newest first, soonest due first, or highest priority first.
    sort: Literal["updated", "created", "due", "priority"] = "updated"
    limit: int = Field(default=8, ge=1, le=20)

    def filter_json(self) -> Any:  # noqa: ANN401 - the filter DSL's JSON tree
        """The filter as the DSL reads it."""
        if self.filter is None:
            return None
        return self.filter.model_dump(by_alias=True, exclude_none=False)


class Widget(BaseModel):
    """One widget: a report definition (or a report reference) shown on the dashboard."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_WIDGET_ID)
    # A user's widget is titled in words; a built-in one by a label key (dashboard_widget.<code>).
    title: str | None = Field(default=None, min_length=1, max_length=120)
    title_key: str | None = Field(default=None, max_length=80)
    report: ReportDefinition | None = None
    report_ref: str | None = Field(default=None, max_length=100)
    records: RecordsSpec | None = None
    place: Placement

    @model_validator(mode="after")
    def _one_source(self) -> "Widget":
        sources = [self.report, self.report_ref, self.records]
        if sum(source is not None for source in sources) != 1:
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


def with_viewer(
    value: Any,  # noqa: ANN401 - a filter DSL tree
    user_id: uuid.UUID,
    group_ids: Collection[uuid.UUID] = (),
) -> Any:  # noqa: ANN401 - a filter DSL tree
    """`value` with `ME` as the viewer's id and `MY_GROUPS` as their groups (checking, running)."""
    if value == ME:
        return str(user_id)
    if value == MY_GROUPS:
        return sorted(str(g) for g in group_ids) or [NO_GROUP]
    if isinstance(value, list):
        return [with_viewer(v, user_id, group_ids) for v in value]
    if isinstance(value, dict):
        return {k: with_viewer(v, user_id, group_ids) for k, v in value.items()}
    return value


def builtin_ref(code: str) -> str:
    """The reference of a built-in dashboard ("builtin:service_desk")."""
    return f"{BUILTIN_PREFIX}{code}"
