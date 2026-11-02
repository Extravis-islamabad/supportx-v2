"""SLA tables (WP-025). Every table is tenant-scoped with RLS (migration 0044)."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed, utc_now


class SlaCalendar(TenantEntity):
    """A working calendar: a week of periods in one time zone (REQ-SLA-010).

    `week` holds `[{"weekday": 0-6, "start": "HH:MM", "end": "HH:MM"}, ...]`; an end not after
    its start crosses midnight. `system_key` marks the two calendars every tenant has: around
    the clock (it cannot change) and the default operating hours (it can, but not be deleted).
    """

    __tablename__ = "sla_calendars"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sla_calendars_tenant_id_id"),
        CheckConstraint("kind IN ('hours', 'around_the_clock')", name="kind_code"),
        CheckConstraint(
            "system_key IS NULL OR system_key IN ('around_the_clock', 'operating_hours')",
            name="system_key_code",
        ),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint("jsonb_typeof(week) = 'array'", name="week_array"),
        Index(
            "uq_sla_calendars_tenant_id_name",
            "tenant_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_sla_calendars_tenant_id_system_key",
            "tenant_id",
            "system_key",
            unique=True,
            postgresql_where=text("system_key IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200))
    # Names in other languages {"ar": ..., "ur": ...}; the name itself is the fallback.
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    time_zone: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20), server_default="hours")
    week: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    system_key: Mapped[str | None] = mapped_column(String(30))


class SlaCalendarException(TenantEntity):
    """Special working hours for a date range of one calendar (Ramadan, a Friday prayer break).

    `week` has the calendar's week format; inside the range it replaces the calendar's week.
    """

    __tablename__ = "sla_calendar_exceptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["sla_calendars.tenant_id", "sla_calendars.id"],
            name="fk_sla_calendar_exceptions_calendar",
        ),
        CheckConstraint("ends_on >= starts_on", name="range_order"),
        CheckConstraint("ends_on - starts_on < 366", name="range_length"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint("jsonb_typeof(week) = 'array'", name="week_array"),
        Index(
            "ix_sla_calendar_exceptions_tenant_calendar",
            "tenant_id",
            "calendar_id",
            "starts_on",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    calendar_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(200))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    week: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")


class SlaHolidayList(TenantEntity):
    """A named list of holidays, attached to calendars (REQ-SLA-012)."""

    __tablename__ = "sla_holiday_lists"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sla_holiday_lists_tenant_id_id"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        Index(
            "uq_sla_holiday_lists_tenant_id_name",
            "tenant_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200))
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")


class SlaHoliday(TenantEntity):
    """One holiday: a date or a range of whole days, or a half day (REQ-SLA-012)."""

    __tablename__ = "sla_holidays"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "list_id"],
            ["sla_holiday_lists.tenant_id", "sla_holiday_lists.id"],
            name="fk_sla_holidays_list",
        ),
        CheckConstraint("part IN ('full', 'morning', 'afternoon')", name="part_code"),
        CheckConstraint("origin IN ('manual', 'import', 'copy')", name="origin_code"),
        CheckConstraint("ends_on >= starts_on", name="range_order"),
        CheckConstraint("part = 'full' OR ends_on = starts_on", name="half_day_single"),
        CheckConstraint("ends_on - starts_on < 366", name="range_length"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        Index(
            "ix_sla_holidays_tenant_id_list_id_starts_on",
            "tenant_id",
            "list_id",
            "starts_on",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    list_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(200))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    part: Mapped[str] = mapped_column(String(10), server_default="full")
    # Copied to the next year: the date may move (Eid), so someone should check it.
    needs_review: Mapped[bool] = mapped_column(Boolean, server_default="false")
    origin: Mapped[str] = mapped_column(String(10), server_default="manual")


class SlaCalendarHoliday(TenantKeyed, Base):
    """Which holiday lists a calendar uses (replaced on edit)."""

    __tablename__ = "sla_calendar_holidays"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["sla_calendars.tenant_id", "sla_calendars.id"],
            name="fk_sla_calendar_holidays_calendar",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "list_id"],
            ["sla_holiday_lists.tenant_id", "sla_holiday_lists.id"],
            name="fk_sla_calendar_holidays_list",
        ),
        Index("ix_sla_calendar_holidays_tenant_list", "tenant_id", "list_id"),
    )

    calendar_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    list_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)


# --- session 2: policies and per-record clocks (migration 0047) ----------------------------------

_KINDS = "kind IN ('first_response', 'resolution')"
_RECORD_TYPE = "record_type ~ '^[a-z][a-z_]{1,29}$'"


class SlaPolicy(TenantEntity):
    """An SLA policy for one record type: conditions, position, targets (REQ-SLA-001..005)."""

    __tablename__ = "sla_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sla_policies_tenant_id_id"),
        CheckConstraint(_RECORD_TYPE, name="record_type_code"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint("NOT fallback OR (conditions IS NULL AND enabled)", name="fallback_shape"),
        Index(
            "uq_sla_policies_tenant_type_fallback",
            "tenant_id",
            "record_type",
            unique=True,
            postgresql_where=text("fallback AND deleted_at IS NULL"),
        ),
        Index(
            "uq_sla_policies_tenant_type_name",
            "tenant_id",
            "record_type",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_sla_policies_tenant_type_position",
            "tenant_id",
            "record_type",
            "position",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    record_type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    description: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    position: Mapped[int] = mapped_column(Integer)
    fallback: Mapped[bool] = mapped_column(Boolean, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    pausing: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), server_default="{first_response,resolution}"
    )


class SlaPolicyTarget(TenantKeyed, Base):
    """One row of a policy's target table (replaced on save)."""

    __tablename__ = "sla_policy_targets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["sla_policies.tenant_id", "sla_policies.id"],
            name="fk_sla_policy_targets_policy",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "fixed_calendar_id"],
            ["sla_calendars.tenant_id", "sla_calendars.id"],
            name="fk_sla_policy_targets_calendar",
        ),
        CheckConstraint(_KINDS, name="kind_code"),
        CheckConstraint("unit IN ('minutes', 'hours', 'business_days')", name="unit_code"),
        CheckConstraint(
            "source IN ('site', 'group', 'fixed', 'around_the_clock')", name="source_code"
        ),
        CheckConstraint("amount IS NULL OR amount BETWEEN 1 AND 100000", name="amount_range"),
        CheckConstraint(
            "(source = 'fixed') = (fixed_calendar_id IS NOT NULL)", name="fixed_calendar"
        ),
        Index(
            "uq_sla_policy_targets_row",
            "tenant_id",
            "policy_id",
            "kind",
            text("coalesce(priority, '*')"),
            unique=True,
        ),
        Index(
            "ix_sla_policy_targets_tenant_calendar",
            "tenant_id",
            "fixed_calendar_id",
            postgresql_where=text("fixed_calendar_id IS NOT NULL"),
        ),
    )

    # The primary key is (tenant_id, id); TenantKeyed puts tenant_id first.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    policy_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str | None] = mapped_column(String(10))
    amount: Mapped[int | None] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20), server_default="site")
    fixed_calendar_id: Mapped[uuid.UUID | None]


