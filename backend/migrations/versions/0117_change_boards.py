"""Change advisory boards (WP-045b S2; REQ-CHG-040, -041), number 0117 from the coordinator.

Expand only, no data step (the two default boards are seeded per tenant on first use):
- `change_boards` (RLS): a named board with its labels and description, an optional chair (a
  person), its quorum rule (any, all, majority, majority with the chair), the changes it is
  mapped to (`mapping`: types, risk levels, sites, templates; JSONB, all optional), its place in
  the order, whether it is the default, and a version for If-Match; soft-deleted.
- `change_board_members` (RLS): a board's members, a person or a group (exactly one), each at
  most once, optionally marked optional.
- `work_item_type_settings` (S3): `segregation_strict` (implementing groups barred from
  approving too; off by default) and `cab_every_match` (every matching board reviews; off).
- `work_item_approvals` (S3): `board_id`, the board an approval row came from, and
  `board_reason` (`mapped`: its mapping chose it; `default`: nothing matched). The route reason
  also accepts `board_has_no_members`; that check is widened from its live definition, as 0103
  does, so lanes adding reasons in either order keep each other's.

The downgrade drops both tables while the tenant has only its two seeded boards, unchanged and
without members; anything someone set up stops it and keeps the data (rule 5h).

Revision ID: 0117
Revises: 0116
Created: 2026-11-10
"""

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0117"
down_revision: str | None = "0116"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BOARDS, MEMBERS = "change_boards", "change_board_members"
SETTINGS = ("segregation_strict", "cab_every_match")
APPROVALS, REASON_CHECK = "work_item_approvals", "ck_work_item_approvals_reason_code"
ADDED_REASONS = ("board_has_no_members",)
RULES = "('any', 'all', 'majority', 'majority_with_chair')"
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {MEMBERS}) OR EXISTS (
            SELECT 1 FROM work_item_type_settings WHERE segregation_strict OR cab_every_match
        ) OR EXISTS (
            SELECT 1 FROM work_item_approvals WHERE board_id IS NOT NULL
        ) OR EXISTS (
            SELECT 1 FROM {BOARDS}
            WHERE code IS NULL OR code NOT IN ('cab', 'emergency_cab') OR version > 1
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has change boards set up (rule 5h)', t;
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


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _reasons_now() -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": REASON_CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(REASON_CHECK), APPROVALS, type_="check")
    listed = ", ".join(f"'{c}'" for c in codes)
    op.create_check_constraint(
        op.f(REASON_CHECK), APPROVALS, f"route_reason IS NULL OR route_reason IN ({listed})"
    )


def upgrade() -> None:
    """The boards and their members."""
    op.create_table(
        BOARDS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(40), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("chair_id", sa.Uuid(), nullable=True),
        sa.Column("rule", sa.String(30), server_default="majority", nullable=False),
        sa.Column("mapping", postgresql.JSONB(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(f"rule IN {RULES}", name=op.f(f"ck_{BOARDS}_rule_code")),
        _tenant_fk(BOARDS),
        sa.ForeignKeyConstraint(
            ["tenant_id", "chair_id"],
            ["users.tenant_id", "users.id"],
            name=op.f(f"fk_{BOARDS}_chair"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{BOARDS}")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f(f"uq_{BOARDS}_tenant_id_id")),
    )
    op.create_index(
        "uq_change_boards_tenant_code",
        BOARDS,
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_table(
        MEMBERS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("optional", sa.Boolean(), server_default="false", nullable=False),
        *_stamps(),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (group_id IS NULL)", name=op.f(f"ck_{MEMBERS}_one_member")
        ),
        _tenant_fk(MEMBERS),
        sa.ForeignKeyConstraint(
            ["tenant_id", "board_id"],
            [f"{BOARDS}.tenant_id", f"{BOARDS}.id"],
            name=op.f(f"fk_{MEMBERS}_board"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f(f"fk_{MEMBERS}_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            name=op.f(f"fk_{MEMBERS}_group"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{MEMBERS}")),
    )
    for column in ("user_id", "group_id"):
        op.create_index(
            f"uq_change_board_members_{column}",
            MEMBERS,
            ["tenant_id", "board_id", column],
            unique=True,
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )
    for table in (BOARDS, MEMBERS):
        enable_tenant_rls(table)
        enable_actor_audit(table)
    grant_app(BOARDS, ("SELECT", "INSERT", "UPDATE"))
    grant_app(MEMBERS, ("SELECT", "INSERT", "UPDATE", "DELETE"))
    op.add_column(APPROVALS, sa.Column("board_id", sa.Uuid(), nullable=True))
    op.add_column(APPROVALS, sa.Column("board_reason", sa.String(10), nullable=True))
    op.create_foreign_key(
        op.f(f"fk_{APPROVALS}_board"),
        APPROVALS,
        BOARDS,
        ["tenant_id", "board_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f(f"ck_{APPROVALS}_board_reason_code"),
        APPROVALS,
        "board_reason IS NULL OR board_reason IN ('mapped', 'default')",
    )
    now = _reasons_now()
    _recheck([*now, *(c for c in ADDED_REASONS if c not in now)])
    for column in SETTINGS:
        op.add_column(
            "work_item_type_settings",
            sa.Column(column, sa.Boolean(), server_default="false", nullable=False),
        )


def downgrade() -> None:
    """Back to before boards (stops while a board or a board setting was set up or changed by someone)."""
    op.execute(GUARD)
    _recheck([c for c in _reasons_now() if c not in ADDED_REASONS])
    op.drop_constraint(op.f(f"ck_{APPROVALS}_board_reason_code"), APPROVALS, type_="check")
    op.drop_constraint(op.f(f"fk_{APPROVALS}_board"), APPROVALS, type_="foreignkey")
    op.drop_column(APPROVALS, "board_reason")
    op.drop_column(APPROVALS, "board_id")
    for column in SETTINGS:
        op.drop_column("work_item_type_settings", column)
    for column in ("user_id", "group_id"):
        op.drop_index(f"uq_change_board_members_{column}", table_name=MEMBERS)
    op.drop_table(MEMBERS)
    op.drop_index("uq_change_boards_tenant_code", table_name=BOARDS)
    op.drop_table(BOARDS)
