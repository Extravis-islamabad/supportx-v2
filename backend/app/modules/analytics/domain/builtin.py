"""Built-in reports (REQ-RPT-014, REQ-RPT-015): definitions shipped in code, read-only, copyable.

Each is a `ReportDefinition` in the same JSON format as saved reports (REQ-RPT-011). Names and
descriptions are labels: `report.<code>` and `report.<code>.description` (en, ar, ur), checked by
the tests. A built-in report whose fields or measures its entity does not offer yet (their data
arrives with a later work package) is left out of the catalogue until it does.

Default range: the last 30 days (parity file 09, Appendix A), shown in the filter bar.
Report set A of the WP-035 plan; SLA, worklog, reopen and service request reports follow their
work packages (WP-025, WP-020e, WP-020f, WP-030). UI pass 3 P6 (D-147) adds a starter set for
every other reportable module (service requests, problems, releases) so the library shows each
module's reports; they use the shared work item fields and the count measure only, as those
entities have no measures of their own yet.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.modules.analytics.domain.definition import ReportDefinition

INCIDENTS = "incidents"  # folder code; label `report_folder.incidents`
SERVICE_REQUESTS = "service_requests"
PROBLEMS = "problems"
RELEASES = "releases"
CHANGES = "changes"
ASSETS = "assets"

_OPEN = {"field": "status_category", "op": "in", "value": ["open", "paused"]}
_LAST_30 = {"field": "created_at", "op": "last_n_days", "value": 30}


@dataclass(frozen=True)
class BuiltinReport:
    """One shipped report."""

    code: str
    folder: str
    definition: ReportDefinition


def _report(code: str, **definition: Any) -> BuiltinReport:  # noqa: ANN401 - definition fields
    return _of("incident", INCIDENTS, code, **definition)


def _of(entity: str, folder: str, code: str, **definition: Any) -> BuiltinReport:  # noqa: ANN401
    return BuiltinReport(
        code, folder, ReportDefinition.model_validate({"entity": entity, **definition})
    )


def _starter_set(entity: str, folder: str, prefix: str) -> tuple[BuiltinReport, ...]:
    """The reports every work item module gets: what is open, what came in, what got done."""

    def open_by(field: str, chart: str = "bar") -> BuiltinReport:
        return _of(
            entity,
            folder,
            f"{prefix}_open_by_{field.removesuffix('_id')}",
            filter=_OPEN,
            group_by=[{"field": field}],
            order="value_desc",
            chart=chart,
        )

    return (
        _of(entity, folder, f"{prefix}_by_status", filter=_LAST_30, group_by=[{"field": "status"}]),
        _of(
            entity,
            folder,
            f"{prefix}_open_by_status",
            filter=_OPEN,
            group_by=[{"field": "status"}],
            chart="doughnut",
        ),
        open_by("priority", "doughnut"),
        open_by("group_id"),
        open_by("technician_id"),
        _of(
            entity,
            folder,
            f"{prefix}_received_per_week",
            filter={"field": "created_at", "op": "last_n_days", "value": 182},
            group_by=[{"field": "created_at", "bucket": "week"}],
            chart="line",
        ),
        _of(
            entity,
            folder,
            f"{prefix}_resolved_per_week",
            filter={"field": "resolved_at", "op": "last_n_days", "value": 182},
            group_by=[{"field": "resolved_at", "bucket": "week"}],
            chart="line",
        ),
        _of(
            entity,
            folder,
            f"{prefix}_open_ageing",
            filter=_OPEN,
            group_by=[{"field": "created_at", "bucket": "age"}],
            chart="bar",
        ),
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

BUILTIN_REPORTS += (
    *_starter_set("service_request", SERVICE_REQUESTS, "requests"),
    *_starter_set("problem", PROBLEMS, "problems"),
    *_starter_set("release", RELEASES, "releases"),
)

# Changes (WP-045d S4c, REQ-CHG-116): the starter set, then where changes stand and how they went,
# over the changes raised in the last 90 days (a year for the monthly trends).
_CHANGE_90 = {"field": "created_at", "op": "last_n_days", "value": 90}


def _change(code: str, **definition: Any) -> BuiltinReport:  # noqa: ANN401 - definition fields
    return _of("change", CHANGES, code, **definition)


BUILTIN_REPORTS += (
    *_starter_set("change", CHANGES, "changes"),
    _change(
        "changes_open_by_stage",
        filter=_OPEN,
        group_by=[{"field": "stage"}],
        order="key",
        chart="bar",
    ),
    _change("changes_by_type", filter=_CHANGE_90, group_by=[{"field": "change_type"}]),
    _change("changes_by_risk", filter=_CHANGE_90, group_by=[{"field": "risk"}], chart="doughnut"),
    _change(
        "changes_by_reason",
        filter=_CHANGE_90,
        group_by=[{"field": "change_reason"}],
        order="value_desc",
    ),
    _change(
        "changes_by_outcome",
        filter={"and": [_CHANGE_90, {"field": "implementation_outcome", "op": "is_not_null"}]},
        group_by=[{"field": "implementation_outcome"}],
        chart="doughnut",
    ),
    _change(
        "changes_success_rate_by_type",
        filter=_CHANGE_90,
        group_by=[{"field": "change_type"}],
        measures=["success_rate", "count"],
        chart="bar",
    ),
    _change(
        "changes_success_rate_by_group",
        filter=_CHANGE_90,
        group_by=[{"field": "group_id"}],
        measures=["success_rate", "count"],
        order="value_desc",
        chart="bar",
    ),
    _change(
        "changes_emergency_share_per_month",
        filter={"field": "created_at", "op": "last_n_days", "value": 365},
        group_by=[{"field": "created_at", "bucket": "month"}],
        measures=["emergency_share"],
        chart="line",
    ),
    _change(
        "changes_downtime_per_month",
        filter={"field": "created_at", "op": "last_n_days", "value": 365},
        group_by=[{"field": "created_at", "bucket": "month"}],
        measures=["planned_downtime_total", "actual_downtime_total"],
        chart="bar",
    ),
    _change(
        "changes_implementation_time_by_type",
        filter=_CHANGE_90,
        group_by=[{"field": "change_type"}],
        measures=["average_implementation_time"],
        chart="bar",
    ),
    _change(
        "changes_freeze_overrides_by_group",
        filter={"and": [_CHANGE_90, {"field": "freeze_overridden", "op": "eq", "value": True}]},
        group_by=[{"field": "group_id"}],
        order="value_desc",
        chart="bar",
    ),
)

# Releases (WP-058b S5b, REQ-REL-060): beside the starter set, where releases stand and how they
# went, over the releases raised in the last 90 days (a year for the monthly trends).
_RELEASE_90 = {"field": "created_at", "op": "last_n_days", "value": 90}


def _release(code: str, **definition: Any) -> BuiltinReport:  # noqa: ANN401 - definition fields
    return _of("release", RELEASES, code, **definition)


BUILTIN_REPORTS += (
    _release(
        "releases_open_by_stage",
        filter=_OPEN,
        group_by=[{"field": "stage"}],
        order="key",
        chart="bar",
    ),
    _release("releases_by_type", filter=_RELEASE_90, group_by=[{"field": "release_type"}]),
    _release(
        "releases_by_risk", filter=_RELEASE_90, group_by=[{"field": "risk"}], chart="doughnut"
    ),
    _release(
        "releases_by_closure_code",
        filter={"and": [_RELEASE_90, {"field": "closure_code", "op": "is_not_null"}]},
        group_by=[{"field": "closure_code"}],
        chart="doughnut",
    ),
    _release(
        "releases_on_time_per_month",
        filter={"field": "created_at", "op": "last_n_days", "value": 365},
        group_by=[{"field": "created_at", "bucket": "month"}],
        measures=["on_time_rate"],
        chart="line",
    ),
    _release(
        "releases_failed_by_type",
        filter=_RELEASE_90,
        group_by=[{"field": "release_type"}],
        measures=["failed_count", "count"],
        chart="bar",
    ),
    _release(
        "releases_overdue_by_manager",
        filter=_OPEN,
        group_by=[{"field": "release_manager_id"}],
        measures=["overdue_count"],
        order="value_desc",
        chart="bar",
    ),
    _release(
        "releases_approval_time_by_type",
        filter=_RELEASE_90,
        group_by=[{"field": "release_type"}],
        measures=["average_approval_turnaround"],
        chart="bar",
    ),
)

# How far ahead the warranty report looks.
WARRANTY_DAYS = 90

# Assets (lane B's reporting source, #310): what is held, of what kind, its warranty and its age.
BUILTIN_REPORTS += (
    _of("asset", ASSETS, "assets_by_state", group_by=[{"field": "state_id"}], chart="doughnut"),
    _of(
        "asset",
        ASSETS,
        "assets_by_product_type",
        group_by=[{"field": "product_type_id"}],
        order="value_desc",
    ),
    _of(
        "asset",
        ASSETS,
        "assets_warranty_ending",
        # The warranties ending in the next 90 days (calendar dates take relative ranges since
        # lane B's #352), by the month they end, so the coming months read at a glance.
        filter={"field": "warranty_expires_on", "op": "next_n_days", "value": WARRANTY_DAYS},
        group_by=[{"field": "warranty_expires_on", "bucket": "month"}],
        chart="bar",
    ),
    _of(
        "asset",
        ASSETS,
        "assets_by_age",
        group_by=[{"field": "acquired_on", "bucket": "age"}],
        chart="bar",
    ),
)

# Assets' money (lane B's #375, WP-049b S2; the coordinator, 2026-11-11): listed only for those
# who may see money, as their fields exist only for them (the library compiles each built-in for
# the viewer and leaves out one that does not compile).
BUILTIN_REPORTS += (
    _of(
        "asset",
        ASSETS,
        "assets_book_value_by_cost_centre",
        group_by=[{"field": "cost_centre"}],
        measures=["book_value_total", "count"],
        order="value_desc",
        chart="bar",
    ),
    _of(
        "asset",
        ASSETS,
        "assets_total_cost_of_ownership",
        group_by=[{"field": "product_type_id"}],
        measures=["total_cost_total", "book_value_total"],
        order="value_desc",
        chart="bar",
    ),
)

BUILTIN: Mapping[str, BuiltinReport] = MappingProxyType({r.code: r for r in BUILTIN_REPORTS})
BUILTIN_PREFIX = "builtin:"


def builtin_ref(code: str) -> str:
    """The favourite / copy reference of a built-in report."""
    return f"{BUILTIN_PREFIX}{code}"
