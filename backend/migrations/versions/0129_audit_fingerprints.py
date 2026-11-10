"""Change-set fingerprints, per-subject salts and history erasure (WP-064 S2, D-150, ADR-046).

Expand only; no data step (older entries get no fingerprint and hash exactly as before).

- `audit_entries`: `fingerprint` (`fp1:<hex>` over the ordinary fields, no salt),
  `personal_fingerprint` (over the personal fields, salted; NULL when there are none),
  `fingerprint_saves` (the change IDs they cover) and `personal_subjects` (whose salts the
  personal half uses), all NULL on older entries. A plain GIN index
  on `personal_subjects` finds a person's entries for erasure (no btree_gin, as in 0122).
- `audit_verification_runs`: counts of fingerprint verdicts per run.
- `audit_subject_salts`: one random 16-byte salt per data subject and tenant. RLS forced, and
  NO right for the app role at all: the migrator-owned SECURITY DEFINER functions below are the
  only way in (search_path pinned, FORCE RLS keeps them inside `app.tenant_id`):
  - `audit_subject_salts_ensure(subjects, new_salts)`: get or create (the app supplies fresh
    random salts; an existing salt is never replaced; an erased subject gets none back);
  - `audit_subject_salts_of(subjects)`: read existing salts, for the verifier;
  - `audit_erase_subject(subject, history_rows)` replaces the one-argument version of 0014: it
    deletes the person's personal rows as before, blanks the given field_changes values (only
    rows of saves whose entries list the person), then destroys the salt (the row stays as a
    tombstone with `erased_at`, so the person never gets a fresh salt older entries would not
    match). Returns counts as JSON.

The downgrade refuses while any tenant has a fingerprinted entry or a salt (rule 5h: dropping
them would make those entries fail verification). Then it restores 0014's function.

Revision ID: 0129
Revises: 0126
Created: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.shared.db.rls import APP_ROLE
from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0129"
down_revision: str | None = "0126"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_audit_entries_personal_subjects"
SALTS = "audit_subject_salts"
FUNCTIONS = (
    "audit_subject_salts_ensure(uuid[], bytea[])",
    "audit_subject_salts_of(uuid[])",
    "audit_erase_subject(uuid, uuid[])",
)

ENSURE = """
CREATE FUNCTION audit_subject_salts_ensure(p_subjects uuid[], p_salts bytea[])
RETURNS TABLE(subject_ref uuid, salt_bytes bytea)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    t uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'audit_subject_salts_ensure needs app.tenant_id';
    END IF;
    IF cardinality(p_subjects) IS DISTINCT FROM cardinality(p_salts) THEN
        RAISE EXCEPTION 'one new salt per subject';
    END IF;
    INSERT INTO audit_subject_salts (tenant_id, subject_id, salt, created_at)
    SELECT t, u.s, u.v, now() FROM unnest(p_subjects, p_salts) AS u(s, v)
    ON CONFLICT ON CONSTRAINT pk_audit_subject_salts DO NOTHING;
    RETURN QUERY
        SELECT a.subject_id, a.salt FROM audit_subject_salts a
         WHERE a.tenant_id = t AND a.subject_id = ANY(p_subjects) AND a.salt IS NOT NULL;
END
$$
"""

SALTS_OF = """
CREATE FUNCTION audit_subject_salts_of(p_subjects uuid[])
RETURNS TABLE(subject_ref uuid, salt_bytes bytea)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT a.subject_id, a.salt FROM audit_subject_salts a
     WHERE a.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
       AND a.subject_id = ANY(p_subjects) AND a.salt IS NOT NULL
