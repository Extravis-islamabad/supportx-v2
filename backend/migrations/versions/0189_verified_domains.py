"""Verified e-mail domains (WP-057 S5d, REQ-SEC-010; lane B's conditions).

- verified_domains: per tenant, RLS. A domain (normalised: IDNA, lowercase, no trailing dot), its
  state (pending | verified | lapsed), the proof token's SHA-256 only (the token is shown once),
  when it was last checked and how its failures stand.
- **One tenant per verified domain** (AC2): a partial unique index on `domain` over verified,
  undeleted rows. Any tenant may hold a pending row; verifying is what conflicts.
- A tenant adds a domain once: a unique index on (tenant_id, domain) over undeleted rows.

Revision ID: 0189
Revises: 0183
Created: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0189"
down_revision: str | None = "0183"  # main's head now; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "verified_domains"
STATES = "('pending', 'verified', 'lapsed')"
METHODS = "('dns', 'manual')"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_method", sa.String(length=16), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outcome", sa.String(length=40), nullable=True),
        sa.Column("failing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"state IN {STATES}", name=op.f(f"ck_{TABLE}_state_code")),
        sa.CheckConstraint(
            f"verified_by_method IS NULL OR verified_by_method IN {METHODS}",
            name=op.f(f"ck_{TABLE}_method_code"),
        ),
        sa.CheckConstraint(
            "domain = lower(domain) AND domain !~ '\\.$' AND domain ~ '\\.'",
            name=op.f(f"ck_{TABLE}_domain_form"),
        ),
        sa.CheckConstraint("failure_count >= 0", name=op.f(f"ck_{TABLE}_failures")),
        sa.CheckConstraint(
            "(state = 'verified') = (verified_at IS NOT NULL AND verified_by_method IS NOT NULL)"
            " OR state = 'lapsed'",
            name=op.f(f"ck_{TABLE}_verified_facts"),
        ),
    )
    op.create_index(
        op.f("ix_verified_domains_tenant_domain"),
        TABLE,
        ["tenant_id", "domain"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # AC2: one tenant per verified domain. Not tenant-led on purpose: it must see every tenant's
    # verified rows, and it reveals nothing (a conflicting verify gets 409, no tenant named).
    op.create_index(
        "uq_verified_domains_verified_domain",
        TABLE,
        ["domain"],
        unique=True,
        postgresql_where=sa.text("state = 'verified' AND deleted_at IS NULL"),
    )
    op.create_index(
        op.f("ix_verified_domains_tenant_state"), TABLE, ["tenant_id", "state", "last_checked_at"]
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))  # soft delete only


def downgrade() -> None:
    op.drop_table(TABLE)
