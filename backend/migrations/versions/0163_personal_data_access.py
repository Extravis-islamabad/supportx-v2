"""Personal data access log (REQ-AUD-017) and the data-key wrap count (WP-057 S3b-1; ADR-050).

- `personal_data_access` (audit module, lane B blocks): who viewed or exported whose personal
  data, and the AI masking counts (REQ-AI-019). Never a value: field codes and counts only.
  Tenant table, RLS forced, **append-only** for the app role (SELECT and INSERT). Rows leave
  only through migrator-owned functions, with the tenant from `app.tenant_id`, never a parameter:
  - `audit_purge_access()`: the daily retention purge. It takes NO cutoff: it computes its own
    from the tenant's audit retention (at least 365 days), so the app can never empty the log
    with a future date (lane B, #500).
  - `audit_erase_access(subject)`: a person's erasure (ADR-052 step 6). It deletes only when that
    person is already erased (`users.erased_at`, set by step 5; #498's 0161), so the app can
    never use it to empty someone's entries early (lane B, #500). Hence 0163 follows 0161.
  A view is written once per accessor, record and 15 minutes (`dedupe_key`, unique per tenant):
  live refetches never flood it.
- `audit_settings.personal_data_log`: the tenant's switch (off by default).
- `sx_kek_wraps()`: how many data keys each key-encryption key wraps, over every tenant, and
  nothing else (no tenant, no key). The API refuses to start while a KEK no longer in the ring
  still wraps any (lane B's conditions). It reads each tenant in turn through the ordinary
  tenant policies, setting `app.tenant_id` and putting the caller's back: no policy of its own,
  so the RLS guard stays strict.

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
    create_definer_function,
    drop_definer_function,
    enable_tenant_rls,
    grant_app,
)

revision: str = "0163"
down_revision: str | None = "0158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "personal_data_access"
KINDS = ("view", "export", "ai_masking")
RETENTION_DEFAULT_DAYS = 3 * 365  # audit's default (service/settings.py) while no row exists

# The tenant, from the transaction's setting: no parameter can name another one.
_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_ERASE = f"""
    WITH gone AS (
        DELETE FROM {TABLE} a
        WHERE a.tenant_id = {_TENANT}
          AND a.subject_person_id = p_subject
          AND EXISTS (
              SELECT 1 FROM users u
              WHERE u.tenant_id = {_TENANT} AND u.id = p_subject AND u.erased_at IS NOT NULL
          )
        RETURNING 1
    )
    SELECT count(*)::integer FROM gone
"""  # noqa: S608 - fixed names, no input
_PURGE = f"""
    WITH gone AS (
        DELETE FROM {TABLE}
        WHERE tenant_id = {_TENANT}
          AND occurred_at < now() - make_interval(days => greatest(
              365,
              coalesce(
                  (SELECT s.retention_days FROM audit_settings s WHERE s.tenant_id = {_TENANT}),
                  {RETENTION_DEFAULT_DAYS}
              )
          ))
        RETURNING 1
    )
    SELECT count(*)::integer FROM gone
"""  # noqa: S608 - fixed names, no input
# Every tenant in turn, through the ordinary tenant policies (no policy of its own, so the RLS
# guard stays strict); the caller's app.tenant_id is put back afterwards. Rows per tenant and
# key, never naming the tenant: the caller adds them up.
_WRAPS = """
DECLARE
    t uuid;
    own text := current_setting('app.tenant_id', true);
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        RETURN QUERY
            SELECT d.kek_id::text, count(*)::bigint FROM tenant_data_keys d GROUP BY d.kek_id;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(own, ''), true);
END
"""


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
    create_definer_function("audit_purge_access", "", "integer", _PURGE, volatility="VOLATILE")
    create_definer_function(
        "sx_kek_wraps",
        "",
        "TABLE (kek_id text, wraps bigint)",
        _WRAPS,
        language="plpgsql",
        volatility="VOLATILE",  # it sets app.tenant_id per tenant, then puts it back
    )


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
    drop_definer_function("audit_purge_access()")
    drop_definer_function("audit_erase_access(uuid)")
    op.drop_table(TABLE)  # its indexes and policies go with it
    op.drop_column("audit_settings", "personal_data_log")
