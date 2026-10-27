"""Tenant branding and domains (WP-017, D-027, D-090).

Tables (all tenant-scoped with RLS):

- tenant_branding: one row per tenant: colours, translated texts, the uploaded originals (files,
  owner `branding`) and the version of the generated variants. SELECT, INSERT, UPDATE.
- branding_assets: generated logo, icon and favicon variants (public images, kilobytes each).
  SELECT, INSERT, UPDATE, DELETE (replaced as a set on save).
- tenant_domains: custom domains, their proof of ownership and TLS state. A host is unique across
  tenants. SELECT, INSERT, UPDATE (removal is a soft delete).

file_links.owner_type gains `branding` (the record is the tenant itself).

Functions (EXECUTE for supportx_app only), SECURITY DEFINER because they run before anyone signs
in, when no tenant is set: each answers one exact question and returns only an active tenant's
id and slug, never a list.

- sx_tenant_for_host(host): the tenant whose verified custom domain is `host`;
- sx_tenant_for_slug(slug): the tenant with that slug (its subdomain, and the public branding
  route's key).

Additive (expand only; reversible).

Revision ID: 0022
Revises: 0021
Created: 2026-10-27
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.shared.db.rls import MIGRATOR_ROLE
from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HEX = "'^#[0-9a-f]{6}$'"

OWNER_TYPES_BEFORE = "owner_type IN ('work_item', 'conversation_entry', 'draft')"
OWNER_TYPES_AFTER = "owner_type IN ('work_item', 'conversation_entry', 'draft', 'branding')"

# One statement each: asyncpg runs every op.execute as a single prepared statement.
FUNCTIONS = (
    """
CREATE FUNCTION sx_tenant_for_host(p_host text) RETURNS TABLE (tenant_id uuid, slug text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT t.id, t.slug
    FROM tenant_domains d JOIN tenants t ON t.id = d.tenant_id
    WHERE d.host = lower(p_host) AND d.status = 'verified' AND d.deleted_at IS NULL
      AND t.status = 'active'
    LIMIT 1
$$""",
    """
CREATE FUNCTION sx_tenant_for_slug(p_slug text) RETURNS TABLE (tenant_id uuid, slug text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT t.id, t.slug FROM tenants t WHERE t.slug = lower(p_slug) AND t.status = 'active'
$$""",
    # The functions run as their owner (the migrator), and FORCE RLS binds the owner too: it may
    # read verified domains of every tenant, only through these functions (it has no login in
    # the API process).
    (
        f"CREATE POLICY tenant_domains_resolve ON tenant_domains FOR SELECT TO {MIGRATOR_ROLE} "
        "USING (status = 'verified' AND deleted_at IS NULL)"
    ),
    "REVOKE ALL ON FUNCTION sx_tenant_for_host(text) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION sx_tenant_for_slug(text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION sx_tenant_for_host(text) TO supportx_app",
    "GRANT EXECUTE ON FUNCTION sx_tenant_for_slug(text) TO supportx_app",
)


def _common() -> list[sa.Column[Any]]:
    return [
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
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "tenant_branding",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("primary_colour", sa.String(), nullable=True),
        sa.Column("gradient_start", sa.String(), nullable=True),
        sa.Column("gradient_end", sa.String(), nullable=True),
        sa.Column("product_name", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("portal_name", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("welcome_text", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("logo_file_id", sa.UUID(), nullable=True),
        sa.Column("logo_dark_file_id", sa.UUID(), nullable=True),
        sa.Column("icon_file_id", sa.UUID(), nullable=True),
        sa.Column("assets_version", sa.String(), nullable=True),
        *_common(),
        sa.CheckConstraint(
            f"primary_colour IS NULL OR primary_colour ~ {HEX}",
            name=op.f("ck_tenant_branding_primary_colour"),
        ),
        sa.CheckConstraint(
            "(gradient_start IS NULL) = (gradient_end IS NULL)",
            name=op.f("ck_tenant_branding_gradient_both_or_none"),
        ),
        sa.CheckConstraint(
            f"gradient_start IS NULL OR (gradient_start ~ {HEX} AND gradient_end ~ {HEX})",
            name=op.f("ck_tenant_branding_gradient_colours"),
        ),
        _tenant_fk("tenant_branding"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_branding")),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_branding_tenant_id"),
    )

    op.create_table(
        "branding_assets",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(content) <= 1048576", name=op.f("ck_branding_assets_content_size")
        ),
        _tenant_fk("branding_assets"),
        sa.PrimaryKeyConstraint("tenant_id", "name", name=op.f("pk_branding_assets")),
    )

    op.create_table(
        "tenant_domains",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("verify_token", sa.String(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("tls_mode", sa.String(), server_default="automatic", nullable=False),
        sa.Column("tls_status", sa.String(), server_default="waiting", nullable=False),
        sa.Column("certificate_pem", sa.String(), nullable=True),
        sa.Column("private_key", sa.LargeBinary(), nullable=True),
        sa.Column("private_key_key_id", sa.UUID(), nullable=True),
        sa.Column("certificate_not_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certificate_error", sa.String(), nullable=True),
        *_common(),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'failed')",
            name=op.f("ck_tenant_domains_status_code"),
        ),
        sa.CheckConstraint(
            "tls_mode IN ('automatic', 'uploaded')", name=op.f("ck_tenant_domains_tls_mode_code")
        ),
        sa.CheckConstraint(
            "tls_status IN ('waiting', 'pending', 'issued', 'failed', 'not_managed')",
            name=op.f("ck_tenant_domains_tls_status_code"),
        ),
        sa.CheckConstraint(
            "host = lower(host) AND length(host) BETWEEN 4 AND 253",
            name=op.f("ck_tenant_domains_host"),
        ),
        _tenant_fk("tenant_domains"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_domains")),
    )
    op.create_index(
        "uq_tenant_domains_host",
        "tenant_domains",
        ["host"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_tenant_domains_tenant_id_status", "tenant_domains", ["tenant_id", "status"])

    enable_tenant_rls("tenant_branding")
    grant_app("tenant_branding", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("tenant_branding")
    enable_tenant_rls("branding_assets")
    grant_app("branding_assets", ("SELECT", "INSERT", "UPDATE", "DELETE"))
    enable_tenant_rls("tenant_domains")
    grant_app("tenant_domains", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("tenant_domains")

    op.drop_constraint(op.f("ck_file_links_owner_type"), "file_links", type_="check")
    op.create_check_constraint(op.f("ck_file_links_owner_type"), "file_links", OWNER_TYPES_AFTER)

    for statement in FUNCTIONS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION sx_tenant_for_slug(text)")
    op.execute("DROP FUNCTION sx_tenant_for_host(text)")
    op.execute("DROP POLICY tenant_domains_resolve ON tenant_domains")
    op.drop_constraint(op.f("ck_file_links_owner_type"), "file_links", type_="check")
    op.create_check_constraint(op.f("ck_file_links_owner_type"), "file_links", OWNER_TYPES_BEFORE)
    for table in ("tenant_domains", "branding_assets", "tenant_branding"):
        op.drop_table(table)
