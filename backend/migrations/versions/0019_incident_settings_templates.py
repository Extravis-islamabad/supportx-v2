"""Incident settings and templates (WP-020c).

- work_item_templates: incident templates (REQ-INC-035): shown / required fields, starting
  values, requester flags for the portal, default and disabled. RLS; the app may read, insert
  and update, never delete (templates are disabled, not removed).
- work_items.template_id, level (REQ-INC-007) and impact_details (REQ-INC-001).
- work_item_reasons becomes the pick-list table: lists `level` and `closure_code` join the
  reason lists, and values get an optional colour (REQ-ADM-043).
- work_item_type_settings.seed_version: which defaults a tenant has been given. Tenants seeded
  before WP-020c (version 1) get the levels, closure codes and the standard template on their
  next read, inside that transaction, the same safe way first use seeds everything.
- users.form_density: comfortable or compact record forms, per user.

Additive (expand only; reversible).

Revision ID: 0019
Revises: 0018
Created: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASON_LISTS = ("pause", "third_party", "cancel", "reopen", "reassign")
PICK_LISTS = (*REASON_LISTS, "level", "closure_code")


def _in(column: str, codes: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def upgrade() -> None:
    op.create_table(
        "work_item_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=True),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("group_name", sa.String(length=60), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("for_requesters", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "field_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "defaults", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("copied_from_id", sa.UUID(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('incident', 'service_request', 'problem', 'change', 'release')",
            name=op.f("ck_work_item_templates_type_code"),
        ),
        sa.CheckConstraint(
            "code IS NOT NULL OR labels IS NOT NULL", name=op.f("ck_work_item_templates_named")
        ),
        sa.CheckConstraint(
            "code IS NULL OR code ~ '^[a-z][a-z0-9_]{1,39}$'",
            name=op.f("ck_work_item_templates_code_format"),
        ),
        sa.CheckConstraint(
            "NOT (is_default AND disabled_at IS NOT NULL)",
            name=op.f("ck_work_item_templates_default_enabled"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "copied_from_id"],
            ["work_item_templates.tenant_id", "work_item_templates.id"],
            name="fk_work_item_templates_copied_from",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_work_item_templates_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item_templates")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_work_item_templates_tenant_id_id"),
    )
    op.create_index(
        "ix_work_item_templates_tenant_type",
        "work_item_templates",
        ["tenant_id", "type", "disabled_at"],
        unique=False,
    )
    op.create_index(
        "uq_work_item_templates_tenant_type_default",
        "work_item_templates",
        ["tenant_id", "type"],
        unique=True,
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
    )
    enable_tenant_rls("work_item_templates")
    grant_app("work_item_templates", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("work_item_templates")

    op.add_column("work_items", sa.Column("impact_details", sa.Text(), nullable=True))
    op.add_column("work_items", sa.Column("level", sa.String(length=40), nullable=True))
    op.add_column("work_items", sa.Column("template_id", sa.UUID(), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_items_impact_details_length"),
        "work_items",
        "impact_details IS NULL OR char_length(impact_details) <= 2000",
    )
    op.create_foreign_key(
        "fk_wi_template",
        "work_items",
        "work_item_templates",
        ["tenant_id", "template_id"],
        ["tenant_id", "id"],
    )

    op.add_column("work_item_reasons", sa.Column("colour", sa.String(length=7), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_item_reasons_colour_format"),
        "work_item_reasons",
        "colour IS NULL OR colour ~ '^#[0-9a-fA-F]{6}$'",
    )
    op.drop_constraint(op.f("ck_work_item_reasons_list_code"), "work_item_reasons", type_="check")
    op.create_check_constraint(
        op.f("ck_work_item_reasons_list_code"), "work_item_reasons", _in("list", PICK_LISTS)
    )

    op.add_column(
        "work_item_type_settings",
        sa.Column("seed_version", sa.Integer(), server_default="1", nullable=False),
    )

    op.add_column(
        "users",
        sa.Column("form_density", sa.String(), server_default="comfortable", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_users_form_density_code"), "users", "form_density IN ('comfortable', 'compact')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_form_density_code"), "users", type_="check")
    op.drop_column("users", "form_density")
    op.drop_column("work_item_type_settings", "seed_version")
    # Values of the new lists cannot satisfy the old check: they go with the downgrade.
    op.execute("DELETE FROM work_item_reasons WHERE list IN ('level', 'closure_code')")
    op.drop_constraint(op.f("ck_work_item_reasons_list_code"), "work_item_reasons", type_="check")
    op.create_check_constraint(
        op.f("ck_work_item_reasons_list_code"), "work_item_reasons", _in("list", REASON_LISTS)
    )
    op.drop_constraint(
        op.f("ck_work_item_reasons_colour_format"), "work_item_reasons", type_="check"
    )
    op.drop_column("work_item_reasons", "colour")
    op.drop_constraint("fk_wi_template", "work_items", type_="foreignkey")
    op.drop_constraint(op.f("ck_work_items_impact_details_length"), "work_items", type_="check")
    op.drop_column("work_items", "template_id")
    op.drop_column("work_items", "level")
    op.drop_column("work_items", "impact_details")
    op.drop_index(
        "uq_work_item_templates_tenant_type_default",
        table_name="work_item_templates",
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
    )
    op.drop_index("ix_work_item_templates_tenant_type", table_name="work_item_templates")
    op.drop_table("work_item_templates")
