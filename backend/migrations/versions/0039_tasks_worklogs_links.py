"""Tasks, worklogs and links (WP-020e; REQ-INC-067, 072, 084).

- work_item_tasks: tasks on a record with their own status, owner, group, priority, due time
  and position; open ones are the record's open work (WP-020f port);
- work_item_worklogs: time spent (start, end, minutes always agree);
- work_item_links: two records linked, `related` (symmetrical) or `follows`; WP-020f's
  `work_items.follows_id` is copied in as `follows` links (the column stays until the contract
  step);
- work_item_type_settings.task_owner_access: a task's owner may work on it without access to
  the record (off by default).

All tenant-scoped with RLS and actor audit. The copy runs per tenant: the tables force RLS, so a
statement without app.tenant_id would see no rows (see 0034). Reversible.

Revision ID: 0039
Revises: 0038
Created: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FOLLOWS_TO_LINKS = """
DO $$
DECLARE
    t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        INSERT INTO work_item_links (id, tenant_id, source_id, target_id, kind)
        SELECT gen_random_uuid(), t, w.id, w.follows_id, 'follows'
        FROM work_items w
        WHERE w.tenant_id = t AND w.follows_id IS NOT NULL;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""


def upgrade() -> None:
    op.create_table(
        "work_item_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=True),
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
            "kind <> 'related' OR source_id < target_id",
            name=op.f("ck_work_item_links_related_in_order"),
        ),
        sa.CheckConstraint(
            "kind IN ('related', 'follows')", name=op.f("ck_work_item_links_kind_code")
        ),
        sa.CheckConstraint(
            "comment IS NULL OR char_length(comment) <= 500",
            name=op.f("ck_work_item_links_comment_length"),
        ),
        sa.CheckConstraint("source_id <> target_id", name=op.f("ck_work_item_links_not_itself")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_wil_source",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_wil_target",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_work_item_links_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item_links")),
    )
    op.create_index(
        "ix_wil_tenant_target",
        "work_item_links",
        ["tenant_id", "target_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_wil_tenant_pair_kind",
        "work_item_links",
        ["tenant_id", "source_id", "target_id", "kind"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("work_item_links")
    enable_actor_audit("work_item_links")
    grant_app("work_item_links", ("SELECT", "INSERT", "UPDATE"))
    op.create_table(
        "work_item_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("work_item_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("priority", sa.String(length=10), server_default="normal", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
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
            "priority IN ('low', 'normal', 'high')", name=op.f("ck_work_item_tasks_priority_code")
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'done', 'canceled')",
            name=op.f("ck_work_item_tasks_status_code"),
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 4000",
            name=op.f("ck_work_item_tasks_description_length"),
        ),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 200", name=op.f("ck_work_item_tasks_title_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            name="fk_wit_group",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_wit_owner"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_wit_work_item",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_work_item_tasks_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item_tasks")),
    )
    op.create_index(
        "ix_wit_tenant_item_position",
        "work_item_tasks",
        ["tenant_id", "work_item_id", "position", "id"],
        unique=False,
    )
    op.create_index(
        "ix_wit_tenant_owner_open",
        "work_item_tasks",
        ["tenant_id", "owner_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL AND status IN ('open', 'in_progress')"),
    )
    enable_tenant_rls("work_item_tasks")
    enable_actor_audit("work_item_tasks")
    grant_app("work_item_tasks", ("SELECT", "INSERT", "UPDATE"))
    op.create_table(
        "work_item_worklogs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("work_item_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("worklog_type", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
            "worklog_type IN ('investigation', 'fix', 'communication', 'travel', 'other')",
            name=op.f("ck_work_item_worklogs_worklog_type_code"),
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 4000",
            name=op.f("ck_work_item_worklogs_description_length"),
        ),
        sa.CheckConstraint(
            "ended_at >= started_at", name=op.f("ck_work_item_worklogs_end_after_start")
        ),
        sa.CheckConstraint(
            "minutes BETWEEN 1 AND 10080", name=op.f("ck_work_item_worklogs_minutes_range")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_wiw_owner"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_wiw_work_item",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_work_item_worklogs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item_worklogs")),
    )
    op.create_index(
        "ix_wiw_tenant_item_start",
        "work_item_worklogs",
        ["tenant_id", "work_item_id", "started_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_wiw_tenant_owner_start",
        "work_item_worklogs",
        ["tenant_id", "owner_id", "started_at"],
        unique=False,
    )
    enable_tenant_rls("work_item_worklogs")
    enable_actor_audit("work_item_worklogs")
    grant_app("work_item_worklogs", ("SELECT", "INSERT", "UPDATE"))
    op.add_column(
        "work_item_type_settings",
        sa.Column("task_owner_access", sa.Boolean(), server_default="false", nullable=False),
    )
    op.execute(FOLLOWS_TO_LINKS)


def downgrade() -> None:
    op.drop_column("work_item_type_settings", "task_owner_access")
    op.drop_index("ix_wiw_tenant_owner_start", table_name="work_item_worklogs")
    op.drop_index("ix_wiw_tenant_item_start", table_name="work_item_worklogs")
    op.drop_table("work_item_worklogs")
    op.drop_index(
        "ix_wit_tenant_owner_open",
        table_name="work_item_tasks",
        postgresql_where=sa.text("deleted_at IS NULL AND status IN ('open', 'in_progress')"),
    )
    op.drop_index("ix_wit_tenant_item_position", table_name="work_item_tasks")
    op.drop_table("work_item_tasks")
    op.drop_index(
        "uq_wil_tenant_pair_kind",
        table_name="work_item_links",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_wil_tenant_target",
        table_name="work_item_links",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("work_item_links")