class SlaSettings(TenantKeyed, Base):
    """Per tenant and record type: warning point, priority-change and reopen rules (D-115 D2)."""

    __tablename__ = "sla_settings"
    __table_args__ = (
        CheckConstraint(_RECORD_TYPE, name="record_type_code"),
        CheckConstraint("warning_percent BETWEEN 1 AND 99", name="warning_range"),
        CheckConstraint("priority_rule IN ('recalculate', 'restart')", name="priority_rule_code"),
        CheckConstraint("reopen_rule IN ('resume', 'restart')", name="reopen_rule_code"),
    )

    record_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    warning_percent: Mapped[int] = mapped_column(SmallInteger, server_default="75")
    priority_rule: Mapped[str] = mapped_column(String(20), server_default="recalculate")
    reopen_rule: Mapped[str] = mapped_column(String(20), server_default="resume")
    version: Mapped[int] = mapped_column(BigInteger, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    updated_by: Mapped[uuid.UUID | None]


class SlaApplication(TenantKeyed, Base):
    """Which policy a record got, when and why, with a snapshot of its targets (D-115 D7)."""

    __tablename__ = "sla_applications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["sla_policies.tenant_id", "sla_policies.id"],
            name="fk_sla_applications_policy",
        ),
        CheckConstraint(_RECORD_TYPE, name="record_type_code"),
        CheckConstraint(
            "reason IN ('created', 'condition_changed', 'priority_changed', 'policy_changed')",
            name="reason_code",
        ),
        Index(
            "uq_sla_applications_current",
            "tenant_id",
            "record_id",
            unique=True,
            postgresql_where=text("current"),
        ),
        Index("ix_sla_applications_tenant_record", "tenant_id", "record_id", "applied_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    record_type: Mapped[str] = mapped_column(String(30))
    record_id: Mapped[uuid.UUID]
    policy_id: Mapped[uuid.UUID | None]
    policy_version: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(20))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    applied_at: Mapped[datetime]
    current: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    created_by: Mapped[uuid.UUID | None]
    updated_by: Mapped[uuid.UUID | None]
    version: Mapped[int] = mapped_column(BigInteger, server_default="1")


