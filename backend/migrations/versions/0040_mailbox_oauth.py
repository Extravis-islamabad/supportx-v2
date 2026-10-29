"""Microsoft 365 and Gmail mailboxes (WP-024 session 2).

Expand only: new nullable columns, a wider protocol check, and host/port/username nullable
(an API mailbox has none). The client credential reuses `secret_*` (sealed, as the IMAP
password); the refresh token and a pending consent are sealed the same way. The consent's state
is stored only as a SHA-256 hash.

Revision ID: 0040
Revises: 0038
Created: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    sa.Column("auth_model", sa.String(length=12), nullable=True),
    sa.Column("client_id", sa.String(length=255), nullable=True),
    sa.Column("directory_id", sa.String(length=64), nullable=True),
    sa.Column("credential_kind", sa.String(length=12), nullable=True),
    sa.Column("credential_expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("credential_warned_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("token_key_id", sa.String(length=32), nullable=True),
    sa.Column("token_sealed", sa.LargeBinary(), nullable=True),
    sa.Column("connected_account", sa.String(length=320), nullable=True),
    sa.Column("oauth_state_hash", sa.String(length=64), nullable=True),
    sa.Column("oauth_pending_key_id", sa.String(length=32), nullable=True),
    sa.Column("oauth_pending_sealed", sa.LargeBinary(), nullable=True),
    sa.Column("oauth_pending_until", sa.DateTime(timezone=True), nullable=True),
)


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("mailboxes", column)
    for name in ("host", "port", "username"):
        op.alter_column("mailboxes", name, nullable=True)
    op.drop_constraint(op.f("ck_mailboxes_protocol_code"), "mailboxes", type_="check")
    op.create_check_constraint(
        op.f("ck_mailboxes_protocol_code"), "mailboxes", "protocol IN ('imap', 'graph', 'gmail')"
    )
    op.create_check_constraint(
        op.f("ck_mailboxes_auth_model_code"),
        "mailboxes",
        "auth_model IS NULL OR auth_model IN ('app', 'delegated')",
    )
    op.create_check_constraint(
        op.f("ck_mailboxes_credential_kind_code"),
        "mailboxes",
        "credential_kind IS NULL OR credential_kind IN ('secret', 'certificate')",
    )
    # An IMAP mailbox still needs its server and account.
    op.create_check_constraint(
        op.f("ck_mailboxes_imap_server"),
        "mailboxes",
        "protocol <> 'imap' OR (host IS NOT NULL AND port IS NOT NULL AND username IS NOT NULL)",
    )
    # The consent callback finds its mailbox by the state's hash (the tenant's session).
    op.create_index(
        "uq_mailboxes_tenant_oauth_state",
        "mailboxes",
        ["tenant_id", "oauth_state_hash"],
        unique=True,
        postgresql_where=sa.text("oauth_state_hash IS NOT NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    api = bind.execute(sa.text("SELECT count(*) FROM mailboxes WHERE protocol <> 'imap'")).scalar()
    if api:
        # Never drop a customer's mailbox settings silently (CLAUDE.md rule h).
        msg = "remove the Microsoft 365 and Gmail mailboxes (Admin > Mail) before downgrading"
        raise RuntimeError(msg)
    op.drop_index("uq_mailboxes_tenant_oauth_state", table_name="mailboxes")
    for name in ("imap_server", "credential_kind_code", "auth_model_code", "protocol_code"):
        op.drop_constraint(op.f(f"ck_mailboxes_{name}"), "mailboxes", type_="check")
    op.create_check_constraint(
        op.f("ck_mailboxes_protocol_code"), "mailboxes", "protocol IN ('imap')"
    )
    for name in ("host", "port", "username"):
        op.alter_column("mailboxes", name, nullable=False)
    for column in reversed(_COLUMNS):
        op.drop_column("mailboxes", column.name)
