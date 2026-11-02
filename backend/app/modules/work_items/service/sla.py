"""Incidents on the SLA module (WP-025 session 2; wp-025-plan.md §3.1).

Registers the incident record type with sla: the fields a policy's conditions may use and the
priority codes, highest first. The SLA fields themselves (due dates, the policy, paused time)
and the record's own timestamps are left out: a policy chosen by its own due date would go round
in circles, and a condition on "created before" would match differently on every recalculation.
"""

from app.modules import sla
from app.modules.work_items.domain.classification import Priority
from app.modules.work_items.domain.types import WorkItemTypeCode
from app.modules.work_items.service.access import FIELDS
from app.shared.api.filters import ResourceFields

# Fields no policy condition may name (see the docstring).
_NOT_CONDITIONS = frozenset(
    {
        "id",
        "display_id",
        "display_number",
        "sla_policy_id",
        "resolution_due_at",
        "first_responded_at",
        "paused_seconds",
        "created_at",
        "updated_at",
        "status_changed_at",
        "first_assigned_at",
        "resolved_at",
        "closed_at",
        "created_by",
        "updated_by",
    }
)

CONDITION_FIELDS = ResourceFields(
    FIELDS.name,
    {k: v for k, v in FIELDS.fields.items() if k not in _NOT_CONDITIONS},
    FIELDS.id_column,
)


def register_sla() -> None:
    """Incidents have SLAs (called at import; idempotent)."""
    sla.register_record_type(
        sla.SlaRecordType(
            code=WorkItemTypeCode.INCIDENT.value,
            fields=CONDITION_FIELDS,
            priorities=tuple(p.value for p in Priority),
        )
    )
