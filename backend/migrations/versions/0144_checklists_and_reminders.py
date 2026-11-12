"""Checklists and personal reminders on work items (WP-046a S2; REQ-INC-040, 077, 078, 082), 0144.

Expand only, no data step:
- `work_item_checklists` (RLS): a record's checklists, in order, with the library checklist it
  was copied from (the copy is the record's own, REQ-INC-077 AC3);
- `work_item_checklist_items` (RLS): each item, in order, with who ticked it and when (AC1);
- `checklist_library` (RLS): an admin's checklists per work item type, translatable names
  (REQ-INC-078 AC2) and their items, disabled when no longer offered;
- `work_item_reminders` (RLS): a person's own reminder on a record (REQ-INC-082): a note, when,
  how long before to alert, when it alerted, when it was completed;
- `work_item_type_settings.checklist_item_max`: the most items one checklist may hold (100);
- `work_item_templates.checklists`: the checklists a record template adds (REQ-INC-040).

The downgrade refuses while any tenant uses what it would drop (rule 5h); otherwise it drops it.

Revision ID: 0144
Revises: 0146
Created: 2026-11-11
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0144"
down_revision: str | None = "0146"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKLISTS, ITEMS, LIBRARY, REMINDERS = (
    "work_item_checklists",
    "work_item_checklist_items",
    "checklist_library",
    "work_item_reminders",
)
SETTINGS, TEMPLATES = "work_item_type_settings", "work_item_templates"
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {CHECKLISTS}) OR EXISTS (SELECT 1 FROM {LIBRARY})
           OR EXISTS (SELECT 1 FROM {REMINDERS})
           OR EXISTS (SELECT 1 FROM {TEMPLATES} WHERE checklists <> '[]'::jsonb)
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has checklists or reminders (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def _stamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def _entity(name: str, *columns: Any, checks: Sequence[tuple[str, str]] = ()) -> None:  # noqa: ANN401 - SQLAlchemy columns and constraints
    op.create_table(
        name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        *columns,
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        *(sa.CheckConstraint(sql, name=op.f(f"ck_{name}_{label}")) for label, sql in checks),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{name}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    enable_tenant_rls(name)
    enable_actor_audit(name)
    grant_app(name, ("SELECT", "INSERT", "UPDATE"))


def _record_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "work_item_id"], ["work_items.tenant_id", "work_items.id"], name=name
    )


def upgrade() -> None:
    """The four tables, the item limit and the record templates' checklists."""
    _entity(
        CHECKLISTS,
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("library_id", sa.Uuid(), nullable=True),
        _record_fk("fk_wicl_work_item"),
        checks=[("title_length", "length(btrim(title)) BETWEEN 1 AND 200")],
    )
    op.create_index(
        "ix_wicl_tenant_item_position",
        CHECKLISTS,
        ["tenant_id", "work_item_id", "position"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    _entity(
        ITEMS,
        sa.Column("checklist_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(500), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_by", sa.Uuid(), nullable=True),
        _record_fk("fk_wicli_work_item"),
        sa.ForeignKeyConstraint(
            ["checklist_id"],
            [f"{CHECKLISTS}.id"],
            name=op.f(f"fk_{ITEMS}_checklist_id_{CHECKLISTS}"),
        ),
        checks=[
            ("text_length", "length(btrim(text)) BETWEEN 1 AND 500"),
            ("done_pair", "done_by IS NULL OR done_at IS NOT NULL"),  # system ticks: no person
        ],
    )
    op.create_index(
        "ix_wicli_tenant_checklist_position",
        ITEMS,
        ["tenant_id", "checklist_id", "position"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    _entity(
        LIBRARY,
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=True),
        sa.Column(
            "items", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        checks=[("items_array", "jsonb_typeof(items) = 'array'")],
    )
    op.create_index(
        "ix_checklist_library_tenant_type",
        LIBRARY,
        ["tenant_id", "type"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    _entity(
        REMINDERS,
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alert_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        _record_fk("fk_wir_work_item"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_wir_user"
        ),
        checks=[
            ("note_length", "length(btrim(note)) BETWEEN 1 AND 500"),
            ("alert_range", "alert_minutes BETWEEN 0 AND 10080"),
        ],
    )
    op.create_index(
        "ix_wir_tenant_user_open",
        REMINDERS,
        ["tenant_id", "user_id", "remind_at"],
        postgresql_where=sa.text("deleted_at IS NULL AND done_at IS NULL"),
    )
    op.create_index(
        "ix_wir_tenant_item", REMINDERS, ["tenant_id", "work_item_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )  # fmt: skip
    op.add_column(
        SETTINGS,
        sa.Column("checklist_item_max", sa.Integer(), server_default="100", nullable=False),
    )
    op.create_check_constraint(
        op.f(f"ck_{SETTINGS}_checklist_item_max_range"),
        SETTINGS,
        "checklist_item_max BETWEEN 1 AND 1000",
    )
    op.add_column(
        TEMPLATES,
        sa.Column(
            "checklists", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
    )


def downgrade() -> None:
    """Back to before (stops while any tenant has checklists, library entries or reminders)."""
    op.execute(GUARD)
    op.drop_column(TEMPLATES, "checklists")
    op.drop_constraint(op.f(f"ck_{SETTINGS}_checklist_item_max_range"), SETTINGS, type_="check")
    op.drop_column(SETTINGS, "checklist_item_max")
    op.drop_index("ix_wir_tenant_item", table_name=REMINDERS)
    op.drop_index("ix_wir_tenant_user_open", table_name=REMINDERS)
    op.drop_table(REMINDERS)
    op.drop_index("ix_checklist_library_tenant_type", table_name=LIBRARY)
    op.drop_table(LIBRARY)
    op.drop_index("ix_wicli_tenant_checklist_position", table_name=ITEMS)
    op.drop_table(ITEMS)
    op.drop_index("ix_wicl_tenant_item_position", table_name=CHECKLISTS)
    op.drop_table(CHECKLISTS)
