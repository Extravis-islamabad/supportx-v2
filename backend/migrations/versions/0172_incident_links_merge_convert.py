"""Incident parents, merges and conversions (WP-046b S2; REQ-INC-086, -088, -089, -150), 0172.

Expand only, no data step:
- `work_item_links.kind` also accepts `child_of` (a child incident -> its parent) and
  `converted_to` (a converted record -> the record it became);
- `work_item_transitions.action` also accepts `convert` (merge and undo_merge exist, 0104);
- `work_item_aliases`: an old display ID (a converted record's) -> the record it now resolves
  to, so an old link or e-mail still finds it. Tenant first, RLS forced; a reader is sent on
  only if they may read the new record (the service's rule, never the table's).

Checks are widened from their live definitions and only these codes are removed on the way
down (as 0104, 0115 and 0138 do), so lanes adding codes in either order keep each other's. The
downgrade stops while a row uses them (rule 5h).

Revision ID: 0172
Revises: 0171
Created: 2026-11-16
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import (
    disable_tenant_rls,
    enable_actor_audit,
    enable_tenant_rls,
    grant_app,
)

revision: str = "0172"
down_revision: str | None = "0171"  # main's head (0169 → 0171 → 0172)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALIASES = "work_item_aliases"
WIDENED = {
    ("ck_work_item_links_kind_code", "work_item_links", "kind"): ("child_of", "converted_to"),
    ("ck_work_item_transitions_action_code", "work_item_transitions", "action"): ("convert",),
}

# Business tables force RLS: the check runs once per tenant (D-113), then the caller's empty
# tenant is put back.
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM work_item_links WHERE kind IN ('child_of', 'converted_to'))
           OR EXISTS (SELECT 1 FROM work_item_transitions WHERE action = 'convert')
           OR EXISTS (SELECT 1 FROM {ALIASES})
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has parents, conversions or aliases', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed names, no input


def _codes_now(name: str) -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(name: str, table: str, column: str, codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    listed = ", ".join(f"'{c}'" for c in codes)
    op.create_check_constraint(op.f(name), table, f"{column} IN ({listed})")


def upgrade() -> None:
    """The new codes, and the alias table."""
    for (name, table, column), added in WIDENED.items():
        now = _codes_now(name)
        _recheck(name, table, column, [*now, *(c for c in added if c not in now)])
    # WP-046b S2: an incident has at most one parent (REQ-INC-086).
    op.create_index(
        "uq_wil_tenant_one_parent",
        "work_item_links",
        ["tenant_id", "source_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'child_of' AND deleted_at IS NULL"),
    )
    op.create_table(
        ALIASES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("display_id", sa.String(40), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
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
            name=op.f(f"fk_{ALIASES}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_work_item_aliases_work_item",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ALIASES}")),
    )
    # One record per old display ID in a tenant; a record's own aliases for its page.
    op.create_index(
        "uq_work_item_aliases_display",
        ALIASES,
        ["tenant_id", "display_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_work_item_aliases_record", ALIASES, ["tenant_id", "work_item_id"])
    enable_tenant_rls(ALIASES)
    enable_actor_audit(ALIASES)
    grant_app(ALIASES, ("SELECT", "INSERT", "UPDATE"))  # soft delete only (rule §6)


def downgrade() -> None:
    """Back to before (stops while any tenant uses them)."""
    op.execute(GUARD)
    disable_tenant_rls(ALIASES)
    op.drop_table(ALIASES)
    op.drop_index("uq_wil_tenant_one_parent", table_name="work_item_links")
    for (name, table, column), added in WIDENED.items():
        _recheck(name, table, column, [c for c in _codes_now(name) if c not in added])
