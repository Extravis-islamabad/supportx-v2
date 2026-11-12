"""Reply and resolution templates (WP-046a S5a; REQ-INC-041, REQ-INC-042).

Expand, with one data step, on `work_item_reply_templates`:
- `kind`: `reply` (the composer's, as before) or `resolution` (the resolution editor's).
- `subject`: an optional subject line for a reply sent by e-mail.
- `bodies`: the text per language ({"en": ..., "ar": ...}); the requester's language is offered
  first. `body` stays for now (nullable) and goes in a later contract migration.
- `visibility`: `personal` (its owner's only, `owner_id`) or `shared` (the type's settings right
  to write; `group_ids` limits who is offered it, empty for everyone).
- `category_ids`: a resolution template for these categories is offered first for them.
- The unique name is per type, kind and owner (two people may each have a personal "Thanks").

Data step, once per tenant with `app.tenant_id` set (business tables force RLS): every existing
template becomes a shared reply whose text is stored under the tenant's default language (the
coordinator: an Arabic-first tenant's templates are probably Arabic), English when the tenant
has none set.

The downgrade refuses while any tenant has a resolution template, a personal one, or text in a
second language (rule 5h); otherwise it puts the default-language text back into `body`.

Revision ID: 0154
Revises: 0149
Created: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0154"
down_revision: str | None = "0149"  # main's head while building; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_reply_templates"
OLD_UNIQUE = "uq_wirt_tenant_type_name"
NEW_UNIQUE = "uq_wirt_tenant_type_kind_owner_name"

_DATA_STEP = f"""
DO $$
DECLARE t uuid; lang text;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        SELECT coalesce(
            (SELECT default_language FROM tenant_settings WHERE tenant_id = t), 'en'
        ) INTO lang;
        UPDATE {TABLE} SET bodies = jsonb_build_object(lang, body)
            WHERE tenant_id = t AND body IS NOT NULL AND bodies = '{{}}'::jsonb;
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
        IF EXISTS (
            SELECT 1 FROM {TABLE}
            WHERE tenant_id = t AND (kind <> 'reply' OR visibility <> 'shared'
               OR (SELECT count(*) FROM jsonb_object_keys(bodies)) > 1
               OR subject IS NOT NULL OR cardinality(group_ids) > 0
               OR cardinality(category_ids) > 0)
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has resolution, personal or translated templates (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input

# Back to one body: the only language each template still has.
_BACK = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE {TABLE} SET body = (SELECT value FROM jsonb_each_text(bodies) LIMIT 1)
            WHERE tenant_id = t AND body IS NULL;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def upgrade() -> None:
    """Kinds, subjects, languages, sharing and categories; existing text kept."""
    op.add_column(TABLE, sa.Column("kind", sa.String(10), server_default="reply", nullable=False))
    op.add_column(TABLE, sa.Column("subject", sa.String(200), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "bodies",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        TABLE,
        sa.Column("visibility", sa.String(10), server_default="shared", nullable=False),
    )
    op.add_column(TABLE, sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.add_column(
        TABLE,
        sa.Column("group_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
    )
    op.add_column(
        TABLE,
        sa.Column("category_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_kind_code"), TABLE, "kind IN ('reply', 'resolution')"
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_visibility_code"), TABLE, "visibility IN ('personal', 'shared')"
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_personal_has_owner"),
        TABLE,
        "visibility <> 'personal' OR owner_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_bodies_object"), TABLE, "jsonb_typeof(bodies) = 'object'"
    )
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_subject_length"),
        TABLE,
        "subject IS NULL OR length(btrim(subject)) BETWEEN 1 AND 200",
    )
    op.alter_column(TABLE, "body", existing_type=sa.Text(), nullable=True)
    op.drop_constraint(op.f(f"ck_{TABLE}_body_length"), TABLE, type_="check")
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_body_length"),
        TABLE,
        "body IS NULL OR char_length(body) BETWEEN 1 AND 100000",
    )
    op.execute(_DATA_STEP)
    op.drop_index(OLD_UNIQUE, table_name=TABLE)
    op.create_index(
        NEW_UNIQUE,
        TABLE,
        [
            "tenant_id",
            "type",
            "kind",
            sa.text("coalesce(owner_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            sa.text("lower(name)"),
        ],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Back to one shared reply text (stops while anything uses the new parts)."""
    op.execute(_GUARD)
    op.execute(_BACK)
    op.drop_index(NEW_UNIQUE, table_name=TABLE)
    op.create_index(
        OLD_UNIQUE,
        TABLE,
        ["tenant_id", "type", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint(op.f(f"ck_{TABLE}_body_length"), TABLE, type_="check")
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_body_length"), TABLE, "char_length(body) BETWEEN 1 AND 100000"
    )
    op.alter_column(TABLE, "body", existing_type=sa.Text(), nullable=False)
    for name in (
        "subject_length",
        "bodies_object",
        "personal_has_owner",
        "visibility_code",
        "kind_code",
    ):
        op.drop_constraint(op.f(f"ck_{TABLE}_{name}"), TABLE, type_="check")
    for column in (
        "category_ids",
        "group_ids",
        "owner_id",
        "visibility",
        "bodies",
        "subject",
        "kind",
    ):
        op.drop_column(TABLE, column)
