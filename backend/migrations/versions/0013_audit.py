"""Audit log (WP-018, ADR-027): append-only entries, a per-tenant hash chain, signed anchors.

Tables (all tenant-scoped with RLS):
- audit_entries: partitioned by month on occurred_at; the app may INSERT and SELECT only;
- audit_queue: entries waiting to be sealed; INSERT and SELECT;
- audit_chain: SELECT only for the app. Rows are written by `audit_seal()`, a SECURITY DEFINER
  function owned by the migrator that computes every chain hash in the database;
- audit_personal: personal data outside the hash, one row per subject; INSERT and SELECT; only
  `audit_erase_subject()` deletes;
- audit_anchors: signed checkpoints; INSERT and SELECT;
- audit_settings, audit_verification_runs, audit_exports: SELECT, INSERT, UPDATE;
- audit_saved_searches: a person's own saved searches; SELECT, INSERT, DELETE;
- audit_archives: months past retention written to object storage; SELECT, INSERT, UPDATE;
- audit_cutoffs: per tenant, entries before `hidden_before` are archived and hidden from every
  app query by the select policies of audit_entries and audit_personal; SELECT only;
- audit_restored: archived entries restored for an investigation; SELECT, INSERT, DELETE.

Functions (EXECUTE for supportx_app only):
- audit_seal(limit): seals up to `limit` queued entries of the current tenant, in order, under a
  per-tenant advisory lock;
- audit_erase_subject(subject): deletes one person's personal rows (REQ-AUD-013);
- audit_tenant_ids(): every tenant ID, so the worker's schedules can visit each tenant;
- audit_ensure_partitions(months_ahead, months_back): creates monthly partitions (with RLS);
- audit_advance_cutoff(before): moves the tenant's cut-off, only behind a ready archive and never
  inside one year, and deletes the personal rows before it;
- audit_drop_expired_partitions(): drops monthly partitions whose rows are behind every
  tenant's cut-off (mixed retention, D-075 item 10).

FORCE ROW LEVEL SECURITY binds the table owner too, so the definer functions still see only the
tenant in `app.tenant_id` (audit_tenant_ids reads `tenants`, where the migrator has its own
policy).

Revision ID: 0013
Revises: 0012
Created: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.shared.db.rls import APP_ROLE, MIGRATOR_ROLE
from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = (
    "audit_seal(integer)",
    "audit_erase_subject(uuid)",
    "audit_tenant_ids()",
    "audit_ensure_partitions(integer, integer)",
    "audit_advance_cutoff(timestamptz)",
    "audit_drop_expired_partitions()",
)
# Retention (D-075 item 10): the migrator may read every tenant's entries, cut-offs and archives,
# so the partition clean-up can tell when a whole month has expired for every tenant. Without
# these policies FORCE RLS would show it nothing and it could drop live data. Allowlisted in
# tooling/rls_guard.py; no other role is affected.
MAINTENANCE_SELECT = ("audit_entries", "audit_cutoffs", "audit_archives")
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# Advances the tenant's cut-off: entries before it are hidden from every app query. Only behind
# a ready archive and never inside the platform minimum of one year; personal rows before the
# cut-off are deleted (they are in the archive). Returns the new cut-off.
CUTOFF = """
CREATE FUNCTION audit_advance_cutoff(p_before timestamptz) RETURNS timestamptz
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    t uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
    archived_to timestamptz;
    current_cutoff timestamptz;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'audit_advance_cutoff needs app.tenant_id';
    END IF;
    IF p_before > now() - interval '365 days' THEN
        RAISE EXCEPTION 'the audit log keeps at least one year';
    END IF;
    SELECT max(range_to) INTO archived_to
      FROM audit_archives WHERE tenant_id = t AND status = 'ready';
    IF archived_to IS NULL OR archived_to < p_before THEN
        RAISE EXCEPTION 'entries before the cut-off are not archived';
    END IF;
    SELECT hidden_before INTO current_cutoff FROM audit_cutoffs WHERE tenant_id = t;
    IF current_cutoff IS NOT NULL AND current_cutoff >= p_before THEN
        RETURN current_cutoff;
    END IF;
    INSERT INTO audit_cutoffs (tenant_id, hidden_before, updated_at)
    VALUES (t, p_before, now())
    ON CONFLICT (tenant_id) DO UPDATE SET hidden_before = EXCLUDED.hidden_before,
                                          updated_at = EXCLUDED.updated_at;
    DELETE FROM audit_personal WHERE tenant_id = t AND occurred_at < p_before;
    RETURN p_before;
