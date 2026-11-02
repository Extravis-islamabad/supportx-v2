"""The connector secrets store, and mailbox secrets copied into it (WP-040 session 1).

Expand only (D-113; the contract step that drops the mailbox columns comes once the store is
proven):
- connector_secrets (RLS, FORCE): one sealed credential per (owner, role), its name, type, sealing
  purpose and age, and `last_four` for display (product owner, 2026-11-02: long random secrets
  only, never a password; a certificate shows its public thumbprint's end). Copied rows get it
  the next time the application opens them.
- mailboxes: `secret_ref`, `token_ref` (to the store) and `secret_fallback_at` (the store's copy
  could not be read and the old column was used; shown as degraded).
- Data, per tenant under FORCE RLS: every live mailbox's credential and refresh token is copied
  as sealed bytes with its key ID and purpose. Nothing is opened here: the store unseals them
  with the same tenant and purpose context as before, and no secret is ever in clear in SQL or
  in this migration's output. The old columns stay and the application keeps writing both, so
  the downgrade (clear the references, drop the table) loses nothing.

IDs of copied rows come from gen_random_uuid() (a data step, as in 0023); new rows get UUIDv7.

Revision ID: 0045
Revises: 0043 (lane A's 0044 comes first at merge; down_revision is re-pointed when queued)
Created: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0045"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOOP_HEAD = """
DO $$
DECLARE
    t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
"""
_LOOP_TAIL = """
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""


def _per_tenant(statement: str) -> str:
    """Fixed statements (written in this file) for each tenant, under FORCE RLS."""
    return _LOOP_HEAD + statement + _LOOP_TAIL


COPY = _per_tenant(
    """
        INSERT INTO connector_secrets
            (id, tenant_id, name, secret_type, owner_kind, owner_id, role, purpose, key_id,
             sealed, set_at)
        SELECT gen_random_uuid(), m.tenant_id, 'mailbox.' || m.id || '.credential',
               CASE WHEN m.protocol = 'imap' THEN 'password'
                    WHEN m.credential_kind = 'certificate' THEN 'certificate'
                    ELSE 'client_secret' END,
               'mailbox', m.id, 'credential', 'mailbox', m.secret_key_id, m.secret_sealed,
               m.updated_at
          FROM mailboxes m
         WHERE m.tenant_id = t AND m.deleted_at IS NULL
           AND m.secret_key_id IS NOT NULL AND m.secret_sealed IS NOT NULL;
        INSERT INTO connector_secrets
            (id, tenant_id, name, secret_type, owner_kind, owner_id, role, purpose, key_id,
             sealed, set_at)
        SELECT gen_random_uuid(), m.tenant_id, 'mailbox.' || m.id || '.refresh_token',
               'refresh_token', 'mailbox', m.id, 'refresh_token', 'mailbox_token',
               m.token_key_id, m.token_sealed, m.updated_at
          FROM mailboxes m
         WHERE m.tenant_id = t AND m.deleted_at IS NULL
           AND m.token_key_id IS NOT NULL AND m.token_sealed IS NOT NULL;
        UPDATE mailboxes m SET secret_ref = s.id
          FROM connector_secrets s
         WHERE m.tenant_id = t AND s.tenant_id = t AND s.owner_kind = 'mailbox'
           AND s.owner_id = m.id AND s.role = 'credential';
        UPDATE mailboxes m SET token_ref = s.id
          FROM connector_secrets s
         WHERE m.tenant_id = t AND s.tenant_id = t AND s.owner_kind = 'mailbox'
           AND s.owner_id = m.id AND s.role = 'refresh_token';
"""
)
CLEAR = _per_tenant(
    "UPDATE mailboxes SET secret_ref = NULL, token_ref = NULL"
    " WHERE tenant_id = t AND (secret_ref IS NOT NULL OR token_ref IS NOT NULL);"
)


def upgrade() -> None:
    op.create_table(
        "connector_secrets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("secret_type", sa.String(length=20), nullable=False),
        sa.Column("owner_kind", sa.String(length=40), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("key_id", sa.String(length=32), nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_four", sa.String(length=4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "secret_type IN ('password', 'client_secret', 'certificate', 'refresh_token')",
            name=op.f("ck_connector_secrets_secret_type_code"),
        ),
        sa.CheckConstraint(
            "secret_type <> 'password' OR last_four IS NULL",
            name=op.f("ck_connector_secrets_no_password_ending"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_connector_secrets_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_secrets")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_connector_secrets_tenant_id_id"),
    )
    op.create_index(
        "uq_connector_secrets_tenant_owner_role",
        "connector_secrets",
        ["tenant_id", "owner_kind", "owner_id", "role"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_connector_secrets_tenant_name",
        "connector_secrets",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("connector_secrets")
    enable_actor_audit("connector_secrets")
    grant_app("connector_secrets", ("SELECT", "INSERT", "UPDATE"))

    op.add_column("mailboxes", sa.Column("secret_ref", sa.Uuid(), nullable=True))
    op.add_column("mailboxes", sa.Column("token_ref", sa.Uuid(), nullable=True))
    op.add_column(
        "mailboxes", sa.Column("secret_fallback_at", sa.DateTime(timezone=True), nullable=True)
    )
    for column in ("secret_ref", "token_ref"):
        op.create_foreign_key(
            f"fk_mailboxes_{column}",
            "mailboxes",
            "connector_secrets",
            ["tenant_id", column],
            ["tenant_id", "id"],
        )
    op.execute(COPY)


def downgrade() -> None:
    # Lossless: the application wrote the old columns too, so they hold every current value.
    op.execute(CLEAR)
    for column in ("token_ref", "secret_ref"):
        op.drop_constraint(f"fk_mailboxes_{column}", "mailboxes", type_="foreignkey")
    op.drop_column("mailboxes", "secret_fallback_at")
    op.drop_column("mailboxes", "token_ref")
    op.drop_column("mailboxes", "secret_ref")
    op.drop_table("connector_secrets")
