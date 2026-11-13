"""Person erasure requests and legal hold (identity_access; D-171, ADR-052 S1).

Expand only, no data step:
- `person_erasures`: one GDPR erasure of a person, requested by one admin and approved by
  another, then run step by step by the erasure job (ADR-052 §3). `step` is the next step to run,
  so a run resumes where it stopped; within step 4, `port_module` and `port_cursor` name the
  module and batch to go on with. `last_error_code` holds a code, never a message. One open
  erasure per person (partial unique index). No DELETE grant: the rows are the tenant's record
  that an erasure happened.
- `users`: `legal_hold_at / legal_hold_by / legal_hold_reason` (H1; a held person is never
  erased) and `erased_at / erased_by` (the row stays, anonymised, so IDs everywhere resolve).
- DELETE on `user_cost_rates` and `list_settings` for the application role: removal there is a
  soft delete everywhere else, but the erasure deletes a person's rates (D3a) and private views
  for good (the GDPR erasure is the one place a hard delete is allowed, CLAUDE.md §6).

Tenant table, RLS forced, through migrations/helpers.py only. The downgrade refuses while any
tenant has an erasure, a held person or an erased person, per tenant with app.tenant_id set
(rule 5h).

Revision ID: 0161
Revises: 0158
Created: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0161"
down_revision: str | None = "0158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "person_erasures"
STATES = ("requested", "approved", "running", "done", "rejected", "expired", "failed")
OPEN_STATES = ("requested", "approved", "running", "failed")
REASONS = ("subject_request", "no_longer_needed", "consent_withdrawn", "legal_obligation")
LAST_STEP = 8  # steps 0..7 run; 8 = all done
USER_COLUMNS = ("legal_hold_at", "legal_hold_by", "legal_hold_reason", "erased_at", "erased_by")
HARD_DELETED = ("user_cost_rates", "list_settings")


def _codes(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Adds the erasure table, the hold and erasure columns and the DELETE grants."""
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=12), server_default="requested", nullable=False),
        sa.Column("step", sa.SmallInteger(), server_default="0", nullable=False),
        # Step 4's progress inside the ports (ADR-052 §4, batches): the module being erased and
        # its cursor, so a resumed run repeats at most one batch.
        sa.Column("port_module", sa.String(length=60), nullable=True),
        sa.Column("port_cursor", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column("successor_id", sa.Uuid(), nullable=False),
        sa.Column("effective_successor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "keep_files",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.Uuid(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=60), nullable=True),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"state IN ({_codes(STATES)})", name=op.f(f"ck_{TABLE}_state_code")),
        sa.CheckConstraint(
            f"reason_code IN ({_codes(REASONS)})", name=op.f(f"ck_{TABLE}_reason_code")
        ),
        sa.CheckConstraint(f"step BETWEEN 0 AND {LAST_STEP}", name=op.f(f"ck_{TABLE}_step_range")),
        sa.CheckConstraint("attempts >= 0", name=op.f(f"ck_{TABLE}_attempts_not_negative")),
        sa.CheckConstraint(
            "char_length(port_cursor) <= 2000", name=op.f(f"ck_{TABLE}_port_cursor_length")
        ),
        sa.CheckConstraint(
            "char_length(reason_text) <= 1000", name=op.f(f"ck_{TABLE}_reason_text_length")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(keep_files) = 'object'", name=op.f(f"ck_{TABLE}_keep_files_object")
        ),
        # Two people (D-171): the approver is never the requester, whatever the code does.
        sa.CheckConstraint(
            "approved_by IS NULL OR approved_by <> requested_by",
            name=op.f(f"ck_{TABLE}_four_eyes"),
        ),
        sa.CheckConstraint("successor_id <> person_id", name=op.f(f"ck_{TABLE}_successor_other")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["users.tenant_id", "users.id"],
            name="fk_person_erasures_person",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "successor_id"],
            ["users.tenant_id", "users.id"],
            name="fk_person_erasures_successor",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["users.tenant_id", "users.id"],
            name="fk_person_erasures_requested_by",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approved_by"],
            ["users.tenant_id", "users.id"],
            name="fk_person_erasures_approved_by",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "rejected_by"],
            ["users.tenant_id", "users.id"],
            name="fk_person_erasures_rejected_by",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_person_erasures_open",
        TABLE,
        ["tenant_id", "person_id"],
        unique=True,
        postgresql_where=sa.text(f"state IN ({_codes(OPEN_STATES)})"),
    )
    op.create_index("ix_person_erasures_tenant_created", TABLE, ["tenant_id", "created_at", "id"])
    op.create_index("ix_person_erasures_tenant_state", TABLE, ["tenant_id", "state"])
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))  # the record of an erasure stays
    enable_actor_audit(TABLE)

    op.add_column("users", sa.Column("legal_hold_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("legal_hold_by", sa.Uuid(), nullable=True))
    op.add_column("users", sa.Column("legal_hold_reason", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("erased_by", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_legal_hold_reason_length"),
        "users",
        "char_length(legal_hold_reason) <= 1000",
    )
    op.create_check_constraint(
        op.f("ck_users_legal_hold_complete"),
        "users",
        "(legal_hold_at IS NULL) = (legal_hold_reason IS NULL)",
    )

    for table in HARD_DELETED:
        grant_app(table)  # SELECT, INSERT, UPDATE, DELETE


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has person erasures (rule 5h)', t;
        END IF;
        IF EXISTS (SELECT 1 FROM users
                    WHERE legal_hold_at IS NOT NULL OR erased_at IS NOT NULL) THEN
            RAISE EXCEPTION
                'downgrade refused: tenant % has a person on legal hold or erased (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops it all only while no tenant has an erasure, a hold or an erased person."""
    op.execute(_REFUSE_IF_ANY)
    for table in HARD_DELETED:
        grant_app(table, ("SELECT", "INSERT", "UPDATE"))  # back to soft delete only
    op.drop_constraint(op.f("ck_users_legal_hold_complete"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_legal_hold_reason_length"), "users", type_="check")
    for column in reversed(USER_COLUMNS):
        op.drop_column("users", column)
    op.drop_table(TABLE)  # its indexes and policies go with it
