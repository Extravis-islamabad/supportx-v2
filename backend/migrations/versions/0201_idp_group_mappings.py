"""Roles and support groups from identity provider and directory groups (WP-057 S5c-1a).

REQ-SEC-014; lane B blocks it, with conditions in ~/Extravis/plans/wp-057-s5c-plan.md.

- **idp_group_mappings** (RLS, soft delete, versioned): a source maps an external group ID onto
  a SupportX role **or** a support group.
  - The source is a directory connector, or an SSO set-up (`sso`, applied from S5c-1b).
  - No foreign key to the source or to the support group: those belong to other modules (rule
    e), so the service checks them through their public interfaces. The role is this module's,
    so it gets a same-tenant key.
- **access_sources** (RLS): which mapping holds which person's role or group. PK (tenant, user,
  target kind, target, mapping). A mapped row goes when its last source does.
- **`managed`** on user_roles and group_members: the row was made by a mapping. Hand-made rows
  are never removed by one, and a managed row can't be removed by hand (409).
- **The data step**, per tenant with app.tenant_id set (business tables force RLS; CLAUDE.md
  §6):
  1. each directory connector's `group_mappings` JSON becomes table rows. The JSON stays in place
     (expand/contract; nothing reads it after this);
  2. a `group_members` row that the connector's own service identity made (`created_by`), in a
     group mapped from a directory group the person is in (`directory_memberships`), becomes
     managed, with its source. This keeps today's "sync removes what sync made", and stops sync
     removing hand-made memberships (the bug this fixes).
- **The downgrade** (lane B's condition 5) rebuilds each connector's JSON from the table. It
  refuses, per tenant, while a mapping exists that the JSON can't hold: a role target, or an SSO
  source.

Revision ID: 0201
Revises: 0199
Created: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0201"
down_revision: str | None = "0199"  # main's head when written; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAPPINGS = "idp_group_mappings"
SOURCES = "access_sources"
SOURCE_KINDS = "('directory', 'sso')"
TARGET_KINDS = "('role', 'group')"
CONNECTOR_KIND = "directory"  # integrations' connector identity kind for directory connectors

BACKFILL = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        INSERT INTO {MAPPINGS} (id, tenant_id, source_kind, source_id, external_group_id,
                                external_name, group_id)
        SELECT gen_random_uuid(), c.tenant_id, 'directory', c.id, m->>'external_id',
               NULLIF(m->>'name', ''), (m->>'group_id')::uuid
        FROM directory_connectors c, jsonb_array_elements(c.group_mappings) AS m
        WHERE jsonb_typeof(c.group_mappings) = 'array'
          AND m ? 'external_id' AND m ? 'group_id'
          AND (m->>'group_id') ~ '^[0-9a-fA-F-]{{36}}$'
        ON CONFLICT DO NOTHING;
        -- Memberships the connector's own identity made, in a group mapped from a directory
        -- group the person is in: managed, held by that mapping.
        INSERT INTO {SOURCES} (tenant_id, user_id, target_kind, target_id, mapping_id)
        SELECT DISTINCT gm.tenant_id, gm.user_id, 'group', gm.group_id, map.id
        FROM group_members gm
        JOIN connector_identities ci
          ON ci.tenant_id = gm.tenant_id AND ci.user_id = gm.created_by
         AND ci.kind = '{CONNECTOR_KIND}'
        JOIN {MAPPINGS} map
          ON map.tenant_id = gm.tenant_id AND map.source_kind = 'directory'
         AND map.source_id = ci.instance_id AND map.group_id = gm.group_id
         AND map.deleted_at IS NULL
        JOIN directory_people dp
          ON dp.tenant_id = gm.tenant_id AND dp.connector_id = ci.instance_id
         AND dp.user_id = gm.user_id
        JOIN directory_memberships dm
          ON dm.tenant_id = gm.tenant_id AND dm.connector_id = ci.instance_id
         AND dm.external_id = dp.external_id AND dm.group_external_id = map.external_group_id
        ON CONFLICT DO NOTHING;
        UPDATE group_members gm SET managed = true
        WHERE EXISTS (
            SELECT 1 FROM {SOURCES} s
            WHERE s.tenant_id = gm.tenant_id AND s.user_id = gm.user_id
              AND s.target_kind = 'group' AND s.target_id = gm.group_id
        );
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input

REBUILD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {MAPPINGS}
                   WHERE deleted_at IS NULL AND (role_id IS NOT NULL OR source_kind = 'sso')) THEN
            RAISE EXCEPTION
                'downgrade refused: tenant % has role or SSO group mappings (rule 5h)', t;
        END IF;
        UPDATE directory_connectors c SET group_mappings = COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                       'external_id', m.external_group_id,
                       'name', COALESCE(m.external_name, ''),
                       'group_id', m.group_id::text) ORDER BY m.created_at, m.id)
            FROM {MAPPINGS} m
            WHERE m.tenant_id = c.tenant_id AND m.source_kind = 'directory'
              AND m.source_id = c.id AND m.deleted_at IS NULL AND m.enabled
        ), '[]'::jsonb);
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def upgrade() -> None:
    """The two tables, the `managed` flags, then the per-tenant data step."""
    op.create_table(
        MAPPINGS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_group_id", sa.String(length=256), nullable=False),
        sa.Column("external_name", sa.String(length=256), nullable=True),
        sa.Column("role_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{MAPPINGS}")),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{MAPPINGS}_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f(f"fk_{MAPPINGS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"],
            name=f"fk_{MAPPINGS}_role", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"source_kind IN {SOURCE_KINDS}", name=op.f(f"ck_{MAPPINGS}_source_kind")
        ),
        sa.CheckConstraint(
            "(role_id IS NULL) <> (group_id IS NULL)", name=op.f(f"ck_{MAPPINGS}_one_target")
        ),
        sa.CheckConstraint(
            "length(external_group_id) BETWEEN 1 AND 256", name=op.f(f"ck_{MAPPINGS}_external")
        ),
    )  # fmt: skip
    # One live mapping per (source, external group, target): one index per target kind.
    for target in ("role_id", "group_id"):
        op.create_index(
            f"uq_{MAPPINGS}_{target}",
            MAPPINGS,
            ["tenant_id", "source_kind", "source_id", "external_group_id", target],
            unique=True,
            postgresql_where=sa.text(f"deleted_at IS NULL AND {target} IS NOT NULL"),
        )
    op.create_index(
        f"ix_{MAPPINGS}_tenant_source", MAPPINGS, ["tenant_id", "source_kind", "source_id"]
    )
    enable_tenant_rls(MAPPINGS)
    enable_actor_audit(MAPPINGS)
    grant_app(MAPPINGS, ("SELECT", "INSERT", "UPDATE"))  # soft delete only

    op.create_table(
        SOURCES,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", sa.String(length=8), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("mapping_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "user_id", "target_kind", "target_id", "mapping_id",
            name=op.f(f"pk_{SOURCES}"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f(f"fk_{SOURCES}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
            name=f"fk_{SOURCES}_user", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "mapping_id"], [f"{MAPPINGS}.tenant_id", f"{MAPPINGS}.id"],
            name=f"fk_{SOURCES}_mapping", ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            f"target_kind IN {TARGET_KINDS}", name=op.f(f"ck_{SOURCES}_target_kind")
        ),
    )  # fmt: skip
    op.create_index(f"ix_{SOURCES}_tenant_mapping", SOURCES, ["tenant_id", "mapping_id"])
    op.create_index(
        f"ix_{SOURCES}_tenant_target", SOURCES, ["tenant_id", "target_kind", "target_id"]
    )
    enable_tenant_rls(SOURCES)
    grant_app(SOURCES, ("SELECT", "INSERT", "DELETE"))

    for table in ("user_roles", "group_members"):
        op.add_column(
            table,
            sa.Column("managed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        )
    # The tenant's opt-in: a mapping may give tenant admin or another never_via_idp right (lane
    # B's condition 4; off by default, turned on with a recent sign-in, audited).
    op.add_column(
        "access_settings",
        sa.Column(
            "mappings_may_grant_privileged",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "access_settings",
        sa.Column("mappings_privileged_set_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "access_settings", sa.Column("mappings_privileged_set_by", sa.Uuid(), nullable=True)
    )
    op.execute(BACKFILL)


def downgrade() -> None:
    """Back to before: the JSON rebuilt from the table (refused while it can't hold them)."""
    op.execute(REBUILD)
    for column in (
        "mappings_privileged_set_by",
        "mappings_privileged_set_at",
        "mappings_may_grant_privileged",
    ):
        op.drop_column("access_settings", column)
    for table in ("group_members", "user_roles"):
        op.drop_column(table, "managed")
    op.drop_table(SOURCES)
    op.drop_table(MAPPINGS)
