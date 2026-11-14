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

TODO(S1b follow-up, after the code-owned definer helper lands in migrations/helpers.py with its
own PR): `history_redact_field(record_type, record_id, field)` - a migrator-owned SECURITY
DEFINER function that blanks old/new values of one field in `field_changes`, so a redacted
passage does not survive in the record's earlier history. Not added here: the repo's guard
refuses definer functions outside that helper.

TODO(S1b follow-up, same helper): `audit_erase_profile_history(person_id)` - the definer
function that blanks the erased person's own profile history (`field_changes` of record type
`user`) and the audit entries' copies of it (ADR-052 "Open").

Revision ID: 0164
Revises: 0161
Created: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0164"
down_revision: str | None = "0161"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "person_erasure_mentions"
ERASURES = "person_erasures"
REVIEW_COLUMNS = ("report_reviewed_at", "report_reviewed_by")


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
    op.drop_table(TABLE)  # its indexes and policies go with it
    for column in reversed(REVIEW_COLUMNS):
        op.drop_column(ERASURES, column)
    op.drop_constraint("uq_person_erasures_tenant_id_id", ERASURES, type_="unique")
