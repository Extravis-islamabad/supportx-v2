"""The mentions report of a person erasure (identity_access; D-171 a, ADR-052 S1b).

Expand only, no data step:
- `person_erasure_mentions`: one place an erasure's person is named in other people's text
  (module, record, field, kind, how often; never the text or the terms), found by the report
  build and then redacted or left. One row per place and kind (unique), so a repeated batch
  adds nothing. No DELETE grant: what the approver saw stays with the erasure.
- `person_erasures.report_reviewed_at / report_reviewed_by`: an admin reviewed the finished
  report; approval needs it. A unique (tenant_id, id) on `person_erasures` for the composite key.

Tenant table, RLS forced, through migrations/helpers.py only. The downgrade refuses while any
tenant has a mention or a reviewed report, per tenant with app.tenant_id set (rule 5h).

Two migrator-owned SECURITY DEFINER functions, through `create_definer_function` only (the app
role has no UPDATE on `field_changes`; record history stays append-only for it):
- `history_redact_field(p_mention)`: blanks old/new values of exactly the record and field named
  by one *redacted* mention row of this tenant, so the redacted passage does not survive in the
  record's earlier history. It takes no record or field name: what it may touch is what the
  approver's report recorded. Rows a fingerprinted audit entry commits to (ADR-046) are left:
  blanking them would read as tampering. Their redaction waits for a verifier status of its own.
- `audit_erase_profile_history(p_person)`: blanks values and reasons of the person's own profile
  history (record type `user`), only once `users.erased_at` is set (step 5 ran), so it can never
  wipe a live person's history. Called in step 6.

Revision ID: 0164
Revises: 0163
Created: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import (
    create_definer_function,
    drop_definer_function,
    enable_actor_audit,
    enable_tenant_rls,
    grant_app,
)

revision: str = "0164"
down_revision: str | None = "0163"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "person_erasure_mentions"
ERASURES = "person_erasures"
REVIEW_COLUMNS = ("report_reviewed_at", "report_reviewed_by")

# The tenant, from the transaction's setting: no parameter can name another one.
_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
# The erasure states in which a mention may be redacted (domain/erasure.py, "redact"); fixed
# here, as a merged migration never changes with the code.
_REDACTABLE = "'requested', 'approved'"
_REDACT = f"""
    WITH m AS (
        SELECT x.record_type, x.record_id, x.field FROM {TABLE} x
        JOIN {ERASURES} e ON e.tenant_id = x.tenant_id AND e.id = x.erasure_id
        WHERE x.tenant_id = {_TENANT} AND x.id = p_mention AND x.state = 'redacted'
          AND x.redacted_at IS NOT NULL AND x.redacted_by IS NOT NULL
          -- Only while redaction is allowed (rules.can("redact")): a row the app wrote for a
          -- closed or finished erasure blanks nothing (lane C's #506 review).
          AND e.state IN ({_REDACTABLE})
    ), rows AS (
        SELECT f.id, EXISTS (
                   SELECT 1 FROM audit_entries e
                   WHERE e.tenant_id = {_TENANT} AND e.object_id = f.record_id::text
                     AND e.fingerprint_saves @> ARRAY[f.change_id]
               ) AS fingerprinted
        FROM field_changes f JOIN m
          ON f.record_type = m.record_type AND f.record_id = m.record_id AND f.field = m.field
        WHERE f.tenant_id = {_TENANT}
          AND (f.old_value IS NOT NULL OR f.new_value IS NOT NULL)
    ), gone AS (
        UPDATE field_changes f SET old_value = NULL, new_value = NULL
        FROM rows r
        WHERE f.tenant_id = {_TENANT} AND f.id = r.id AND NOT r.fingerprinted
        RETURNING 1
    )
    SELECT jsonb_build_object(
        'blanked', (SELECT count(*) FROM gone),
        'kept_fingerprinted', (SELECT count(*) FROM rows WHERE fingerprinted))
"""  # noqa: S608 - fixed names, no input
_PROFILE = f"""
    WITH gone AS (
        UPDATE field_changes f SET old_value = NULL, new_value = NULL, reason = NULL
        WHERE f.tenant_id = {_TENANT}
          AND f.record_type = 'user' AND f.record_id = p_person
          AND (f.old_value IS NOT NULL OR f.new_value IS NOT NULL OR f.reason IS NOT NULL)
          AND EXISTS (
              SELECT 1 FROM users u
              WHERE u.tenant_id = {_TENANT} AND u.id = p_person AND u.erased_at IS NOT NULL
          )
        RETURNING 1
    )
    SELECT count(*)::integer FROM gone
"""  # noqa: S608 - fixed names, no input


def upgrade() -> None:
    """Adds the mentions table and the report review columns."""
    op.create_unique_constraint("uq_person_erasures_tenant_id_id", ERASURES, ["tenant_id", "id"])
    op.add_column(
        ERASURES, sa.Column("report_reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(ERASURES, sa.Column("report_reviewed_by", sa.Uuid(), nullable=True))
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("erasure_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=60), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=80), nullable=False),
        sa.Column("match_kind", sa.String(length=10), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=10), server_default="found", nullable=False),
        sa.Column("redacted_by", sa.Uuid(), nullable=True),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        # History rows of the field kept at redaction: a fingerprinted entry commits to them.
        sa.Column("history_kept", sa.Integer(), server_default="0", nullable=False),
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
        sa.CheckConstraint(
            "match_kind IN ('name', 'email', 'phone')", name=op.f(f"ck_{TABLE}_match_kind_code")
        ),
        sa.CheckConstraint(
            "state IN ('found', 'redacted', 'left')", name=op.f(f"ck_{TABLE}_state_code")
        ),
        sa.CheckConstraint("occurrences > 0", name=op.f(f"ck_{TABLE}_occurrences_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "erasure_id"],
            [f"{ERASURES}.tenant_id", f"{ERASURES}.id"],
            name="fk_person_erasure_mentions_erasure",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "redacted_by"],
            ["users.tenant_id", "users.id"],
            name="fk_person_erasure_mentions_redacted_by",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.UniqueConstraint(
            "tenant_id",
            "erasure_id",
            "module_key",
            "record_type",
            "record_id",
            "field",
            "match_kind",
            name="uq_person_erasure_mentions_place",
        ),
    )
    op.create_index("ix_person_erasure_mentions_state", TABLE, ["tenant_id", "erasure_id", "state"])
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))  # what the approver saw stays
    enable_actor_audit(TABLE)
    create_definer_function(
        "history_redact_field", "p_mention uuid", "jsonb", _REDACT, volatility="VOLATILE"
    )
    create_definer_function(
        "audit_erase_profile_history", "p_person uuid", "integer", _PROFILE, volatility="VOLATILE"
    )


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM person_erasure_mentions) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has erasure mentions (rule 5h)', t;
        END IF;
        IF EXISTS (SELECT 1 FROM person_erasures WHERE report_reviewed_at IS NOT NULL) THEN
            RAISE EXCEPTION
                'downgrade refused: tenant % has a reviewed erasure report (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops it all only while no tenant has a mention or a reviewed report."""
    op.execute(_REFUSE_IF_ANY)
    drop_definer_function("audit_erase_profile_history(uuid)")
    drop_definer_function("history_redact_field(uuid)")
    op.drop_table(TABLE)  # its indexes and policies go with it
    for column in reversed(REVIEW_COLUMNS):
        op.drop_column(ERASURES, column)
    op.drop_constraint("uq_person_erasures_tenant_id_id", ERASURES, type_="unique")
