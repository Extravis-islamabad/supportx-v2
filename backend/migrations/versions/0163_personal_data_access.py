"""Personal data access log (REQ-AUD-017) and the data-key wrap count (WP-057 S3b-1; ADR-050).

- `personal_data_access` (audit module, lane B blocks): who viewed or exported whose personal
  data, and the AI masking counts (REQ-AI-019). Never a value: field codes and counts only.
  Tenant table, RLS forced, **append-only** for the app role (SELECT and INSERT). Rows go only
  through two migrator-owned functions, with the tenant from `app.tenant_id`, never a parameter:
  - `audit_erase_access(subject)`: a person's erasure (ADR-052 step 6, after
    `audit_erase_subject`, in the same transaction);
  - `audit_purge_access(before)`: the daily retention purge.
  A view is written once per accessor, record and 15 minutes (`dedupe_key`, unique per tenant):
  live refetches never flood it.
- `audit_settings.personal_data_log`: the tenant's switch (off by default).
- `sx_kek_wraps()`: how many data keys each key-encryption key wraps, over every tenant, and
  nothing else (no tenant, no key). The API refuses to start while a KEK no longer in the ring
  still wraps any (lane B's #490 conditions), through a migrator read policy on
  `tenant_data_keys` that only this function can use (the migrator has no login).

Every function is made by `create_definer_function` (migrations/helpers.py, D-168): fixed
search_path, closed to PUBLIC, EXECUTE for supportx_app only. The downgrade refuses while any
tenant has an access entry (rule 5h).

Revision ID: 0163
Revises: 0158
Created: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import (
    allow_migrator_read,
    create_definer_function,
    drop_definer_function,
    drop_policy,
    enable_tenant_rls,
    grant_app,
)

revision: str = "0163"
down_revision: str | None = "0158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "personal_data_access"
KINDS = ("view", "export", "ai_masking")
KEYS_POLICY = "tenant_data_keys_kek_count"

# The tenant, from the transaction's setting: no parameter can name another one.
_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_ERASE = f"""
    WITH gone AS (
        DELETE FROM {TABLE} WHERE tenant_id = {_TENANT} AND subject_person_id = p_subject
        RETURNING 1
    )
    SELECT count(*)::integer FROM gone
"""  # noqa: S608 - fixed names, no input
_PURGE = f"""
    WITH gone AS (
        DELETE FROM {TABLE} WHERE tenant_id = {_TENANT} AND occurred_at < p_before
        RETURNING 1
    )
    SELECT count(*)::integer FROM gone
"""  # noqa: S608 - fixed names, no input
_WRAPS = "SELECT kek_id::text, count(*)::bigint FROM tenant_data_keys GROUP BY kek_id"


def upgrade() -> None:
    """Adds the access log, its two writer functions and the wrap count."""
    op.add_column(
        "audit_settings",
        sa.Column("personal_data_log", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accessor_type", sa.String(20), nullable=False),
        sa.Column("accessor_id", sa.Uuid(), nullable=True),  # none for the system
        sa.Column("subject_person_id", sa.Uuid(), nullable=True),
        sa.Column("record_type", sa.String(40), nullable=True),
        sa.Column("record_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("purpose", sa.String(60), nullable=False),  # a code: person_profile, export…
        sa.Column("fields", postgresql.ARRAY(sa.String(80)), nullable=False),
        sa.Column("counts", postgresql.JSONB(), nullable=True),  # ai_masking: per type, no value
        sa.Column("client", sa.String(20), nullable=True),
        sa.Column("dedupe_key", sa.String(120), nullable=True),  # views: one per 15 minutes
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")",
            name=op.f(f"ck_{TABLE}_kind_code"),
        ),
        sa.CheckConstraint(
            "subject_person_id IS NOT NULL OR record_id IS NOT NULL",
            name=op.f(f"ck_{TABLE}_names_whose"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_personal_data_access_once",
        TABLE,
        ["tenant_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_index(
        "ix_personal_data_access_subject", TABLE, ["tenant_id", "subject_person_id", "occurred_at"]
    )
    op.create_index("ix_personal_data_access_time", TABLE, ["tenant_id", "occurred_at"])
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT"))  # append-only: rows leave only through the functions
    create_definer_function(
        "audit_erase_access", "p_subject uuid", "integer", _ERASE, volatility="VOLATILE"
    )
    create_definer_function(
        "audit_purge_access", "p_before timestamptz", "integer", _PURGE, volatility="VOLATILE"
    )
    allow_migrator_read("tenant_data_keys", KEYS_POLICY)
    create_definer_function("sx_kek_wraps", "", "TABLE (kek_id text, wraps bigint)", _WRAPS)


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE})
            OR EXISTS (SELECT 1 FROM audit_settings WHERE personal_data_log) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % uses the personal data access log', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table name, no input


def downgrade() -> None:
    """Drops what upgrade added only while no tenant has an entry (rule 5h)."""
    op.execute(_REFUSE_IF_ANY)
    drop_definer_function("sx_kek_wraps()")
    drop_policy("tenant_data_keys", KEYS_POLICY)
    drop_definer_function("audit_purge_access(timestamptz)")
    drop_definer_function("audit_erase_access(uuid)")
    op.drop_table(TABLE)  # its indexes and policies go with it
    op.drop_column("audit_settings", "personal_data_log")