END
$$
"""

# Drops monthly partitions older than a year whose every row is behind its tenant's cut-off.
DROP_EXPIRED = """
CREATE FUNCTION audit_drop_expired_partitions() RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    part record;
    m date;
    dropped integer := 0;
BEGIN
    FOR part IN
        SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
         WHERE i.inhparent = 'public.audit_entries'::regclass
           AND c.relname ~ '^audit_entries_p[0-9]{6}$'
         ORDER BY c.relname
    LOOP
        m := to_date(substr(part.relname, 16), 'YYYYMM');
        CONTINUE WHEN (m + interval '1 month') > now() - interval '365 days';
        CONTINUE WHEN EXISTS (
            SELECT 1 FROM public.audit_entries e
              LEFT JOIN public.audit_cutoffs c ON c.tenant_id = e.tenant_id
             WHERE e.occurred_at >= m AND e.occurred_at < m + interval '1 month'
               AND (c.hidden_before IS NULL OR e.occurred_at >= c.hidden_before)
        );
        EXECUTE format('ALTER TABLE public.audit_entries DETACH PARTITION public.%I', part.relname);
        EXECUTE format('DROP TABLE public.%I', part.relname);
        dropped := dropped + 1;
    END LOOP;
    RETURN dropped;
END
$$
"""

SEAL = """
CREATE FUNCTION audit_seal(p_limit integer) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    t uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
    last_seq bigint;
    last_hash bytea;
    next_hash bytea;
    r record;
    sealed integer := 0;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'audit_seal needs app.tenant_id';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 5000 THEN
        RAISE EXCEPTION 'audit_seal limit must be between 1 and 5000';
    END IF;
    -- One sealer per tenant at a time; others wait and then find the queue already sealed.
    PERFORM pg_advisory_xact_lock(724118, hashtext(t::text));
    SELECT c.seq, c.chain_hash INTO last_seq, last_hash
      FROM audit_chain c WHERE c.tenant_id = t ORDER BY c.seq DESC LIMIT 1;
    IF last_seq IS NULL THEN
        last_seq := 0;
        last_hash := decode(repeat('00', 32), 'hex');
    END IF;
    FOR r IN
        SELECT q.entry_id, q.occurred_at, e.entry_hash
          FROM audit_queue q
          JOIN audit_entries e
            ON e.tenant_id = q.tenant_id AND e.occurred_at = q.occurred_at AND e.id = q.entry_id
         WHERE q.tenant_id = t
         ORDER BY q.occurred_at, q.entry_id
         LIMIT p_limit
    LOOP
        last_seq := last_seq + 1;
        -- Same bytes as app/modules/audit/domain/integrity.py chain_hash().
        next_hash := sha256(
            convert_to('sx-audit-v1', 'UTF8') || uuid_send(t) || int8send(last_seq)
            || last_hash || r.entry_hash
        );
        INSERT INTO audit_chain
            (tenant_id, seq, entry_id, entry_occurred_at, entry_hash, prev_hash, chain_hash,
             sealed_at)
        VALUES (t, last_seq, r.entry_id, r.occurred_at, r.entry_hash, last_hash, next_hash,
                clock_timestamp());
        DELETE FROM audit_queue WHERE tenant_id = t AND entry_id = r.entry_id;
        last_hash := next_hash;
        sealed := sealed + 1;
    END LOOP;
    RETURN sealed;
END
$$
"""

ERASE = """
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

TENANT_IDS = """
CREATE FUNCTION audit_tenant_ids() RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT id FROM tenants ORDER BY id
$$
"""

