"""Signed history redaction (ADR-046 addendum; D-171, ADR-052 S1b follow-up), 0167.

A redacted passage (D-171 a) must not survive in record history, but some history rows are
committed to by a fingerprinted audit entry (ADR-046): blanking their values alone would read as
tampering. So the field's pre-blank digests (exactly the `[field, digest(old), digest(new)]` the
fingerprint already commits to, salted for personal fields) are kept, and the verifier reports
such a save as `redacted_on_request`, never `verified`.

Expand only, no data step:
- `field_change_redactions` (tenant, RLS forced): one row per blanked signed history row, its
  digests and the redacted mention. The app role may only read it; rows are written by the
  migrator-owned `history_redact_signed()` alone.
- `history_redact_signed(mention, rows, old, new, salted)`: the same binding as 0164's
  `history_redact_field` (a redacted mention with redactor and time, of an erasure that may still
  redact), and every row must be that mention's record and field in the caller's tenant and be
  committed by a fingerprinted entry; it stores the digests, then blanks the values.
- `audit_verification_runs.fingerprints_redacted`: saves verified through stored digests.
- `uq_person_erasure_mentions_tenant_id_id` for the composite key to the mention.

The downgrade refuses while any tenant has a redaction row (rule 5h), per tenant with
app.tenant_id set.

Revision ID: 0167
Revises: 0164
Created: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import (
    create_definer_function,
    drop_definer_function,
    enable_tenant_rls,
    grant_app,
)

revision: str = "0167"
down_revision: str | None = "0164"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "field_change_redactions"
MENTIONS = "person_erasure_mentions"
ERASURES = "person_erasures"
RUNS = "audit_verification_runs"

# The tenant, from the transaction's setting: no parameter can name another one.
_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
# The erasure states in which a mention may be redacted (domain/erasure.py, "redact"); fixed
# here, as a merged migration never changes with the code.
_REDACTABLE = "'requested', 'approved'"
_REDACT = f"""
DECLARE
    t uuid := {_TENANT};
    m record;
    n integer := coalesce(cardinality(p_rows), 0);
    recorded integer := 0;
    blanked integer := 0;
    ok integer;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'history_redact_signed needs app.tenant_id';
    END IF;
    IF coalesce(cardinality(p_old), 0) <> n OR coalesce(cardinality(p_new), 0) <> n
       OR coalesce(cardinality(p_salted), 0) <> n THEN
        RAISE EXCEPTION 'one digest pair and salted flag per row';
    END IF;
    SELECT x.id, x.record_type, x.record_id, x.field INTO m
      FROM {MENTIONS} x
      JOIN {ERASURES} e ON e.tenant_id = x.tenant_id AND e.id = x.erasure_id
     WHERE x.tenant_id = t AND x.id = p_mention AND x.state = 'redacted'
       AND x.redacted_at IS NOT NULL AND x.redacted_by IS NOT NULL
       AND e.state IN ({_REDACTABLE});
    IF NOT FOUND OR n = 0 THEN
        RETURN jsonb_build_object('blanked', 0, 'recorded', 0);
    END IF;
    -- Every row: that mention's record and field, here, and committed by a fingerprinted entry.
    SELECT count(*) INTO ok
      FROM field_changes f
     WHERE f.tenant_id = t AND f.id = ANY(p_rows)
       AND f.record_type = m.record_type AND f.record_id = m.record_id AND f.field = m.field
       AND EXISTS (
           SELECT 1 FROM audit_entries a
            WHERE a.tenant_id = t AND a.object_id = f.record_id::text
              AND a.fingerprint_saves @> ARRAY[f.change_id]);
    IF ok <> (SELECT count(DISTINCT r) FROM unnest(p_rows) AS r) THEN
        RAISE EXCEPTION 'a row is not a signed history row of this mention';
    END IF;
    INSERT INTO {TABLE} (tenant_id, id, field_change_id, change_id, record_type, record_id,
                         field, mention_id, old_digest, new_digest, salted, redacted_at)
    SELECT t, gen_random_uuid(), f.id, f.change_id, f.record_type, f.record_id, f.field, m.id,
           u.o, u.nw, u.s, now()
      FROM unnest(p_rows, p_old, p_new, p_salted) AS u(r, o, nw, s)
      JOIN field_changes f ON f.tenant_id = t AND f.id = u.r
    ON CONFLICT ON CONSTRAINT uq_field_change_redactions_row DO NOTHING;
    GET DIAGNOSTICS recorded = ROW_COUNT;
    -- Only rows whose digests are kept are blanked (a repeat finds them blank already).
    UPDATE field_changes f SET old_value = NULL, new_value = NULL
     WHERE f.tenant_id = t AND f.id = ANY(p_rows)
       AND (f.old_value IS NOT NULL OR f.new_value IS NOT NULL)
       AND EXISTS (SELECT 1 FROM {TABLE} d WHERE d.tenant_id = t AND d.field_change_id = f.id);
    GET DIAGNOSTICS blanked = ROW_COUNT;
    RETURN jsonb_build_object('blanked', blanked, 'recorded', recorded);
END
"""  # noqa: S608 - fixed names, no input


def upgrade() -> None:
    """Adds the redaction table, its writer function and the runs' count."""
    op.create_unique_constraint(
        "uq_person_erasure_mentions_tenant_id_id", MENTIONS, ["tenant_id", "id"]
    )
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("field_change_id", sa.Uuid(), nullable=False),
        sa.Column("change_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=80), nullable=False),
        sa.Column("mention_id", sa.Uuid(), nullable=False),
        sa.Column("old_digest", sa.Text(), nullable=False),
        sa.Column("new_digest", sa.Text(), nullable=False),
        sa.Column("salted", sa.Boolean(), nullable=False),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "mention_id"],
            [f"{MENTIONS}.tenant_id", f"{MENTIONS}.id"],
            name="fk_field_change_redactions_mention",
        ),
        # A digest is the fingerprint's own form, 64 lowercase hex characters, and nothing else
        # (no value can hide in it).
        sa.CheckConstraint(
            "old_digest ~ '^[0-9a-f]{64}$' AND new_digest ~ '^[0-9a-f]{64}$'",
            name=op.f(f"ck_{TABLE}_digest_form"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f(f"pk_{TABLE}")),
        sa.UniqueConstraint("tenant_id", "field_change_id", name="uq_field_change_redactions_row"),
    )
    op.create_index(
        "ix_field_change_redactions_change", TABLE, ["tenant_id", "change_id", "field_change_id"]
    )
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT",))  # written only by history_redact_signed()
    op.add_column(
        RUNS,
        sa.Column("fingerprints_redacted", sa.Integer(), server_default="0", nullable=False),
    )
    create_definer_function(
        "history_redact_signed",
        "p_mention uuid, p_rows uuid[], p_old text[], p_new text[], p_salted boolean[]",
        "jsonb",
        _REDACT,
        language="plpgsql",
        volatility="VOLATILE",
    )


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has signed history redactions', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table name, no input


def downgrade() -> None:
    """Drops what upgrade added only while no tenant has a redaction row (rule 5h)."""
    op.execute(_REFUSE_IF_ANY)
    drop_definer_function("history_redact_signed(uuid, uuid[], text[], text[], boolean[])")
    op.drop_column(RUNS, "fingerprints_redacted")
    op.drop_table(TABLE)  # its indexes and policies go with it
    op.drop_constraint("uq_person_erasure_mentions_tenant_id_id", MENTIONS, type_="unique")
