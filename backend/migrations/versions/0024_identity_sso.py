"""Sign-in settings and single sign-on per tenant (WP-039 session 1; ADR-033; D-089, D-094).

- identity_settings (new): per tenant, the console and portal session timeouts (REQ-SEC-029,
  Appendix A defaults and caps) and whether a first sign-in creates the person (REQ-SEC-013).
  No row = the defaults.
- sso_providers (new): a tenant's SAML and OpenID Connect set-ups (REQ-SEC-007, 008), each the
  mirror of a Keycloak identity provider linked to the tenant's organization. The client secret
  is never stored here (Keycloak keeps it, write-only).

Both tenant-scoped with RLS. Reversible: the downgrade drops both tables (the Keycloak
identity providers stay, as Keycloak's own data).

Revision ID: 0024
Revises: 0023
Created: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_settings",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("console_idle_seconds", sa.BigInteger(), server_default="3600", nullable=False),
        sa.Column(
            "console_absolute_seconds", sa.BigInteger(), server_default="43200", nullable=False
        ),
        sa.Column("portal_idle_seconds", sa.BigInteger(), server_default="1800", nullable=False),
        sa.Column(
            "portal_absolute_seconds", sa.BigInteger(), server_default="43200", nullable=False
        ),
        sa.Column("create_people_on_sign_in", sa.Boolean(), server_default="true", nullable=False),
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
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "console_absolute_seconds BETWEEN console_idle_seconds AND 604800 AND portal_absolute_seconds BETWEEN portal_idle_seconds AND 2592000",
            name=op.f("ck_identity_settings_absolute_range"),
        ),
        sa.CheckConstraint(
            "console_idle_seconds BETWEEN 300 AND 86400 AND portal_idle_seconds BETWEEN 300 AND 86400",
            name=op.f("ck_identity_settings_idle_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_identity_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_identity_settings")),
    )
    enable_tenant_rls("identity_settings")
    grant_app("identity_settings", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("identity_settings")
    op.create_table(
        "sso_providers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.String(length=60), nullable=False),
        sa.Column("protocol", sa.String(length=10), nullable=False),
        sa.Column("preset", sa.String(length=10), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=10), server_default="draft", nullable=False),
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "domains", postgresql.ARRAY(sa.String(length=253)), server_default="{}", nullable=False
        ),
        sa.Column("email_redirect", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_check", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tested_by", sa.UUID(), nullable=True),
        sa.Column("switched_on_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "preset IN ('entra', 'okta', 'google', 'oidc', 'saml')",
            name=op.f("ck_sso_providers_preset_code"),
        ),
        sa.CheckConstraint(
            "protocol IN ('oidc', 'saml')", name=op.f("ck_sso_providers_protocol_code")
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'tested', 'on', 'off')", name=op.f("ck_sso_providers_state_code")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_sso_providers_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sso_providers")),
        sa.UniqueConstraint("tenant_id", "alias", name="uq_sso_providers_tenant_alias"),
    )
    op.create_index(
        "ix_sso_providers_tenant_state", "sso_providers", ["tenant_id", "state"], unique=False
    )
    enable_tenant_rls("sso_providers")
    grant_app("sso_providers", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("sso_providers")


def downgrade() -> None:
    op.drop_index("ix_sso_providers_tenant_state", table_name="sso_providers")
    op.drop_table("sso_providers")
    op.drop_table("identity_settings")
