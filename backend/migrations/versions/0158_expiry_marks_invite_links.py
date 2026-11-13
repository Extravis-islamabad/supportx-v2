"""Expiry alerts and copied invite links (identity_access; WP-057 S2b-2: REQ-SEC-011, REQ-SEC-021).

Expand only, no data step:
- `security_expiry_marks`: each certificate or secret expiry alert already sent (30, 7, 1 days
  before; 0 = run out), one row each, so the daily schedule tells the tenant admins once. A mark
  names its provider (tenant-scoped key: `uq_sso_providers_tenant_id_id`, added here) and what
  runs out (a certificate's SHA-256, or `client_secret`). Tenant table, RLS forced.
- `sso_providers.client_secret_expires_at`: an OIDC client secret's expiry, entered by an admin.
- `invitations.delivery` gains `link`, and `invitations.link_token_hash` (the SHA-256 of a copied invite link's token, 32 bytes, unique per
  tenant) and `invitations.link_copied_at`. The token itself is never stored.

- `security_notice_marks` (REQ-SEC-033 part 2): each Keycloak user event already turned into a
  notice to the person (or kept quiet), once per Keycloak event ID. Only what the once-only check
  and the lock-out count need: no address, browser or client (lane B). Purged after 30 days;
  erasure deletes the person's rows. Tenant table, RLS forced.

The downgrade refuses while any tenant has a mark, a secret expiry or a copied link, per tenant
with app.tenant_id set (rule 5h).

Revision ID: 0158
Revises: 0157
Created: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0158"
down_revision: str | None = "0157"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKS = "security_expiry_marks"
NOTICES = "security_notice_marks"
NOTICE_KINDS = ("locked_out", "password_changed", "password_set", "mfa_added", "mfa_removed")
PROVIDERS = "sso_providers"
INVITATIONS = "invitations"
THRESHOLDS = (0, 1, 7, 30)


def upgrade() -> None:
    """Adds the marks table, the secret expiry and the invite link columns."""
    op.create_unique_constraint("uq_sso_providers_tenant_id_id", PROVIDERS, ["tenant_id", "id"])
    op.add_column(
        PROVIDERS, sa.Column("client_secret_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(INVITATIONS, sa.Column("link_token_hash", sa.LargeBinary(), nullable=True))
    op.add_column(
        INVITATIONS, sa.Column("link_copied_at", sa.DateTime(timezone=True), nullable=True)
    )
    # A link is a third way to deliver an invitation (when no mail is set up, REQ-SEC-021).
    op.drop_constraint(op.f(f"ck_{INVITATIONS}_delivery_code"), INVITATIONS, type_="check")
    op.create_check_constraint(
        op.f(f"ck_{INVITATIONS}_delivery_code"),
        INVITATIONS,
        "delivery IN ('email', 'existing_account', 'link')",
    )
    op.create_check_constraint(
        op.f(f"ck_{INVITATIONS}_link_token_hash_length"),
        INVITATIONS,
        "link_token_hash IS NULL OR octet_length(link_token_hash) = 32",
    )
    op.create_index(
        "uq_invitations_link_token",
        INVITATIONS,
        ["tenant_id", "link_token_hash"],
        unique=True,
        postgresql_where=sa.text("link_token_hash IS NOT NULL"),
    )

    op.create_table(
        MARKS,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("item", sa.String(64), nullable=False),
        sa.Column("threshold", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"threshold IN ({', '.join(str(t) for t in THRESHOLDS)})",
            name=op.f(f"ck_{MARKS}_threshold_code"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{MARKS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "provider_id"],
            ["sso_providers.tenant_id", "sso_providers.id"],
            name="fk_security_expiry_marks_provider",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f(f"pk_{MARKS}")),
        sa.UniqueConstraint(
            "tenant_id", "provider_id", "item", "threshold", name="uq_security_expiry_marks_once"
        ),
    )
    enable_tenant_rls(MARKS)
    grant_app(MARKS, ("SELECT", "INSERT"))  # append-only: an alert once sent stays sent

    op.create_table(
        NOTICES,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("keycloak_event_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("told", sa.Boolean(), nullable=False),  # False: kept quiet (rate limit, first)
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in NOTICE_KINDS) + ")",
            name=op.f(f"ck_{NOTICES}_kind_code"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{NOTICES}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_security_notice_marks_user",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f(f"pk_{NOTICES}")),
        sa.UniqueConstraint("tenant_id", "keycloak_event_id", name="uq_security_notice_marks_once"),
    )
    op.create_index(
        "ix_security_notice_marks_person",
        NOTICES,
        ["tenant_id", "user_id", "kind", "occurred_at"],
    )
    enable_tenant_rls(NOTICES)
    grant_app(NOTICES, ("SELECT", "INSERT", "DELETE"))  # the purge and erasure delete


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {NOTICES}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has security notices sent (rule 5h)', t;
        END IF;
        IF EXISTS (SELECT 1 FROM {MARKS}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has expiry alerts sent (rule 5h)', t;
        END IF;
        IF EXISTS (SELECT 1 FROM {PROVIDERS} WHERE client_secret_expires_at IS NOT NULL) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has a client secret expiry (rule 5h)', t;
        END IF;
        IF EXISTS (
            SELECT 1 FROM {INVITATIONS} WHERE link_token_hash IS NOT NULL OR delivery = 'link'
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has a copied invite link (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops what upgrade added only while nothing uses it; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table(NOTICES)  # its index and policies go with it
    op.drop_table(MARKS)  # its policies go with it
    op.drop_index("uq_invitations_link_token", table_name=INVITATIONS)
    op.drop_constraint(op.f(f"ck_{INVITATIONS}_link_token_hash_length"), INVITATIONS, type_="check")
    op.drop_constraint(op.f(f"ck_{INVITATIONS}_delivery_code"), INVITATIONS, type_="check")
    op.create_check_constraint(
        op.f(f"ck_{INVITATIONS}_delivery_code"),
        INVITATIONS,
        "delivery IN ('email', 'existing_account')",
    )
    op.drop_column(INVITATIONS, "link_copied_at")
    op.drop_column(INVITATIONS, "link_token_hash")
    op.drop_column(PROVIDERS, "client_secret_expires_at")
    op.drop_constraint("uq_sso_providers_tenant_id_id", PROVIDERS, type_="unique")
