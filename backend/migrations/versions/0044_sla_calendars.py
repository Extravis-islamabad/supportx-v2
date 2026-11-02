"""SLA calendars (WP-025 session 1): working calendars, holiday lists, holidays, their links.

Tenant-scoped with RLS. Calendars, their special date-range hours, holiday lists and holidays
are soft deleted; the link from a
calendar to its holiday lists is replaced on edit (DELETE granted). Sites and support groups
name their calendar (`calendar_id`, REQ-ADM-040, D-115 D3) through a same-tenant foreign key.
Every tenant's two system calendars ("around the clock" and the default operating hours) are
created on first use by the service, not here (D-041).

Revision ID: 0044
Revises: 0043
Created: 2026-11-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNITS = ("sites", "support_groups")


# Any: these lists mix column types (datetime, uuid, int), as op.create_table accepts.
def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _named(table: str) -> None:
    """Names are unique per tenant among live rows, ignoring case."""
    op.create_index(
        f"uq_{table}_tenant_id_name",
        table,
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def upgrade() -> None:
    op.create_table(
        "sla_calendars",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("labels", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=20), server_default="hours", nullable=False),
        sa.Column("week", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("system_key", sa.String(length=30), nullable=True),
        *_timestamps(),
        _tenant_fk("sla_calendars"),
        sa.CheckConstraint(
            "kind IN ('hours', 'around_the_clock')", name=op.f("ck_sla_calendars_kind_code")
        ),
        sa.CheckConstraint(
            "system_key IS NULL OR system_key IN ('around_the_clock', 'operating_hours')",
            name=op.f("ck_sla_calendars_system_key_code"),
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f("ck_sla_calendars_name_length")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(week) = 'array'", name=op.f("ck_sla_calendars_week_array")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_calendars")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sla_calendars_tenant_id_id"),
    )
    _named("sla_calendars")
    op.create_index(
        "uq_sla_calendars_tenant_id_system_key",
        "sla_calendars",
        ["tenant_id", "system_key"],
        unique=True,
        postgresql_where=sa.text("system_key IS NOT NULL AND deleted_at IS NULL"),
    )

    op.create_table(
        "sla_holiday_lists",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("labels", postgresql.JSONB(), server_default="{}", nullable=False),
        *_timestamps(),
        _tenant_fk("sla_holiday_lists"),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f("ck_sla_holiday_lists_name_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_holiday_lists")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sla_holiday_lists_tenant_id_id"),
    )
    _named("sla_holiday_lists")

    op.create_table(
        "sla_holidays",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("list_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("part", sa.String(length=10), server_default="full", nullable=False),
        sa.Column("needs_review", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("origin", sa.String(length=10), server_default="manual", nullable=False),
        *_timestamps(),
        _tenant_fk("sla_holidays"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "list_id"],
            ["sla_holiday_lists.tenant_id", "sla_holiday_lists.id"],
            name="fk_sla_holidays_list",
        ),
        sa.CheckConstraint(
            "part IN ('full', 'morning', 'afternoon')", name=op.f("ck_sla_holidays_part_code")
        ),
        sa.CheckConstraint(
            "origin IN ('manual', 'import', 'copy')", name=op.f("ck_sla_holidays_origin_code")
        ),
        sa.CheckConstraint("ends_on >= starts_on", name=op.f("ck_sla_holidays_range_order")),
        # A half day is one day; a range is whole days.
        sa.CheckConstraint(
            "part = 'full' OR ends_on = starts_on", name=op.f("ck_sla_holidays_half_day_single")
        ),
        sa.CheckConstraint("ends_on - starts_on < 366", name=op.f("ck_sla_holidays_range_length")),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f("ck_sla_holidays_name_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_holidays")),
    )
    op.create_index(
        "ix_sla_holidays_tenant_id_list_id_starts_on",
        "sla_holidays",
        ["tenant_id", "list_id", "starts_on"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "sla_calendar_holidays",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("list_id", sa.Uuid(), nullable=False),
        _tenant_fk("sla_calendar_holidays"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["sla_calendars.tenant_id", "sla_calendars.id"],
            name="fk_sla_calendar_holidays_calendar",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "list_id"],
            ["sla_holiday_lists.tenant_id", "sla_holiday_lists.id"],
            name="fk_sla_calendar_holidays_list",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "calendar_id", "list_id", name=op.f("pk_sla_calendar_holidays")
        ),
    )
    op.create_index(
        "ix_sla_calendar_holidays_tenant_list", "sla_calendar_holidays", ["tenant_id", "list_id"]
    )

    # Special working hours for a date range (Ramadan, a Friday prayer break; product owner
    # 2026-11-02): inside the range its own week replaces the calendar's week. Ranges of one
    # calendar never overlap (checked by the service under a lock on the calendar).
    op.create_table(
        "sla_calendar_exceptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("week", postgresql.JSONB(), server_default="[]", nullable=False),
        *_timestamps(),
        _tenant_fk("sla_calendar_exceptions"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["sla_calendars.tenant_id", "sla_calendars.id"],
            name="fk_sla_calendar_exceptions_calendar",
        ),
        sa.CheckConstraint(
            "ends_on >= starts_on", name=op.f("ck_sla_calendar_exceptions_range_order")
        ),
        sa.CheckConstraint(
            "ends_on - starts_on < 366", name=op.f("ck_sla_calendar_exceptions_range_length")
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200",
            name=op.f("ck_sla_calendar_exceptions_name_length"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(week) = 'array'", name=op.f("ck_sla_calendar_exceptions_week_array")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_calendar_exceptions")),
    )
    op.create_index(
        "ix_sla_calendar_exceptions_tenant_calendar",
        "sla_calendar_exceptions",
        ["tenant_id", "calendar_id", "starts_on"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    for table in ("sla_calendars", "sla_holiday_lists", "sla_holidays", "sla_calendar_exceptions"):
        enable_tenant_rls(table)
        enable_actor_audit(table)
        grant_app(table, ("SELECT", "INSERT", "UPDATE"))
    enable_tenant_rls("sla_calendar_holidays")
    grant_app("sla_calendar_holidays", ("SELECT", "INSERT", "DELETE"))

    # Sites and support groups name their calendar (organization's own data; D-115 D3).
    for table in _UNITS:
        op.add_column(table, sa.Column("calendar_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_calendar",
            table,
            "sla_calendars",
            ["tenant_id", "calendar_id"],
            ["tenant_id", "id"],
        )
        op.create_index(
            f"ix_{table}_tenant_id_calendar_id",
            table,
            ["tenant_id", "calendar_id"],
            postgresql_where=sa.text("calendar_id IS NOT NULL"),
        )


def downgrade() -> None:
    for table in _UNITS:
        op.drop_index(f"ix_{table}_tenant_id_calendar_id", table_name=table)
        op.drop_constraint(f"fk_{table}_calendar", table, type_="foreignkey")
        op.drop_column(table, "calendar_id")
    op.drop_table("sla_calendar_exceptions")
    op.drop_table("sla_calendar_holidays")
    op.drop_table("sla_holidays")
    op.drop_table("sla_holiday_lists")
    op.drop_table("sla_calendars")
