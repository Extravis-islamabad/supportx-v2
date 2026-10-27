"""People, sites, departments, groups and desks (WP-021; ADR-032; D-061, D-092).

- desks: every record belongs to one (REQ-ESM-002). Each tenant gets its IT desk here; the
  app also creates it on demand for tenants made later.
- sites: details, a default site per tenant, inactive (`disabled_at`).
- departments (new): name, code (unique per tenant), site, head, parent.
- support_groups: description, lead, own address and sender name, desk, inactive; group_sites:
  the sites a group serves.
- users: the person record (names, employee ID, phones, VIP, site, department, manager,
  sign-in, portal visibility override); `external_subject` NULL for people added by an admin or
  an import until their first sign-in; `email` optional (a contact may have none). People search covers the employee ID and phones.
- work_items: department and desk; work_item_templates: desk.
- access_settings (new): what the built-in technician role sees, asked at first run (D-073).
- people_imports (new): CSV and Excel imports of people, run in the background.

Existing rows: each tenant's oldest site becomes its default (or a "Main site" is added),
first names come from today's display names, and records, templates and groups go to the IT
desk. Reversible; a downgrade keeps people added without a subject by giving them a local one.

Revision ID: 0023
Revises: 0022
Created: 2026-10-27
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_USER_VECTOR = (
    "sx_search_vector(display_name, email || ' ' || translate(email, '@._-+', '     '))"
)
NEW_USER_VECTOR = (
    "sx_search_vector(display_name, coalesce(email, '') || ' '"
    " || translate(coalesce(email, ''), '@._-+', '     ')"
    " || ' ' || coalesce(employee_id, '') || ' ' || coalesce(phone, '')"
    " || ' ' || coalesce(mobile, ''))"
)

# One pass per tenant (business tables force RLS, even for the migrator): the IT desk, the
# default site, and every existing record, template and group on the IT desk.
BACKFILL = """
DO $$
DECLARE
    t uuid;
    d uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        d := gen_random_uuid();
        INSERT INTO desks (id, tenant_id, code, labels, is_default)
        VALUES (d, t, 'it', '{"en": "IT"}'::jsonb, true);
        UPDATE work_items SET desk_id = d WHERE tenant_id = t;
        UPDATE work_item_templates SET desk_id = d WHERE tenant_id = t;
        UPDATE support_groups SET desk_id = d WHERE tenant_id = t;
        UPDATE sites SET is_default = true
        WHERE id = (
            SELECT id FROM sites
            WHERE tenant_id = t AND deleted_at IS NULL
            ORDER BY created_at, id
            LIMIT 1
        );
        IF NOT FOUND THEN
            INSERT INTO sites (id, tenant_id, name, is_default)
            VALUES (gen_random_uuid(), t, 'Main site', true);
        END IF;
        UPDATE users SET first_name = left(btrim(display_name), 100) WHERE tenant_id = t;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""


def _entity_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
    ]


def _audit_columns() -> list[sa.Column[Any]]:
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


def _user_vector(expression: str) -> None:
    # A generated column's expression cannot change in place: drop and add it again.
    op.execute("DROP INDEX ix_users_search_vector")
    op.execute("ALTER TABLE users DROP COLUMN search_vector")
    op.execute(
        "ALTER TABLE users ADD COLUMN search_vector tsvector"
        f" GENERATED ALWAYS AS ({expression}) STORED"
    )
    op.execute("CREATE INDEX ix_users_search_vector ON users USING gin (search_vector)")


