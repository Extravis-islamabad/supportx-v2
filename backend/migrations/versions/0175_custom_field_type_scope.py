"""Custom fields scoped to a type and its subtypes; CIs carry custom fields (lane B), 0175.

No second custom-field system (§6.6, the coordinator): configuration items take metadata custom
fields, and a field may belong to one type of a record kind and every type below it
(plans/metadata-type-subtree-design-lane-b.md, lane A's review).

- `custom_fields.scope_type_id uuid NULL`: NULL is the whole entity, as every field is today, so
  nothing existing changes. A value is a type of the owning module (CMDB CI types, asset product
  types); no foreign key, the type tables are another module's (rule 5e): the metadata service
  checks it through the module's type-tree port.
- A partial index (tenant first) for the scoped fields.
- `custom_fields.entity` also accepts `ci`. Widened from the check's live definition, as 0099
  does, so codes other lanes add are never dropped.

Expand only, no data step. The downgrade refuses per tenant (with `app.tenant_id` set, the table
forces RLS) while a field is scoped or a `ci` field exists, keeping the data (rule 5h).

Revision ID: 0175
Revises: 0176 (main's head at its queue turn, after #533)
Created: 2026-11-17
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0175"
down_revision: str | None = "0176"  # main's head at its queue turn (after #533)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE, COLUMN, CHECK = "custom_fields", "entity", "ck_custom_fields_entity_code"
ADDED = ("ci",)
INDEX = "ix_custom_fields_tenant_entity_scope"


def _codes_now() -> list[str]:
    """The codes the check allows now, in their order."""
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": CHECK},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CHECK), TABLE, f"{COLUMN} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"
    )


def upgrade() -> None:
    """The scope column, its index, and `ci` among the entities."""
    op.add_column(TABLE, sa.Column("scope_type_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f(INDEX),
        TABLE,
        ["tenant_id", "entity", "scope_type_id"],
        postgresql_where=sa.text("scope_type_id IS NOT NULL"),
    )
    now = _codes_now()
    _recheck([*now, *(c for c in ADDED if c not in now)])


def downgrade() -> None:
    """Refuse while a tenant has a scoped field or a `ci` field; else drop what was added."""
    conn = op.get_bind()
    tenants = conn.execute(sa.text("SELECT audit_tenant_ids()")).scalars().all()
    for tenant in tenants:
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        held = conn.execute(
            sa.text(
                "SELECT count(*) FROM custom_fields"
                " WHERE scope_type_id IS NOT NULL OR entity IN ('ci')"
            )
        ).scalar_one()
        if held:
            msg = (
                f"0175 downgrade refused: tenant {tenant} has {held} type-scoped or CI custom"
                " fields; they would be lost"
            )
            raise RuntimeError(msg)
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    _recheck([c for c in _codes_now() if c not in ADDED])
    op.drop_index(op.f(INDEX), table_name=TABLE)
    op.drop_column(TABLE, "scope_type_id")
