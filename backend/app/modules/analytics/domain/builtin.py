"""Built-in reports (REQ-RPT-014, REQ-RPT-015): definitions shipped in code, read-only, copyable.

Each is a `ReportDefinition` in the same JSON format as saved reports (REQ-RPT-011). Names and
descriptions are labels: `report.<code>` and `report.<code>.description` (en, ar, ur), checked by
the tests. A built-in report whose fields or measures its entity does not offer yet (their data
arrives with a later work package) is left out of the catalogue until it does.

Default range: the last 30 days (parity file 09, Appendix A), shown in the filter bar.
Report set A of the WP-035 plan; SLA, worklog, reopen and service request reports follow their
work packages (WP-025, WP-020e, WP-020f, WP-030).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.modules.analytics.domain.definition import ReportDefinition

INCIDENTS = "incidents"  # folder code; label `report_folder.incidents`

_OPEN = {"field": "status_category", "op": "in", "value": ["open", "paused"]}
_LAST_30 = {"field": "created_at", "op": "last_n_days", "value": 30}


@dataclass(frozen=True)
class BuiltinReport:
    """One shipped report."""

    code: str
    folder: str
    definition: ReportDefinition


def _report(code: str, **definition: Any) -> BuiltinReport:  # noqa: ANN401 - definition fields
    return BuiltinReport(
        code, INCIDENTS, ReportDefinition.model_validate({"entity": "incident", **definition})
    )


def _open_by(field: str, chart: str = "bar") -> BuiltinReport:
    return _report(
        f"incidents_open_by_{field.removesuffix('_id')}",
        filter=_OPEN,
        group_by=[{"field": field}],
        order="value_desc",
        chart=chart,
    )


BUILTIN_REPORTS: tuple[BuiltinReport, ...] = (
    _report(
        "incidents_all",
        filter=_LAST_30,
        group_by=[{"field": "status_category"}],
        chart="table",
    ),
    _report("incidents_by_status", filter=_LAST_30, group_by=[{"field": "status"}]),
    _report(
        "incidents_open_by_status",
        filter=_OPEN,
        group_by=[{"field": "status"}],
        chart="doughnut",
    ),
    _open_by("priority", "doughnut"),
    _open_by("category_id"),
    _open_by("group_id"),
    _open_by("technician_id"),
    _open_by("site_id"),
    _open_by("department_id"),
    _open_by("requester_id"),
    _open_by("channel", "doughnut"),
    _open_by("level"),
    _report(
        "incidents_received_per_day",
        filter=_LAST_30,
        group_by=[{"field": "created_at", "bucket": "day"}],
        chart="line",
    ),
    _report(
        "incidents_received_per_week",
        filter={"field": "created_at", "op": "last_n_days", "value": 182},
        group_by=[{"field": "created_at", "bucket": "week"}],
        chart="line",
    ),
    _report(
        "incidents_received_per_month",
        filter={"field": "created_at", "op": "last_n_days", "value": 365},
        group_by=[{"field": "created_at", "bucket": "month"}],
        chart="bar",
    ),
    _report(
        "incidents_resolved_per_day",
        filter={"field": "resolved_at", "op": "last_n_days", "value": 30},
        group_by=[{"field": "resolved_at", "bucket": "day"}],
        chart="line",
    ),
    _report(
        "incidents_open_ageing",
        filter=_OPEN,
        group_by=[{"field": "created_at", "bucket": "age"}],
        chart="bar",
    ),
    _report(
        "incidents_unassigned_by_site",
        filter={
            "and": [
                _OPEN,
                {"field": "group_id", "op": "is_null"},
                {"field": "technician_id", "op": "is_null"},
            ]
        },
        group_by=[{"field": "site_id"}],
        order="value_desc",
    ),
    _report(
        "incidents_reassignments_by_group",
        filter=_LAST_30,
        group_by=[{"field": "group_id"}],
        measures=["count", "reassigned_count", "average_reassignments"],
        order="value_desc",
        chart="table",
    ),
    _report(
        "incidents_reassignments_by_technician",
        filter=_LAST_30,
        group_by=[{"field": "technician_id"}],
        measures=["count", "reassigned_count", "average_reassignments"],
        order="value_desc",
        chart="table",
    ),
    _report(
        "incidents_response_time_by_group",
        filter=_LAST_30,
        group_by=[{"field": "group_id"}],
        measures=["mean_time_to_respond", "count"],
        chart="bar",
    ),
    _report(
        "incidents_response_time_by_priority",
        filter=_LAST_30,
        group_by=[{"field": "priority"}],
        measures=["mean_time_to_respond", "count"],
        chart="bar",
    ),
    _report(
        "incidents_resolution_time_by_priority",
        filter={"field": "resolved_at", "op": "last_n_days", "value": 30},
        group_by=[{"field": "priority"}],
        measures=["mean_time_to_resolve", "resolved_count"],
        chart="bar",
    ),
)

BUILTIN: Mapping[str, BuiltinReport] = MappingProxyType({r.code: r for r in BUILTIN_REPORTS})
BUILTIN_PREFIX = "builtin:"


def builtin_ref(code: str) -> str:
    """The favourite / copy reference of a built-in report."""
    return f"{BUILTIN_PREFIX}{code}"