def upgrade() -> None:  # noqa: PLR0915 - one migration, many columns
    # --- desks ------------------------------------------------------------------------------------
    op.create_table(
        "desks",
        *_entity_columns(),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,39}$'", name=op.f("ck_desks_code_format")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_desks_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_desks")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_desks_tenant_id_id"),
    )
    op.create_index(
        "uq_desks_tenant_code",
        "desks",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_desks_tenant_default",
        "desks",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
    )
    enable_tenant_rls("desks")
    grant_app("desks", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("desks")

    # --- sites ------------------------------------------------------------------------------------
    op.add_column("sites", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("sites", sa.Column("region", sa.String(length=100), nullable=True))
    op.add_column("sites", sa.Column("time_zone", sa.String(length=64), nullable=True))
    op.add_column("sites", sa.Column("default_language", sa.String(length=2), nullable=True))
    op.add_column("sites", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("sites", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("sites", sa.Column("email", sa.String(length=320), nullable=True))
    op.add_column(
        "sites", sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("sites", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_sites_default_language_code"),
        "sites",
        "default_language IS NULL OR default_language IN ('en', 'ar', 'ur')",
    )
    op.create_index(
        "uq_sites_tenant_default",
        "sites",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
    )

    # --- departments ------------------------------------------------------------------------------
    op.create_table(
        "departments",
        *_entity_columns(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("site_id", sa.UUID(), nullable=True),
        sa.Column("head_id", sa.UUID(), nullable=True),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f("ck_departments_name_length")
        ),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name=op.f("ck_departments_not_own_parent")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "head_id"], ["users.tenant_id", "users.id"], name="fk_departments_head"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_departments_parent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], name="fk_departments_site"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_departments_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_departments_tenant_id_id"),
    )
    op.create_index("ix_departments_tenant_site", "departments", ["tenant_id", "site_id"])
    op.create_index(
        "uq_departments_tenant_code",
        "departments",
        ["tenant_id", sa.literal_column("lower(code)")],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_departments_tenant_name",
        "departments",
        ["tenant_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("departments")
    grant_app("departments", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("departments")

    # --- support groups and the sites they serve --------------------------------------------------
    op.add_column("support_groups", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("support_groups", sa.Column("lead_id", sa.UUID(), nullable=True))
    op.add_column("support_groups", sa.Column("email", sa.String(length=320), nullable=True))
    op.add_column("support_groups", sa.Column("sender_name", sa.String(length=200), nullable=True))
    op.add_column("support_groups", sa.Column("desk_id", sa.UUID(), nullable=True))
    op.add_column(
        "support_groups", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_support_groups_desk",
        "support_groups",
        "desks",
        ["tenant_id", "desk_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_support_groups_lead",
        "support_groups",
        "users",
        ["tenant_id", "lead_id"],
        ["tenant_id", "id"],
    )
    op.create_table(
        "group_sites",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            name="fk_group_sites_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            name="fk_group_sites_site",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_group_sites_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "group_id", "site_id", name=op.f("pk_group_sites")),
    )
    op.create_index("ix_group_sites_tenant_site", "group_sites", ["tenant_id", "site_id"])
    enable_tenant_rls("group_sites")
    grant_app("group_sites", ("SELECT", "INSERT", "DELETE"))

    # --- the person record ------------------------------------------------------------------------
    op.add_column("users", sa.Column("first_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=100), nullable=True))
    op.add_column(
        "users", sa.Column("name_custom", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("users", sa.Column("employee_id", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("job_title", sa.String(length=200), nullable=True))
    op.add_column("users", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("mobile", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("vip", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("users", sa.Column("site_id", sa.UUID(), nullable=True))
    op.add_column("users", sa.Column("department_id", sa.UUID(), nullable=True))
    op.add_column("users", sa.Column("manager_id", sa.UUID(), nullable=True))
    op.add_column(
        "users", sa.Column("can_sign_in", sa.Boolean(), server_default="true", nullable=False)
    )
    op.add_column("users", sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("request_visibility", sa.String(length=20), nullable=True))
    op.alter_column("users", "external_subject", existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column("users", "email", existing_type=sa.VARCHAR(), nullable=True)
    op.create_check_constraint(
        op.f("ck_users_first_name_length"), "users", "length(btrim(first_name)) BETWEEN 1 AND 100"
    )
    op.create_check_constraint(
        op.f("ck_users_not_own_manager"), "users", "manager_id IS NULL OR manager_id <> id"
    )
    op.create_check_constraint(
        op.f("ck_users_request_visibility_code"),
        "users",
        "request_visibility IS NULL OR request_visibility IN ('site')",
    )
    op.create_index("ix_users_tenant_manager", "users", ["tenant_id", "manager_id"])
    op.create_index(
        "uq_users_tenant_employee_id",
        "users",
        ["tenant_id", "employee_id"],
        unique=True,
        postgresql_where=sa.text("employee_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_users_manager", "users", "users", ["tenant_id", "manager_id"], ["tenant_id", "id"]
    )
    op.create_foreign_key(
        "fk_users_department",
        "users",
        "departments",
        ["tenant_id", "department_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_users_site", "users", "sites", ["tenant_id", "site_id"], ["tenant_id", "id"]
    )
    _user_vector(NEW_USER_VECTOR)

    # --- access settings (D-073) and people imports ---------------------------------------------
    op.create_table(
        "access_settings",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("technician_scope", sa.String(length=20), server_default="group", nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        *[c for c in _audit_columns() if c.name != "deleted_at"],
        sa.CheckConstraint(
            "technician_scope IN ('group', 'all')",
            name=op.f("ck_access_settings_technician_scope_code"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_access_settings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_access_settings")),
    )
    enable_tenant_rls("access_settings")
    grant_app("access_settings", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("access_settings")
    op.create_table(
        "people_imports",
        *_entity_columns(),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_format", sa.String(length=10), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("match_on", sa.String(length=20), server_default="email", nullable=False),
        sa.Column("total", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("processed", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "problems", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("failure", sa.String(length=50), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name=op.f("ck_people_imports_status_code"),
        ),
        sa.CheckConstraint(
            "file_format IN ('csv', 'xlsx')", name=op.f("ck_people_imports_file_format_code")
        ),
        sa.CheckConstraint(
            "match_on IN ('email', 'employee_id')", name=op.f("ck_people_imports_match_on_code")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_people_imports_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_people_imports")),
    )
    op.create_index("ix_people_imports_tenant_status", "people_imports", ["tenant_id", "status"])
    op.create_index(
        "ix_people_imports_tenant_created", "people_imports", ["tenant_id", "created_at", "id"]
    )
    enable_tenant_rls("people_imports")
    grant_app("people_imports", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("people_imports")

    # --- records and templates --------------------------------------------------------------------
    op.add_column("work_item_templates", sa.Column("desk_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_wit_desk", "work_item_templates", "desks", ["tenant_id", "desk_id"], ["tenant_id", "id"]
    )
    op.add_column("work_items", sa.Column("department_id", sa.UUID(), nullable=True))
    op.add_column("work_items", sa.Column("desk_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_wi_desk", "work_items", "desks", ["tenant_id", "desk_id"], ["tenant_id", "id"]
    )
    op.create_foreign_key(
        "fk_wi_department",
        "work_items",
        "departments",
        ["tenant_id", "department_id"],
        ["tenant_id", "id"],
    )

    # --- existing rows, then the columns that must always be set ---------------------------------
    op.execute(BACKFILL)
    for table in ("work_items", "work_item_templates", "support_groups"):
        op.alter_column(table, "desk_id", existing_type=sa.UUID(), nullable=False)
    op.alter_column("users", "first_name", existing_type=sa.String(length=100), nullable=False)


def downgrade() -> None:
    # People added without an identity-provider subject keep a local one (no data is dropped).
    op.execute(
        "UPDATE users SET external_subject = 'local:' || id::text WHERE external_subject IS NULL"
    )
    op.drop_constraint("fk_wi_department", "work_items", type_="foreignkey")
    op.drop_constraint("fk_wi_desk", "work_items", type_="foreignkey")
    op.drop_column("work_items", "desk_id")
    op.drop_column("work_items", "department_id")
    op.drop_constraint("fk_wit_desk", "work_item_templates", type_="foreignkey")
    op.drop_column("work_item_templates", "desk_id")
    _user_vector(OLD_USER_VECTOR)
    op.drop_constraint("fk_users_site", "users", type_="foreignkey")
    op.drop_constraint("fk_users_department", "users", type_="foreignkey")
    op.drop_constraint("fk_users_manager", "users", type_="foreignkey")
    op.drop_index(
        "uq_users_tenant_employee_id",
        table_name="users",
        postgresql_where=sa.text("employee_id IS NOT NULL"),
    )
    op.drop_index("ix_users_tenant_manager", table_name="users")
    op.drop_constraint(op.f("ck_users_request_visibility_code"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_not_own_manager"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_first_name_length"), "users", type_="check")
    op.alter_column("users", "external_subject", existing_type=sa.VARCHAR(), nullable=False)
    op.execute("UPDATE users SET email = 'contact-' || id::text || '@invalid' WHERE email IS NULL")
    op.alter_column("users", "email", existing_type=sa.VARCHAR(), nullable=False)
    for column in (
        "request_visibility",
        "invited_at",
        "can_sign_in",
        "manager_id",
        "department_id",
        "site_id",
        "vip",
        "mobile",
        "phone",
        "description",
        "job_title",
        "employee_id",
        "name_custom",
        "last_name",
        "first_name",
    ):
        op.drop_column("users", column)
    op.drop_index("ix_people_imports_tenant_created", table_name="people_imports")
    op.drop_index("ix_people_imports_tenant_status", table_name="people_imports")
    op.drop_table("people_imports")
    op.drop_table("access_settings")
    op.drop_index("ix_group_sites_tenant_site", table_name="group_sites")
    op.drop_table("group_sites")
    op.drop_constraint("fk_support_groups_lead", "support_groups", type_="foreignkey")
    op.drop_constraint("fk_support_groups_desk", "support_groups", type_="foreignkey")
    for column in ("disabled_at", "desk_id", "sender_name", "email", "lead_id", "description"):
        op.drop_column("support_groups", column)
    op.drop_index("uq_departments_tenant_name", table_name="departments")
    op.drop_index("uq_departments_tenant_code", table_name="departments")
    op.drop_index("ix_departments_tenant_site", table_name="departments")
    op.drop_table("departments")
    op.drop_index("uq_sites_tenant_default", table_name="sites")
    op.drop_constraint(op.f("ck_sites_default_language_code"), "sites", type_="check")
    for column in (
        "disabled_at",
        "is_default",
        "email",
        "phone",
        "address",
        "default_language",
        "time_zone",
        "region",
        "description",
    ):
        op.drop_column("sites", column)
    op.drop_index("uq_desks_tenant_default", table_name="desks")
    op.drop_index("uq_desks_tenant_code", table_name="desks")
    op.drop_table("desks")
