"""Work items as reporting sources (WP-035 port, ADR-033, D-100 D9).

Each type hands analytics its own list query (`staff_rows`, scope filter included) and the
list's filter fields, so a report never counts a record the viewer could not list.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.service.access import FIELDS, type_fields
from app.modules.work_items.service.work_items import staff_rows
from app.shared.api.filters import FieldType, ResourceFields
from app.shared.reporting import (
    Dimension,
    DimensionKind,
    ReportingSource,
    register_source,
    unregister_source,
)

_D = DimensionKind
DIMENSIONS: Mapping[str, Dimension] = {
    "priority": Dimension(_D.CODE, label_prefix="priority"),
    "status_category": Dimension(_D.CODE, label_prefix="status_category"),
    "channel": Dimension(_D.CODE, label_prefix="work_item_channel"),
    "impact": Dimension(_D.CODE, label_prefix="impact"),
    "urgency": Dimension(_D.CODE, label_prefix="urgency"),
    "status": Dimension(_D.ADMIN_CODE),
    "level": Dimension(_D.ADMIN_CODE),
    "closure_code": Dimension(_D.ADMIN_CODE),  # REQ-INC-093: reports group by it
    "group_id": Dimension(_D.REFERENCE, reference="group"),
    "site_id": Dimension(_D.REFERENCE, reference="site"),
    "department_id": Dimension(_D.REFERENCE, reference="department"),
    "technician_id": Dimension(_D.REFERENCE, reference="user"),
    "requester_id": Dimension(_D.REFERENCE, reference="user"),
    "category_id": Dimension(_D.REFERENCE, reference="category"),
    "created_at": Dimension(_D.DATETIME),
    "resolved_at": Dimension(_D.DATETIME),
    "closed_at": Dimension(_D.DATETIME),
    # The latest restore from the trash (Haider, 2026-11-10): "restored from trash" in SLA
    # reports, as the clock keeps running while a record is in the trash.
    "restored_at": Dimension(_D.DATETIME),
    "reopen_count": Dimension(_D.NUMBER),
    "reassignment_count": Dimension(_D.NUMBER),
    "paused_seconds": Dimension(_D.NUMBER),
    # SLA results (WP-025 session 3): each target's state, named by `sla_target_state.*`, and
    # whether it was ever breached; the same values the record's SLA panel shows (§3.2).
    "first_response_sla_state": Dimension(_D.CODE, label_prefix="sla_target_state"),
    "resolution_sla_state": Dimension(_D.CODE, label_prefix="sla_target_state"),
    "first_response_breached": Dimension(_D.BOOLEAN),
    "resolution_breached": Dimension(_D.BOOLEAN),
}


# Problems' own figures (WP-044c D15, the report source lane C's WP-063 screens use): what kind,
# the root cause category (never the root cause text, D-140 Q7), whether it is a known error, and
# when it was accepted without a fix. The fields are the type's own (access.type_fields), so the
# problem list takes them too and incident filters and reports never offer them.
PROBLEM_DIMENSIONS: Mapping[str, Dimension] = {
    "problem_type": Dimension(_D.ADMIN_CODE),
    "root_cause_category": Dimension(_D.ADMIN_CODE),
    "known_error_at": Dimension(_D.DATETIME),
    "accepted_at": Dimension(_D.DATETIME),
}
# Changes' own figures (WP-045d S4c, REQ-CHG-116): where it is, what kind, why, how risky, and
# how it went (the implementation's outcome and time, downtime planned and actual, freezes
# passed). Never the plans, the risk answers or anyone's reasons in words.
CHANGE_DIMENSIONS: Mapping[str, Dimension] = {
    "stage": Dimension(_D.CODE, label_prefix="work_item_stage"),
    "stage_path": Dimension(_D.CODE, label_prefix="stage_path"),
    "change_type": Dimension(_D.ADMIN_CODE),
    "change_reason": Dimension(_D.ADMIN_CODE),
    "risk": Dimension(_D.CODE, label_prefix="risk_level"),
    "retrospective": Dimension(_D.BOOLEAN),
    "freeze_overridden": Dimension(_D.BOOLEAN),
    "implementation_outcome": Dimension(_D.CODE, label_prefix="stage_outcome"),
    "implementation_seconds": Dimension(_D.NUMBER),
    "planned_downtime_seconds": Dimension(_D.NUMBER),
    "actual_downtime_seconds": Dimension(_D.NUMBER),
}
TYPE_DIMENSIONS: Mapping[WorkItemTypeCode, Mapping[str, Dimension]] = {
    WorkItemTypeCode.PROBLEM: PROBLEM_DIMENSIONS,
    WorkItemTypeCode.CHANGE: CHANGE_DIMENSIONS,
}


class WorkItemSource:
    """The reporting provider of one work item type."""

    def __init__(self, wtype: WorkItemType) -> None:
        self._wtype = wtype

    @property
    def entity(self) -> str:
        """Entity code: the type code, e.g. "incident"."""
        return self._wtype.code.value

    @property
    def feature(self) -> str:
        """The type's licence feature."""
        return self._wtype.feature

    @property
    def permission(self) -> str:
        """The list permission."""
        return f"{self._wtype.permission_prefix}.view"

    async def source(self, session: AsyncSession, subject: Any) -> ReportingSource:  # noqa: ANN401 - Subject; the port is typed for shared code
        """The type's list query, scope-filtered for `subject`, with its filter fields."""
        if not isinstance(subject, Subject):
            raise TypeError(subject)
        custom = await metadata.filter_fields(session, self.entity, "work_items")
        dimensions = {**DIMENSIONS, **TYPE_DIMENSIONS.get(self._wtype.code, {})}
        own = type_fields(self._wtype)
        for name, spec in custom.items():
            # Single choices group by their admin label; multi-choice is not groupable (MVP).
            if spec.type == FieldType.ENUM and not spec.array:
                dimensions[name] = Dimension(_D.ADMIN_CODE)
        return ReportingSource(
            entity=self.entity,
            rows=staff_rows(subject, self._wtype),
            fields=ResourceFields(
                FIELDS.name, {**FIELDS.fields, **own, **custom}, FIELDS.id_column
            ),
            dimensions=dimensions,
            list_path=self._wtype.path,
        )


def register_sources() -> None:
    """Make every built work item type reportable (module startup)."""
    for wtype in TYPES.values():
        register_source(WorkItemSource(wtype))


def unregister_sources() -> None:
    """Undo `register_sources` (module shutdown)."""
    for wtype in TYPES.values():
        unregister_source(wtype.code.value)