$$
"""

ERASE = """
CREATE FUNCTION audit_erase_subject(p_subject uuid, p_history uuid[]) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    t uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
    personal_rows integer;
    history_values integer;
    salts integer;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'audit_erase_subject needs app.tenant_id';
    END IF;
    DELETE FROM audit_personal WHERE tenant_id = t AND subject_id = p_subject;
    GET DIAGNOSTICS personal_rows = ROW_COUNT;
    -- Only values of saves whose entries list the person (their fingerprints use the salt).
    UPDATE field_changes f SET old_value = NULL, new_value = NULL
     WHERE f.tenant_id = t AND f.id = ANY(p_history)
       AND (f.old_value IS NOT NULL OR f.new_value IS NOT NULL)
       AND EXISTS (
           SELECT 1 FROM audit_entries e
            WHERE e.tenant_id = t
              AND e.personal_subjects @> ARRAY[p_subject]
              AND e.fingerprint_saves @> ARRAY[f.change_id]
              AND e.object_id = f.record_id::text);
    GET DIAGNOSTICS history_values = ROW_COUNT;
    -- Crypto-shredding: the salt goes after the values it protects; the row stays a tombstone.
    UPDATE audit_subject_salts SET salt = NULL, erased_at = now()
     WHERE tenant_id = t AND subject_id = p_subject AND salt IS NOT NULL;
    GET DIAGNOSTICS salts = ROW_COUNT;
    RETURN jsonb_build_object(
        'personal_rows', personal_rows, 'history_values', history_values, 'salts', salts);
END
$$
"""

# 0014's version, restored by the downgrade.
ERASE_0014 = """
CREATE FUNCTION audit_erase_subject(p_subject uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    t uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
    removed integer;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'audit_erase_subject needs app.tenant_id';
    END IF;
    DELETE FROM audit_personal WHERE tenant_id = t AND subject_id = p_subject;
    GET DIAGNOSTICS removed = ROW_COUNT;
    RETURN removed;
END
$$
"""


def _grant(function: str) -> None:
    op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")


def upgrade() -> None:
    """Adds the columns, the salts table (no app rights) and the definer functions."""
    op.add_column("audit_entries", sa.Column("fingerprint", sa.String(length=80), nullable=True))
    op.add_column(
        "audit_entries", sa.Column("personal_fingerprint", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "audit_entries", sa.Column("fingerprint_saves", postgresql.ARRAY(sa.Uuid()), nullable=True)
    )
    op.add_column(
        "audit_entries", sa.Column("personal_subjects", postgresql.ARRAY(sa.Uuid()), nullable=True)
    )
    op.create_index(INDEX, "audit_entries", ["personal_subjects"], postgresql_using="gin")
    for column in ("fingerprints_verified", "fingerprints_erased", "fingerprint_mismatches"):
        op.add_column(
            "audit_verification_runs",
            sa.Column(column, sa.Integer(), server_default="0", nullable=False),
        )

    op.create_table(
        SALTS,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("salt", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "salt IS NULL OR octet_length(salt) = 16",
            name=op.f("ck_audit_subject_salts_salt_length"),
        ),
        sa.CheckConstraint(
            "(salt IS NULL) = (erased_at IS NOT NULL)",
            name=op.f("ck_audit_subject_salts_salt_or_erased"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_audit_subject_salts_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "subject_id", name=op.f("pk_audit_subject_salts")),
    )
    enable_tenant_rls(SALTS)
    grant_app(SALTS, ())  # nothing: salts are reached only through the functions below

    op.execute("DROP FUNCTION audit_erase_subject(uuid)")
    for statement in (ENSURE, SALTS_OF, ERASE):
        op.execute(statement)
    for function in FUNCTIONS:
        _grant(function)


_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM audit_entries WHERE fingerprint IS NOT NULL)
           OR EXISTS (SELECT 1 FROM audit_subject_salts) THEN
            RAISE EXCEPTION
                'downgrade refused: tenant % has fingerprinted audit entries (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops it all only while no tenant has a fingerprinted entry or a salt; else refuses."""
    op.execute(_REFUSE_IF_ANY)
    for function in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute(ERASE_0014)
    _grant("audit_erase_subject(uuid)")
    op.drop_table(SALTS)
    for column in ("fingerprint_mismatches", "fingerprints_erased", "fingerprints_verified"):
        op.drop_column("audit_verification_runs", column)
    op.drop_index(INDEX, table_name="audit_entries")
    for column in ("personal_subjects", "fingerprint_saves", "personal_fingerprint", "fingerprint"):
        op.drop_column("audit_entries", column)
