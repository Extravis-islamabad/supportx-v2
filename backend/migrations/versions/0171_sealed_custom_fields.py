"""Sensitive custom fields sealed at rest: the blind index and the seal state (WP-057 S3b-2, 0171).

SEC-040, ADR-050 addendum §S3b-2. A custom field marked `sensitive` keeps its values sealed
(`sx2:` text, the tenant's data keys) in `work_items.custom`. Two things are added:

- `work_item_field_index`: one row per record and sensitive field, holding the data key the
  digest was made under and a keyed digest of the value (HMAC-SHA256 under an HKDF key of that
  data key; never the value). It answers exact-match list filters (`eq`, `in`) on a sealed field.
  Equal values give equal digests: someone who can read the table sees which records share a
  value, never the value. Derived data: the app writes and rebuilds it (full grants), tenant
  table with RLS forced, every index tenant first.
- `custom_fields.seal_state` and `seal_cursor`: where a field's stored values stand while the
  re-seal job (S3b-2b) follows a change of `sensitive` (`plain`, `sealing`, `sealed`,
  `opening`). Filters on a field in between are refused, never half answered.

Expand only, no data step. The downgrade refuses while any tenant has an index row or a field
that is not plain (rule 5h): undoing it would leave sealed values nobody can filter.

Revision ID: 0171
Revises: 0169
Created: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0171"
down_revision: str | None = "0169"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_field_index"
FIELDS = "custom_fields"
SEAL_STATES = ("plain", "sealing", "sealed", "opening")


def upgrade() -> None:
    """The index table and the fields' seal state."""
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("field_key", sa.String(64), nullable=False),
        sa.Column("key_id", sa.Uuid(), nullable=False),  # the data key the digest was made under
        sa.Column("digest", sa.String(64), nullable=False),
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
        sa.CheckConstraint("digest ~ '^[0-9a-f]{64}$'", name=op.f(f"ck_{TABLE}_digest_form")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_work_item_field_index_record",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f(f"pk_{TABLE}")),
        sa.UniqueConstraint(
            "tenant_id", "work_item_id", "field_key", name="uq_work_item_field_index_place"
        ),
    )
    op.create_index("ix_work_item_field_index_lookup", TABLE, ["tenant_id", "field_key", "digest"])
    enable_tenant_rls(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE", "DELETE"))  # derived: rebuilt by the app
    op.add_column(
        FIELDS,
        sa.Column("seal_state", sa.String(10), server_default="plain", nullable=False),
    )
    op.add_column(FIELDS, sa.Column("seal_cursor", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        "ck_custom_fields_seal_state_code",
        FIELDS,
        "seal_state IN (" + ", ".join(f"'{s}'" for s in SEAL_STATES) + ")",
    )


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has sealed-field index rows (rule 5h)', t;
        END IF;
        IF EXISTS (SELECT 1 FROM {FIELDS} WHERE seal_state <> 'plain') THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has sealed custom fields (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed names, no input


def downgrade() -> None:
    """Drops it all only while no tenant has an index row or a sealed field."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_constraint("ck_custom_fields_seal_state_code", FIELDS, type_="check")
    op.drop_column(FIELDS, "seal_cursor")
    op.drop_column(FIELDS, "seal_state")
    op.drop_table(TABLE)  # its indexes and policies go with it
