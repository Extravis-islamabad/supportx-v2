"""Streaming audit and sign-in entries to a security monitoring system (WP-057 S5a), 0186.

REQ-AUD-011. `siem_destinations` (tenant-first, RLS): where a tenant's entries go (syslog over
TCP with TLS, or an HTTPS webhook), in which format (JSON or CEF), which streams (audit,
sign-ins), on or off, and how far each stream has been sent:

- `audit_seq_sent`: the last audit chain sequence the destination acknowledged. A new
  destination starts at the chain's current end (no history is replayed).
- `sign_in_after_at` / `sign_in_after_id`: the same for sign-in entries, by time and ID.
- Delivery health: last success, the last error (a code), when failing began, the next try.

Secrets (the webhook's signing secrets, a CA bundle, a client certificate and key) are stored
sealed (ADR-048/050 field cipher), never in plain text. Plain syslog is not offered: TLS only
(the coordinator, S5 Q4). The app role may insert and update, never delete (soft delete).

Revision ID: 0186
Revises: 0179 (main's head now; re-pointed at its queue turn)
Created: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0186"
down_revision: str | None = "0183"  # main's head at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "siem_destinations"
KINDS = ("syslog", "webhook")
FORMATS = ("json", "cef")
STREAMS = ("audit", "sign_ins")


def _codes(column: str, codes: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def upgrade() -> None:
    """The destinations table, with both cursors and its delivery health."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("format", sa.String(20), server_default="json", nullable=False),
        sa.Column("host", sa.String(253), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column(
            "streams",
            postgresql.ARRAY(sa.String(20)),
            server_default=sa.text("ARRAY['audit']::varchar[]"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        # Sealed with the field cipher (text blobs); None when not set.
        sa.Column("secret_sealed", sa.Text(), nullable=True),
        sa.Column("previous_secret_sealed", sa.Text(), nullable=True),
        sa.Column("ca_pem_sealed", sa.Text(), nullable=True),
        sa.Column("client_cert_sealed", sa.Text(), nullable=True),
        sa.Column("client_key_sealed", sa.Text(), nullable=True),
        sa.Column("audit_seq_sent", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("sign_in_after_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sign_in_after_id", sa.Uuid(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(40), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(_codes("kind", KINDS), name=op.f(f"ck_{TABLE}_kind_code")),
        sa.CheckConstraint(_codes("format", FORMATS), name=op.f(f"ck_{TABLE}_format_code")),
        sa.CheckConstraint(
            "streams <@ ARRAY['audit', 'sign_ins']::varchar[] AND cardinality(streams) > 0",
            name=op.f(f"ck_{TABLE}_streams_codes"),
        ),
        sa.CheckConstraint(
            "(kind = 'syslog' AND host IS NOT NULL AND port BETWEEN 1 AND 65535 AND url IS NULL)"
            " OR (kind = 'webhook' AND url IS NOT NULL AND host IS NULL AND port IS NULL"
            " AND format = 'json')",
            name=op.f(f"ck_{TABLE}_kind_target"),
        ),
        sa.CheckConstraint(
            "kind = 'syslog' OR secret_sealed IS NOT NULL", name=op.f(f"ck_{TABLE}_webhook_secret")
        ),
        sa.CheckConstraint(
            "(sign_in_after_at IS NULL) = (sign_in_after_id IS NULL)",
            name=op.f(f"ck_{TABLE}_sign_in_cursor"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f(f"fk_{TABLE}_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_siem_destinations_tenant_name",
        TABLE,
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # The schedule's question: which live destinations are due now.
    op.create_index(
        "ix_siem_destinations_tenant_due",
        TABLE,
        ["tenant_id", "next_attempt_at"],
        postgresql_where=sa.text("deleted_at IS NULL AND enabled"),
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))


# Business tables force RLS, so the check runs once per tenant (D-113); a plain literal (Semgrep).
GUARD = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM siem_destinations) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % streams to a SIEM (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Refused while any tenant has a destination (rule 5h); otherwise the table goes."""
    op.execute(GUARD)
    op.drop_table(TABLE)
