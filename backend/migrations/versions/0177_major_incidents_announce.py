"""Major incidents and announcing from an incident (WP-046b S4), 0177.

Expand only, no data step:
- `work_items.major` with when, by whom and why it was declared (REQ-INC-141). The reason is free
  text (possibly personal data): it lives here and in the audit entry's personal part, never in
  field history values (lane B).
- `work_item_type_settings.major_group_id`, `major_user_ids`, `major_template_id`: who is told
  when an incident is declared major, and the template it switches to (none: it keeps its own).
- `work_item_announcements`: which announcements were made from which record (REQ-INC-129). Kept
  by work_items; no foreign key into the announcements module (rule 5e).
- The bulk jobs' action check also allows `attach_child` (similar incidents attached as children
  of a major incident, REQ-INC-141 AC2); widened from its live definition, as 0141 does.

Expand/contract (§14.3): new columns with defaults and a new table, read only by the new code.
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import (
    disable_tenant_rls,
    enable_actor_audit,
    enable_tenant_rls,
    grant_app,
)

revision: str = "0177"
down_revision: str | None = "0175"  # main's head at its queue turn (0173 → 0176 → 0175 → 0177)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ITEMS = "work_items"
SETTINGS = "work_item_type_settings"
LINKS = "work_item_announcements"
BULK_CHECK, BULK = "ck_work_item_bulk_jobs_action_code", "work_item_bulk_jobs"

# Business tables force RLS: the check runs once per tenant (D-113), then the caller's empty
# tenant is put back.
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {ITEMS} WHERE major OR major_declared_at IS NOT NULL)
           OR EXISTS (
               SELECT 1 FROM {SETTINGS}
               WHERE major_group_id IS NOT NULL OR cardinality(major_user_ids) > 0
                  OR major_template_id IS NOT NULL
           )
           OR EXISTS (SELECT 1 FROM {LINKS})
           OR EXISTS (SELECT 1 FROM {BULK} WHERE action = 'attach_child')
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % uses major incidents or announcements', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed names, no input


def _bulk_codes() -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": BULK_CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _bulk_recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(BULK_CHECK), BULK, type_="check")
    listed = ", ".join(f"'{c}'" for c in codes)
    op.create_check_constraint(op.f(BULK_CHECK), BULK, f"action IN ({listed})")


def upgrade() -> None:
    """The major flag and its settings, and the announcement links."""
    op.add_column(ITEMS, sa.Column("major", sa.Boolean(), server_default="false", nullable=False))
    op.add_column(ITEMS, sa.Column("major_declared_at", sa.DateTime(timezone=True)))
    op.add_column(ITEMS, sa.Column("major_declared_by", sa.Uuid()))
    op.add_column(ITEMS, sa.Column("major_reason", sa.String(500)))
    # The major incidents list and the marker filter: few rows, so a partial index.
    op.create_index(
        "ix_work_items_tenant_major",
        ITEMS,
        ["tenant_id", "type"],
        postgresql_where=sa.text("major AND deleted_at IS NULL"),
    )
    op.add_column(SETTINGS, sa.Column("major_group_id", sa.Uuid()))
    op.add_column(
        SETTINGS,
        sa.Column(
            "major_user_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False
        ),
    )
    op.add_column(SETTINGS, sa.Column("major_template_id", sa.Uuid()))
    op.create_table(
        LINKS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("announcement_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{LINKS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_work_item_announcements_work_item",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{LINKS}")),
    )
    op.create_index(
        "uq_work_item_announcements_pair",
        LINKS,
        ["tenant_id", "work_item_id", "announcement_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_work_item_announcements_announcement", LINKS, ["tenant_id", "announcement_id"]
    )
    enable_tenant_rls(LINKS)
    enable_actor_audit(LINKS)
    grant_app(LINKS, ("SELECT", "INSERT", "UPDATE"))  # soft delete only (rule §6)
    now = _bulk_codes()
    if "attach_child" not in now:
        _bulk_recheck([*now, "attach_child"])


def downgrade() -> None:
    """Back to before (stops while any tenant uses them)."""
    op.execute(GUARD)
    _bulk_recheck([c for c in _bulk_codes() if c != "attach_child"])
    disable_tenant_rls(LINKS)
    op.drop_table(LINKS)
    op.drop_column(SETTINGS, "major_template_id")
    op.drop_column(SETTINGS, "major_user_ids")
    op.drop_column(SETTINGS, "major_group_id")
    op.drop_index("ix_work_items_tenant_major", table_name=ITEMS)
    op.drop_column(ITEMS, "major_reason")
    op.drop_column(ITEMS, "major_declared_by")
    op.drop_column(ITEMS, "major_declared_at")
    op.drop_column(ITEMS, "major")