class SlaTarget(TenantKeyed, Base):
    """One target clock of one record, per round (REQ-SLA-015..020, 029)."""

    __tablename__ = "sla_targets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sla_targets_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["sla_calendars.tenant_id", "sla_calendars.id"],
            name="fk_sla_targets_calendar",
        ),
        CheckConstraint(_RECORD_TYPE, name="record_type_code"),
        CheckConstraint(_KINDS, name="kind_code"),
        CheckConstraint(
            "state IN ('running', 'paused', 'met', 'breached', 'stopped')", name="state_code"
        ),
        CheckConstraint(
            "met_how IS NULL OR met_how IN ('on_time', 'late', 'at_resolution')",
            name="met_how_code",
        ),
        CheckConstraint(
            "breach_reason IS NULL OR breach_reason IN ('time_passed', 'target_changed')",
            name="breach_reason_code",
        ),
        CheckConstraint(
            "target_seconds >= 0 AND used_seconds >= 0 AND paused_seconds >= 0",
            name="seconds_positive",
        ),
        Index("uq_sla_targets_round", "tenant_id", "record_id", "kind", "round", unique=True),
        Index(
            "ix_sla_targets_tenant_due",
            "tenant_id",
            "due_at",
            postgresql_where=text("state IN ('running', 'breached') AND due_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    record_type: Mapped[str] = mapped_column(String(30))
    record_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(20))
    round: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    calendar_id: Mapped[uuid.UUID | None]
    target_seconds: Mapped[int] = mapped_column(BigInteger)
    used_seconds: Mapped[int] = mapped_column(BigInteger, server_default="0")
    paused_seconds: Mapped[int] = mapped_column(BigInteger, server_default="0")
    state: Mapped[str] = mapped_column(String(20))
    running_since: Mapped[datetime | None]
    paused_since: Mapped[datetime | None]
    due_at: Mapped[datetime | None]
    warning_at: Mapped[datetime | None]
    met_at: Mapped[datetime | None]
    met_how: Mapped[str | None] = mapped_column(String(20))
    warned_at: Mapped[datetime | None]
    breached_at: Mapped[datetime | None]
    breach_seconds: Mapped[int | None] = mapped_column(BigInteger)
    breach_reason: Mapped[str | None] = mapped_column(String(20))
    manual_due_at: Mapped[datetime | None]
    manual_by: Mapped[uuid.UUID | None]
    manual_reason: Mapped[str | None] = mapped_column(String(500))
    manual_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    created_by: Mapped[uuid.UUID | None]
    updated_by: Mapped[uuid.UUID | None]
    version: Mapped[int] = mapped_column(BigInteger, server_default="1")


class SlaPause(TenantKeyed, Base):
    """One pause of one target: when, why (the status) and who (REQ-SLA-016)."""

    __tablename__ = "sla_pauses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "target_id"],
            ["sla_targets.tenant_id", "sla_targets.id"],
            name="fk_sla_pauses_target",
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="range_order"),
        Index("ix_sla_pauses_tenant_target", "tenant_id", "target_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    target_id: Mapped[uuid.UUID]
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    cause: Mapped[str | None] = mapped_column(String(40))
    person_id: Mapped[uuid.UUID | None]
    business_seconds: Mapped[int | None] = mapped_column(BigInteger)
    calendar_seconds: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
