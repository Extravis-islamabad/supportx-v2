"""Automation tables (WP-029; ADR-035). Tenant-scoped with RLS (migration 0025).

Definitions (business rules, routing rules, triggers) and settings (routing per record type,
auto-assignment per group) are edited by admins. Technician availability, the round robin turns
and the run log are written by the engine. Nothing here stores record values: rules hold codes
and IDs only, the run log names fields, not what was in them.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.automation.domain.assignment import AssignMethod, Availability
from app.modules.automation.domain.rules import RuleState
from app.shared.db.models import (
    Actors,
    Base,
    TenantEntity,
    TenantKeyed,
    TenantScoped,
    Timestamps,
    UuidPrimaryKey,
    Versioned,
)


def _codes(column: str, values: Any) -> str:  # noqa: ANN401 - any StrEnum class
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _group_fk(column: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", column], ["support_groups.tenant_id", "support_groups.id"], name=name
    )


class BusinessRule(TenantEntity):
    """A business rule: runs inside the save of one record type (REQ-RUL-001..005)."""

    __tablename__ = "business_rules"
    __table_args__ = (
        CheckConstraint(_codes("state", RuleState), name="state_code"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint("cardinality(events) BETWEEN 1 AND 2", name="events_present"),
        Index("ix_business_rules_tenant_type_position", "tenant_id", "record_type", "position"),
    )

    record_type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    events: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
    site_id: Mapped[uuid.UUID | None]
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    stop_after: Mapped[bool] = mapped_column(Boolean, server_default="false")
    position: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), server_default=RuleState.DRAFT.value)
    owner_id: Mapped[uuid.UUID | None]


class RoutingRule(TenantEntity):
    """An ordered routing rule: conditions → a group (REQ-ASG-001)."""

    __tablename__ = "routing_rules"
    __table_args__ = (
        CheckConstraint(_codes("state", RuleState), name="state_code"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        _group_fk("group_id", "fk_routing_rules_group"),
        Index("ix_routing_rules_tenant_type_position", "tenant_id", "record_type", "position"),
        Index("ix_routing_rules_tenant_group", "tenant_id", "group_id"),
    )

    record_type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    site_id: Mapped[uuid.UUID | None]
    group_id: Mapped[uuid.UUID]
    overwrite: Mapped[bool] = mapped_column(Boolean, server_default="false")
    position: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), server_default=RuleState.DRAFT.value)


class RoutingSettings(TenantKeyed, Timestamps, Actors, Versioned, Base):
    """Per record type: the fallback group and whether a category suggests one (REQ-ASG-001)."""

    __tablename__ = "routing_settings"
    __table_args__ = (_group_fk("fallback_group_id", "fk_routing_settings_fallback"),)

    record_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    fallback_group_id: Mapped[uuid.UUID | None]
    use_category_group: Mapped[bool] = mapped_column(Boolean, server_default="true")


class TransitionSetting(TenantKeyed, Timestamps, Actors, Versioned, Base):
    """One life-cycle action's settings: who, when, confirmation, "after" (REQ-WF-003, 004).

    No row: the action behaves as before (permission only).
    """

    __tablename__ = "transition_settings"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(after_actions) = 'array'", name="after_actions_array"),
    )

    record_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    action: Mapped[str] = mapped_column(String(40), primary_key=True)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(80)), server_default="{}")
    group_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    relatives: Mapped[list[str]] = mapped_column(ARRAY(String(30)), server_default="{}")
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confirmation: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    after_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")


class AssignmentSettings(TenantKeyed, Timestamps, Actors, Versioned, Base):
    """Auto-assignment of one support group (REQ-ASG-002); off unless switched on (D-097)."""

    __tablename__ = "assignment_settings"
    __table_args__ = (
        CheckConstraint(_codes("method", AssignMethod), name="method_code"),
        CheckConstraint("load_cap IS NULL OR load_cap BETWEEN 1 AND 1000", name="load_cap_range"),
        _group_fk("group_id", "fk_assignment_settings_group"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    method: Mapped[str] = mapped_column(String(20), server_default=AssignMethod.ROUND_ROBIN.value)
    # Record types it applies to (every type when empty).
    record_types: Mapped[list[str]] = mapped_column(ARRAY(String(30)), server_default="{}")
    on_create: Mapped[bool] = mapped_column(Boolean, server_default="true")
    on_move: Mapped[bool] = mapped_column(Boolean, server_default="true")
    unassigned_only: Mapped[bool] = mapped_column(Boolean, server_default="true")
    count_paused: Mapped[bool] = mapped_column(Boolean, server_default="false")
    load_cap: Mapped[int | None]


class AssignmentTurn(TenantKeyed, Base):
    """When a member last got a record by auto-assignment in a group (round robin, ties)."""

    __tablename__ = "assignment_turns"
    __table_args__ = (_group_fk("group_id", "fk_assignment_turns_group"),)

    group_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    last_assigned_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TechnicianAvailability(TenantKeyed, Base):
    """A technician's own Available / Away state (REQ-ASG-006; D-097). No row: available."""

    __tablename__ = "technician_availability"
    __table_args__ = (CheckConstraint(_codes("state", Availability), name="state_code"),)

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    state: Mapped[str] = mapped_column(String(20))
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    changed_by: Mapped[uuid.UUID | None]


class AutomationTrigger(TenantEntity):
    """A trigger: runs after a change is committed, from its event (REQ-RUL-009, 010)."""

    __tablename__ = "automation_triggers"
    __table_args__ = (
        CheckConstraint(_codes("state", RuleState), name="state_code"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint("cardinality(events) >= 1", name="events_present"),
        Index(
            "ix_automation_triggers_tenant_type_position", "tenant_id", "record_type", "position"
        ),
    )

    record_type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    events: Mapped[list[str]] = mapped_column(ARRAY(String(80)))
    site_id: Mapped[uuid.UUID | None]
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # REQ-RUL-028 AC2: never fires on the change its own action made unless the admin allows it.
    fire_on_own_change: Mapped[bool] = mapped_column(Boolean, server_default="false")
    position: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), server_default=RuleState.DRAFT.value)
    owner_id: Mapped[uuid.UUID | None]


class AutomationRun(UuidPrimaryKey, TenantScoped, Base):
    """One automation step on one record (the execution log, REQ-RUL-006, 028; kept 30 days).

    Insert-only. `detail` names fields, rules, methods and loads, never the record's values.
    """

    __tablename__ = "automation_runs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('business_rule', 'routing', 'assignment', 'trigger', 'loop_guard')",
            name="kind_code",
        ),
        Index("ix_automation_runs_tenant_record", "tenant_id", "record_id", "occurred_at"),
        Index("ix_automation_runs_tenant_time", "tenant_id", "occurred_at"),
    )

    record_type: Mapped[str] = mapped_column(String(30))
    record_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(20))
    automation_id: Mapped[uuid.UUID | None]
    automation_name: Mapped[str | None] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(String(30))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    change_id: Mapped[uuid.UUID | None]
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
