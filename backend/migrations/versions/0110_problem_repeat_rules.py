"""Repeat incident rules without AI (WP-044c S3, D16; REQ-PRB-068).

- problem_repeat_rules: an admin's rule, "N or more incidents in the same category (and site)
  within H hours"; the default ("10 in the same category and site in 24 h") is made per tenant
  on demand, like system roles, so no data step.
- problem_repeat_hits: one set of matching incidents a rule found, open until a problem is
  created from it or it is dismissed. At most one open hit per rule and key (a unique partial
  index): two evaluations that overlap never open two (the coordinator's condition).
- problem_repeat_hit_incidents: the set's members, capped by the service (at most 100 per hit)
  so a busy category never grows one row without limit; the hit keeps the full count.

All three tenant-scoped with RLS (tenant_id leads every composite index), expand only. The
downgrade refuses, per tenant with app.tenant_id set, while any rule or hit exists (rule 5h).

Revision ID: 0110
Revises: 0109
Created: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0110"
down_revision: str | None = "0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULES, HITS, MEMBERS = "problem_repeat_rules", "problem_repeat_hits", "problem_repeat_hit_incidents"


def _entity_columns() -> list[sa.Column]:  # type: ignore[type-arg]  # sa.Column is generic in stubs only
    return [
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
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    """The three tables, their RLS and the app role's grants."""
    op.create_table(
        RULES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("match", sa.String(length=20), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("notify_group_id", sa.UUID(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        *_entity_columns(),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f(f"ck_{RULES}_name_length")
        ),
        sa.CheckConstraint(
            "match IN ('category', 'category_site')", name=op.f(f"ck_{RULES}_match_code")
        ),
        sa.CheckConstraint(
            "threshold BETWEEN 2 AND 1000", name=op.f(f"ck_{RULES}_threshold_range")
        ),
        sa.CheckConstraint(
            "window_hours BETWEEN 1 AND 2160", name=op.f(f"ck_{RULES}_window_range")
        ),
        _tenant_fk(RULES),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{RULES}")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_problem_repeat_rules_tenant_id_id"),
    )
    op.create_index(
        "uq_problem_repeat_rules_tenant_name",
        RULES,
        ["tenant_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_problem_repeat_rules_tenant_default",
        RULES,
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
    )
    op.create_table(
        HITS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.UUID(), nullable=False),
        sa.Column("match_key", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("site_id", sa.UUID(), nullable=True),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column("incident_count", sa.Integer(), nullable=False),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handled_by", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("problem_id", sa.UUID(), nullable=True),
        *_entity_columns(),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('problem_created', 'dismissed')",
            name=op.f(f"ck_{HITS}_outcome_code"),
        ),
        sa.CheckConstraint(
            "(handled_at IS NULL) = (outcome IS NULL)", name=op.f(f"ck_{HITS}_handled_with_outcome")
        ),
        sa.CheckConstraint("incident_count >= 1", name=op.f(f"ck_{HITS}_incident_count_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "rule_id"],
            [f"{RULES}.tenant_id", f"{RULES}.id"],
            name="fk_problem_repeat_hits_rule",
        ),
        _tenant_fk(HITS),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{HITS}")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_problem_repeat_hits_tenant_id_id"),
    )
    op.create_index(
        "uq_problem_repeat_hits_open",
        HITS,
        ["tenant_id", "rule_id", "match_key"],
        unique=True,
        postgresql_where=sa.text("handled_at IS NULL AND deleted_at IS NULL"),
    )
    op.create_index("ix_problem_repeat_hits_tenant_handled", HITS, ["tenant_id", "handled_at"])
    op.create_table(
        MEMBERS,
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("hit_id", sa.UUID(), nullable=False),
        sa.Column("work_item_id", sa.UUID(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "hit_id"],
            [f"{HITS}.tenant_id", f"{HITS}.id"],
            name="fk_prhi_hit",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_prhi_incident",
        ),
        _tenant_fk(MEMBERS),
        sa.PrimaryKeyConstraint("tenant_id", "hit_id", "work_item_id", name=op.f(f"pk_{MEMBERS}")),
    )
    for table in (RULES, HITS):
        enable_tenant_rls(table)
        enable_actor_audit(table)
        grant_app(table, ("SELECT", "INSERT", "UPDATE"))
    enable_tenant_rls(MEMBERS)
    grant_app(MEMBERS, ("SELECT", "INSERT", "DELETE"))


# Rule 5h: never drop tenants' rules or what they found. Checked per tenant with app.tenant_id
# set, as the tables force RLS (a bare SELECT would see nothing and pass).
_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM problem_repeat_rules)
           OR EXISTS (SELECT 1 FROM problem_repeat_hits) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has repeat incident rules or hits'
                ' (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops the tables only while no tenant has a rule or a hit; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table(MEMBERS)
    op.drop_table(HITS)
    op.drop_table(RULES)
