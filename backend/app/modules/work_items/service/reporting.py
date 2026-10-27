"""Work items as reporting sources (WP-035 port, ADR-033, D-100 D9).

Each type hands analytics its own list query (`staff_rows`, scope filter included) and the
list's filter fields, so a report never counts a record the viewer could not list.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import metadata
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import TYPES, WorkItemType
from app.modules.work_items.service.access import FIELDS
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
    "group_id": Dimension(_D.REFERENCE, reference="group"),
    "site_id": Dimension(_D.REFERENCE, reference="site"),
    "department_id": Dimension(_D.REFERENCE, reference="department"),
    "technician_id": Dimension(_D.REFERENCE, reference="user"),
    "requester_id": Dimension(_D.REFERENCE, reference="user"),
    "category_id": Dimension(_D.REFERENCE, reference="category"),
    "created_at": Dimension(_D.DATETIME),
    "resolved_at": Dimension(_D.DATETIME),
    "closed_at": Dimension(_D.DATETIME),
    "reopen_count": Dimension(_D.NUMBER),
    "reassignment_count": Dimension(_D.NUMBER),
    "paused_seconds": Dimension(_D.NUMBER),
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
        dimensions = dict(DIMENSIONS)
        for name, spec in custom.items():
            # Single choices group by their admin label; multi-choice is not groupable (MVP).
            if spec.type == FieldType.ENUM and not spec.array:
                dimensions[name] = Dimension(_D.ADMIN_CODE)
        return ReportingSource(
            entity=self.entity,
            rows=staff_rows(subject, self._wtype),
            fields=ResourceFields(FIELDS.name, {**FIELDS.fields, **custom}, FIELDS.id_column),
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