# Creates the missing monthly partitions from last month to `months_ahead` months ahead. Each
# partition gets the tenant policies too (the RLS guard checks every table), and no app grants:
# the app reaches rows only through the parent, whose policies apply.
PARTITIONS = """
CREATE FUNCTION audit_ensure_partitions(p_months_ahead integer, p_months_back integer DEFAULT 1)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    first_month date;
    m date;
    name text;
    match text := 'tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid';
    created integer := 0;
BEGIN
    IF p_months_ahead IS NULL OR p_months_ahead < 1 OR p_months_ahead > 36 THEN
        RAISE EXCEPTION 'months ahead must be between 1 and 36';
    END IF;
    IF p_months_back IS NULL OR p_months_back < 0 OR p_months_back > 240 THEN
        RAISE EXCEPTION 'months back must be between 0 and 240';
    END IF;
    first_month := (date_trunc('month', now()) - make_interval(months => p_months_back))::date;
    FOR i IN 0 .. p_months_ahead + p_months_back LOOP
        m := (first_month + make_interval(months => i))::date;
        name := 'audit_entries_p' || to_char(m, 'YYYYMM');
        IF to_regclass('public.' || name) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE public.%I PARTITION OF public.audit_entries FOR VALUES FROM (%L) TO (%L)',
                name, m, (m + interval '1 month')::date
            );
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', name);
            EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', name);
            EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT USING (%s)',
                           name || '_tenant_select', name, match);
            EXECUTE format('CREATE POLICY %I ON public.%I FOR INSERT WITH CHECK (%s)',
                           name || '_tenant_insert', name, match);
            EXECUTE format('CREATE POLICY %I ON public.%I FOR UPDATE USING (%s) WITH CHECK (%s)',
                           name || '_tenant_update', name, match, match);
            EXECUTE format('CREATE POLICY %I ON public.%I FOR DELETE USING (%s)',
                           name || '_tenant_delete', name, match);
            EXECUTE format('REVOKE ALL ON public.%I FROM supportx_app', name);
            created := created + 1;
        END IF;
    END LOOP;
    RETURN created;
END
$$
"""

