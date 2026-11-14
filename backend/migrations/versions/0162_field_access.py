"""Field access per role (ADR-047; REQ-WI-016, REQ-ADM-026; WP-046a S7), 0162.

Expand only, no data step:
- `role_field_access` (RLS, audited actors): one role's rule for one field of one record type,
  read_only, masked or hidden; soft-deleted when removed, a live rule unique per role and field.
- `custom_fields.personal_data` and `.sensitive` (REQ-ADM-026 AC2; D-171): an admin's marks on
  a custom field. Marking creates no rule; erasure and export read them (lane B).
- `work_item_type_settings.custom_text_rebuilding_since`: set while the type's search text is
  rebuilt after a field gains its first rule or loses its last one; search then ignores custom
  text for that type for everyone (ADR-047 §6: fewer matches for a while, never a leak).

The downgrade refuses while any tenant has a rule, a marked field or a rebuild under way (rule
5h): they are admins' decisions about who sees what.

Revision ID: 0162
Revises: 0160 (main's head while building; re-pointed onto 0161 at its queue turn)
Created: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0162"
down_revision: str | None = "0160"  # main's head while building; onto 0161 at its turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "role_field_access"
FIELDS = "custom_fields"
SETTINGS = "work_item_type_settings"

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE})
           OR EXISTS (SELECT 1 FROM {FIELDS} WHERE personal_data OR sensitive)
           OR EXISTS (SELECT 1 FROM {SETTINGS} WHERE custom_text_rebuilding_since IS NOT NULL)
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % uses field access (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def upgrade() -> None:
    """The rules table, the custom field marks and the rebuild marker."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(40), nullable=False),
        sa.Column("field", sa.String(80), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "mode IN ('read_only', 'masked', 'hidden')", name=op.f(f"ck_{TABLE}_mode_code")
        ),
        sa.CheckConstraint(
            "record_type ~ '^[a-z][a-z_]{0,39}$'", name=op.f(f"ck_{TABLE}_record_type_format")
        ),
        sa.CheckConstraint(
            "char_length(field) BETWEEN 1 AND 80", name=op.f(f"ck_{TABLE}_field_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            ondelete="CASCADE",
            name="fk_role_field_access_role",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "uq_rfa_tenant_role_type_field",
        TABLE,
        ["tenant_id", "role_id", "record_type", "field"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_rfa_tenant_type_field", TABLE, ["tenant_id", "record_type", "field"])
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))
    op.add_column(
        FIELDS, sa.Column("personal_data", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(
        FIELDS, sa.Column("sensitive", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(
        SETTINGS,
        sa.Column("custom_text_rebuilding_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Back to before (stops while any tenant uses field access)."""
    op.execute(GUARD)
    op.drop_column(SETTINGS, "custom_text_rebuilding_since")
    op.drop_column(FIELDS, "sensitive")
    op.drop_column(FIELDS, "personal_data")
    op.drop_table(TABLE)
