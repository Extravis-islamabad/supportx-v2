"""Shared life cycle versions (ADR-049; WP-046a S4, REQ-INC-049, REQ-CHG-030).

Expand, with one data step:
- `work_item_lifecycle_versions`: each life cycle's versions (draft, published, retired), for
  action-based and staged types alike. Tenant-scoped with RLS forced and actor audit.
- `work_item_transitions` (action-based types) gains `lifecycle_version` in its key, with a
  foreign key to its version, and what ADR-049 §4 (as amended) adds per version: `permission`
  and `required_fields`. Who may run a move, when it is offered and its after-actions stay
  WP-029's transition settings (automation), version-wide.
- The application role may DELETE from `work_item_transitions` (a draft's moves are replaced
  and a discarded draft's removed; the service touches only drafts).
- Data step, once per tenant with `app.tenant_id` set (business tables force RLS): every life
  cycle the tenant has becomes version 1, published; staged transitions with no version get 1;
  records with no version get 1, in batches of 5,000 so no single statement holds a large
  table's locks for long.

The downgrade refuses while any tenant has a version other than 1, or a transition using the new
columns (rule 5h: an administrator's life cycle work is never thrown away). Otherwise it drops
the new columns and table; staged transitions and records keep their version 1, which ADR-041
already read as version 1.

Revision ID: 0152
Revises: 0149
Created: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0152"
down_revision: str | None = (
    "0149"  # main's head while building; re-pointed at its queue turn (after 0151)
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSIONS = "work_item_lifecycle_versions"
TRANSITIONS = "work_item_transitions"
TRANSITIONS_PK = "pk_work_item_transitions"
VERSION_FK = "fk_work_item_transitions_version"
TYPES = ("incident", "service_request", "problem", "change", "release")
BATCH = 5000

_DATA_STEP = f"""
DO $$
DECLARE t uuid; moved integer;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        INSERT INTO {VERSIONS} (tenant_id, type, lifecycle, number, state, published_at)
            SELECT DISTINCT tenant_id, type, lifecycle, 1, 'published', now()
            FROM {TRANSITIONS}
            ON CONFLICT DO NOTHING;
        INSERT INTO {VERSIONS} (tenant_id, type, lifecycle, number, state, published_at)
            SELECT DISTINCT tenant_id, type, 'standard', 1, 'published', now()
            FROM work_item_status_transitions
            ON CONFLICT DO NOTHING;
        UPDATE work_item_status_transitions SET lifecycle_version = 1
            WHERE lifecycle_version IS NULL;
        LOOP
            UPDATE work_items SET lifecycle_version = 1
                WHERE id IN (
                    SELECT id FROM work_items WHERE lifecycle_version IS NULL LIMIT {BATCH}
                );
            GET DIAGNOSTICS moved = ROW_COUNT;
            EXIT WHEN moved = 0;
        END LOOP;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input

_GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {VERSIONS} WHERE number <> 1 OR state <> 'published')
            OR EXISTS (SELECT 1 FROM {TRANSITIONS} WHERE lifecycle_version <> 1
                OR permission IS NOT NULL OR required_fields IS NOT NULL)
            OR EXISTS (SELECT 1 FROM work_items WHERE lifecycle_version <> 1)
            OR EXISTS (SELECT 1 FROM work_item_status_transitions WHERE lifecycle_version <> 1)
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has life cycle versions or transition rules (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def _create_versions() -> None:
    op.create_table(
        VERSIONS,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("lifecycle", sa.String(40), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column(
            "problems",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "type IN (" + ", ".join(f"'{t}'" for t in TYPES) + ")",
            name=op.f(f"ck_{VERSIONS}_type_code"),
        ),
        sa.CheckConstraint(
            "lifecycle ~ '^[a-z][a-z0-9_]{1,39}$'", name=op.f(f"ck_{VERSIONS}_lifecycle_format")
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'published', 'retired')", name=op.f(f"ck_{VERSIONS}_state_code")
        ),
        sa.CheckConstraint("number >= 1", name=op.f(f"ck_{VERSIONS}_number_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{VERSIONS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "type", "lifecycle", "number", name=op.f(f"pk_{VERSIONS}")
        ),
    )
    op.create_index(
        "uq_work_item_lifecycle_versions_one_draft",
        VERSIONS,
        ["tenant_id", "type", "lifecycle"],
        unique=True,
        postgresql_where=sa.text("state = 'draft'"),
    )
    enable_tenant_rls(VERSIONS)
    enable_actor_audit(VERSIONS)
    grant_app(VERSIONS)  # DELETE too: a draft may be discarded


def upgrade() -> None:
    """The versions table, the transitions' version, right and fields, version 1 everywhere."""
    _create_versions()
    op.add_column(
        TRANSITIONS,
        sa.Column("lifecycle_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.drop_constraint(op.f(TRANSITIONS_PK), TRANSITIONS, type_="primary")
    op.create_primary_key(
        op.f(TRANSITIONS_PK),
        TRANSITIONS,
        ["tenant_id", "type", "lifecycle", "lifecycle_version", "from_status", "action"],
    )
    op.add_column(TRANSITIONS, sa.Column("permission", sa.String(40), nullable=True))
    op.add_column(
        TRANSITIONS,
        sa.Column("required_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # A draft's moves are replaced as a whole and a discarded draft takes its moves with it; the
    # service deletes only a draft's rows (published versions never change, ADR-049 §2).
    grant_app(TRANSITIONS)
    op.execute(_DATA_STEP)
    # After the data step: every transition now has its version row.
    op.create_foreign_key(
        op.f(VERSION_FK),
        TRANSITIONS,
        VERSIONS,
        ["tenant_id", "type", "lifecycle", "lifecycle_version"],
        ["tenant_id", "type", "lifecycle", "number"],
    )


def downgrade() -> None:
    """Back to before (stops while any tenant has versions or rules beyond version 1)."""
    op.execute(_GUARD)
    op.drop_constraint(op.f(VERSION_FK), TRANSITIONS, type_="foreignkey")
    grant_app(TRANSITIONS, ("SELECT", "INSERT", "UPDATE"))  # no DELETE, as before
    op.drop_column(TRANSITIONS, "required_fields")
    op.drop_column(TRANSITIONS, "permission")
    op.drop_constraint(op.f(TRANSITIONS_PK), TRANSITIONS, type_="primary")
    op.create_primary_key(
        op.f(TRANSITIONS_PK),
        TRANSITIONS,
        ["tenant_id", "type", "lifecycle", "from_status", "action"],
    )
    op.drop_column(TRANSITIONS, "lifecycle_version")
    op.drop_index("uq_work_item_lifecycle_versions_one_draft", table_name=VERSIONS)
    op.drop_table(VERSIONS)
