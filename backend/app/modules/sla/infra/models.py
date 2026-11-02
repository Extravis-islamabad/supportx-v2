"""SLA tables (WP-025). Every table is tenant-scoped with RLS (migration 0044)."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed


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