DEFAULT_PARTITION = "audit_entries_default"


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _retention() -> None:
    """Archives, cut-offs and restored copies (D-075 item 10)."""
    op.create_table(
        "audit_archives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("range_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("range_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=True),
        sa.Column("entries", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("first_seq", sa.BigInteger(), nullable=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("problem", sa.String(length=60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restore_status", sa.String(length=20), nullable=True),
        sa.Column("restore_problem", sa.String(length=60), nullable=True),
        sa.Column("restored_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ready', 'failed')", name=op.f("ck_audit_archives_status_code")
        ),
        sa.CheckConstraint(
            "restore_status IN ('running', 'ready', 'failed')",
            name=op.f("ck_audit_archives_restore_status_code"),
        ),
        sa.CheckConstraint("range_to > range_from", name=op.f("ck_audit_archives_range_order")),
        _tenant_fk("audit_archives"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_archives")),
    )
    op.create_index("ix_audit_archives_tenant_range", "audit_archives", ["tenant_id", "range_from"])
    enable_tenant_rls("audit_archives")
    grant_app("audit_archives", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "audit_cutoffs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("hidden_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _tenant_fk("audit_cutoffs"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_audit_cutoffs")),
    )
    enable_tenant_rls("audit_cutoffs")
    grant_app("audit_cutoffs", ("SELECT",))

    op.create_table(
        "audit_restored",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("archive_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("entry", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("entry_hash", sa.LargeBinary(), nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=False),
        sa.Column("chain_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _tenant_fk("audit_restored"),
        sa.PrimaryKeyConstraint("tenant_id", "archive_id", "seq", name=op.f("pk_audit_restored")),
    )
    enable_tenant_rls("audit_restored")
    grant_app("audit_restored", ("SELECT", "INSERT", "DELETE"))

    # The cut-off (retention, D-075 item 10): rows before it stay in place but no app query sees
    # them, until the whole monthly partition can go.
    for table in ("audit_entries", "audit_personal"):
        op.execute(f"DROP POLICY {table}_tenant_select ON {table}")
        op.execute(
            f"CREATE POLICY {table}_tenant_select ON {table} FOR SELECT USING ("  # noqa: S608 - fixed table names
            f"tenant_id = {CURRENT_TENANT} AND occurred_at >= COALESCE(("
            f"SELECT c.hidden_before FROM audit_cutoffs c WHERE c.tenant_id = {CURRENT_TENANT}"
            "), '-infinity'::timestamptz))"
        )
    for table in MAINTENANCE_SELECT:
        op.execute(
            f"CREATE POLICY {table}_maintenance_select ON {table} FOR SELECT "
            f"TO {MIGRATOR_ROLE} USING (true)"
        )


def upgrade() -> None:
    op.create_table(
        "audit_entries",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("module", sa.String(length=40), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("on_behalf_id", sa.Uuid(), nullable=True),
        sa.Column("object_type", sa.String(length=40), nullable=True),
        sa.Column("object_id", sa.String(length=128), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("client", sa.String(length=20), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("change_id", sa.Uuid(), nullable=True),
        sa.Column(
            "personal_commitments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("entry_hash", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('done', 'refused', 'failed')", name=op.f("ck_audit_entries_outcome_code")
        ),
        sa.CheckConstraint(
            "actor_type IN ('person', 'service_account', 'api_key', 'ai_agent', 'automation', "
            "'system', 'vendor_support')",
            name=op.f("ck_audit_entries_actor_type_code"),
        ),
        sa.CheckConstraint(
            "client IN ('console', 'portal', 'mobile', 'api', 'worker')",
            name=op.f("ck_audit_entries_client_code"),
        ),
        sa.CheckConstraint(
            "octet_length(entry_hash) = 32", name=op.f("ck_audit_entries_entry_hash_length")
        ),
        sa.CheckConstraint(
            "action ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$'",
            name=op.f("ck_audit_entries_action_code"),
        ),
        _tenant_fk("audit_entries"),
        sa.PrimaryKeyConstraint("tenant_id", "occurred_at", "id", name=op.f("pk_audit_entries")),
        postgresql_partition_by="RANGE (occurred_at)",
    )
    op.create_index("ix_audit_entries_tenant_id_id", "audit_entries", ["tenant_id", "id"])
    op.create_index(
        "ix_audit_entries_tenant_actor_time",
        "audit_entries",
        ["tenant_id", "actor_id", "occurred_at"],
    )
    op.create_index(
        "ix_audit_entries_tenant_action_time",
        "audit_entries",
        ["tenant_id", "action", "occurred_at"],
    )
    op.create_index(
        "ix_audit_entries_tenant_object_time",
        "audit_entries",
        ["tenant_id", "object_type", "object_id", "occurred_at"],
    )
    op.create_index(
        "ix_audit_entries_tenant_change",
        "audit_entries",
        ["tenant_id", "change_id"],
        postgresql_where=sa.text("change_id IS NOT NULL"),
    )
    op.create_index(
        "ix_audit_entries_tenant_outcome_time",
        "audit_entries",
        ["tenant_id", "outcome", "occurred_at"],
        postgresql_where=sa.text("outcome <> 'done'"),
    )
    enable_tenant_rls("audit_entries")
    grant_app("audit_entries", ("SELECT", "INSERT"))

    op.create_table(
        "audit_queue",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _tenant_fk("audit_queue"),
        sa.PrimaryKeyConstraint("tenant_id", "entry_id", name=op.f("pk_audit_queue")),
    )
    enable_tenant_rls("audit_queue")
    grant_app("audit_queue", ("SELECT", "INSERT"))

    op.create_table(
        "audit_chain",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("entry_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_hash", sa.LargeBinary(), nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=False),
        sa.Column("chain_hash", sa.LargeBinary(), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_audit_chain_seq_positive")),
        sa.CheckConstraint(
            "octet_length(entry_hash) = 32 AND octet_length(prev_hash) = 32 "
            "AND octet_length(chain_hash) = 32",
            name=op.f("ck_audit_chain_hash_lengths"),
        ),
        _tenant_fk("audit_chain"),
        sa.PrimaryKeyConstraint("tenant_id", "seq", name=op.f("pk_audit_chain")),
        sa.UniqueConstraint("tenant_id", "entry_id", name="uq_audit_chain_tenant_id_entry_id"),
    )
    op.create_index("ix_audit_chain_tenant_sealed", "audit_chain", ["tenant_id", "sealed_at"])
    enable_tenant_rls("audit_chain")
    grant_app("audit_chain", ("SELECT",))

    op.create_table(
        "audit_personal",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("salt", sa.LargeBinary(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("octet_length(salt) = 16", name=op.f("ck_audit_personal_salt_length")),
        _tenant_fk("audit_personal"),
        sa.PrimaryKeyConstraint(
            "tenant_id", "entry_id", "subject_id", name=op.f("pk_audit_personal")
        ),
    )
    op.create_index(
        "ix_audit_personal_tenant_subject", "audit_personal", ["tenant_id", "subject_id"]
    )
    op.create_index("ix_audit_personal_tenant_time", "audit_personal", ["tenant_id", "occurred_at"])
    enable_tenant_rls("audit_personal")
    grant_app("audit_personal", ("SELECT", "INSERT"))

    op.create_table(
        "audit_anchors",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("chain_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key_id", sa.String(length=40), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint(
            "octet_length(chain_hash) = 32", name=op.f("ck_audit_anchors_chain_hash_length")
        ),
        sa.CheckConstraint(
            "octet_length(public_key) = 32", name=op.f("ck_audit_anchors_public_key_length")
        ),
        sa.CheckConstraint(
            "octet_length(signature) = 64", name=op.f("ck_audit_anchors_signature_length")
        ),
        _tenant_fk("audit_anchors"),
        sa.PrimaryKeyConstraint("tenant_id", "seq", name=op.f("pk_audit_anchors")),
    )
    enable_tenant_rls("audit_anchors")
    grant_app("audit_anchors", ("SELECT", "INSERT"))

    op.create_table(
        "audit_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("read_window_minutes", sa.Integer(), nullable=False),
        sa.Column("refusal_threshold", sa.Integer(), nullable=False),
        sa.Column("refusal_window_minutes", sa.Integer(), nullable=False),
        sa.Column("read_categories", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "retention_days BETWEEN 365 AND 3650", name=op.f("ck_audit_settings_retention_range")
        ),
        sa.CheckConstraint(
            "read_window_minutes BETWEEN 1 AND 1440",
            name=op.f("ck_audit_settings_read_window_range"),
        ),
        sa.CheckConstraint(
            "refusal_threshold BETWEEN 3 AND 1000",
            name=op.f("ck_audit_settings_refusal_threshold_range"),
        ),
        sa.CheckConstraint(
            "refusal_window_minutes BETWEEN 1 AND 1440",
            name=op.f("ck_audit_settings_refusal_window_range"),
        ),
        _tenant_fk("audit_settings"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_audit_settings")),
    )
    enable_tenant_rls("audit_settings")
    grant_app("audit_settings", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "audit_verification_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("range_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("range_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entries_checked", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("unsealed_overdue", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("first_broken_seq", sa.BigInteger(), nullable=True),
        sa.Column("first_broken_entry_id", sa.Uuid(), nullable=True),
        sa.Column("problem", sa.String(length=40), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('daily', 'weekly', 'on_demand')",
            name=op.f("ck_audit_verification_runs_kind_code"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'error')",
            name=op.f("ck_audit_verification_runs_status_code"),
        ),
        _tenant_fk("audit_verification_runs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_verification_runs")),
    )
    op.create_index(
        "ix_audit_verification_runs_tenant_started",
        "audit_verification_runs",
        ["tenant_id", "started_at"],
    )
    enable_tenant_rls("audit_verification_runs")
    grant_app("audit_verification_runs", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "audit_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("range_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("range_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("entries", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("verification", sa.String(length=20), nullable=True),
        sa.Column("problem", sa.String(length=60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'ready', 'failed', 'expired')",
            name=op.f("ck_audit_exports_status_code"),
        ),
        sa.CheckConstraint("format IN ('jsonl', 'csv')", name=op.f("ck_audit_exports_format_code")),
        _tenant_fk("audit_exports"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_exports")),
    )
    op.create_index("ix_audit_exports_tenant_created", "audit_exports", ["tenant_id", "created_at"])
    enable_tenant_rls("audit_exports")
    grant_app("audit_exports", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "audit_saved_searches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("query", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 100",
            name=op.f("ck_audit_saved_searches_name_length"),
        ),
        _tenant_fk("audit_saved_searches"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_saved_searches")),
    )
    op.create_index(
        "ix_audit_saved_searches_tenant_owner",
        "audit_saved_searches",
        ["tenant_id", "owner_id"],
    )
    enable_tenant_rls("audit_saved_searches")
    grant_app("audit_saved_searches", ("SELECT", "INSERT", "DELETE"))

    _retention()

    for statement in (SEAL, ERASE, TENANT_IDS, PARTITIONS, CUTOFF, DROP_EXPIRED):
        op.execute(statement)
    for function in FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")

    # An empty catch-all partition: anything outside the monthly partitions lands here and is
    # reported by verification; normal entries never do.
    op.execute(f"CREATE TABLE {DEFAULT_PARTITION} PARTITION OF audit_entries DEFAULT")
    enable_tenant_rls(DEFAULT_PARTITION)
    op.execute(f"REVOKE ALL ON {DEFAULT_PARTITION} FROM {APP_ROLE}")
    op.execute("SELECT audit_ensure_partitions(24)")


def downgrade() -> None:
    for function in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    # The select policies read audit_cutoffs, so they go before it.
    for table in MAINTENANCE_SELECT:
        op.execute(f"DROP POLICY IF EXISTS {table}_maintenance_select ON {table}")
    for table in ("audit_entries", "audit_personal"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_select ON {table}")
    for table in (
        "audit_restored",
        "audit_cutoffs",
        "audit_archives",
        "audit_saved_searches",
        "audit_exports",
        "audit_verification_runs",
        "audit_settings",
        "audit_anchors",
        "audit_personal",
        "audit_chain",
        "audit_queue",
        "audit_entries",  # its partitions go with it
    ):
        op.drop_table(table)
