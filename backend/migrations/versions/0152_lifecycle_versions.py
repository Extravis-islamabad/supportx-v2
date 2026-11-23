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
- For S4b, so it needs no migration: the bulk job action check also allows `migrate_version`
  (moving records to a newer version, §7) and the field history source check `migration`. The
  code that uses them ships with S4b.
- Two triggers keep published versions as they are, whatever the code does (lane B): a
  transition row is written only while its version is a draft (on a published one only the
  version-wide reason prompt may change), and a version goes draft → published → retired only,
  removed only as a draft.
- Data step, once per tenant with `app.tenant_id` set (business tables force RLS): every life
  cycle the tenant has becomes version 1, published; staged transitions with no version get 1;
  records with no version get 1, in batches of 5,000 so no single statement holds a large
  table's locks for long.

The downgrade refuses while any tenant has a version other than 1, or a transition using the new
columns (rule 5h: an administrator's life cycle work is never thrown away). Otherwise it drops
the new columns and table; staged transitions and records keep their version 1, which ADR-041
already read as version 1.

Revision ID: 0152
Revises: 0151
Created: 2026-11-12
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0152"
down_revision: str | None = "0151"  # main's head at its queue turn (after #455's 0151)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSIONS = "work_item_lifecycle_versions"
TRANSITIONS = "work_item_transitions"
TRANSITIONS_PK = "pk_work_item_transitions"
VERSION_FK = "fk_work_item_transitions_version"
TYPES = ("incident", "service_request", "problem", "change", "release")
BATCH = 5000
# For S4b (§7): the checks are widened here so that work needs no migration of its own.
WIDENED = (
    ("work_item_bulk_jobs", "ck_work_item_bulk_jobs_action_code", "action", "migrate_version"),
    ("field_changes", "ck_field_changes_source_code", "source", "migration"),
)

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
            OR EXISTS (SELECT 1 FROM work_item_bulk_jobs WHERE action = 'migrate_version')
            OR EXISTS (SELECT 1 FROM field_changes WHERE source = 'migration')
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has life cycle versions or transition rules (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


# Published versions never change, enforced by the database, not only the service (lane B's
# #454 review). A transition row may be written only while its version is a draft; on a
# published or retired version only the reason prompt (a version-wide setting, ADR-049
# Amendment 1) may change. Created after the data step, which writes no transition rows.
_TRANSITIONS_GUARD = (
    f"""
CREATE FUNCTION work_item_transitions_versioned() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    row_now {TRANSITIONS}%ROWTYPE;
    state_now text;
    state_before text;
BEGIN
    IF TG_OP = 'DELETE' THEN row_now := OLD; ELSE row_now := NEW; END IF;
    SELECT state INTO state_now FROM {VERSIONS} v
        WHERE v.tenant_id = row_now.tenant_id AND v.type = row_now.type
          AND v.lifecycle = row_now.lifecycle AND v.number = row_now.lifecycle_version;
    IF TG_OP = 'UPDATE' THEN
        SELECT state INTO state_before FROM {VERSIONS} v
            WHERE v.tenant_id = OLD.tenant_id AND v.type = OLD.type
              AND v.lifecycle = OLD.lifecycle AND v.number = OLD.lifecycle_version;
        IF state_now = 'draft' AND state_before = 'draft' THEN
            RETURN NEW;
        END IF;
        IF (NEW.tenant_id, NEW.type, NEW.lifecycle, NEW.lifecycle_version, NEW.from_status,
            NEW.action, NEW.to_status, NEW.permission, NEW.required_fields)
           IS NOT DISTINCT FROM
           (OLD.tenant_id, OLD.type, OLD.lifecycle, OLD.lifecycle_version, OLD.from_status,
            OLD.action, OLD.to_status, OLD.permission, OLD.required_fields) THEN
            RETURN NEW;  -- the reason prompt only
        END IF;
    ELSIF state_now = 'draft' THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'life cycle version % of % (%) is %: its moves never change',
        row_now.lifecycle_version, row_now.type, row_now.lifecycle, coalesce(state_now, 'missing')
        USING ERRCODE = 'check_violation';
END $$
""",  # noqa: S608 - fixed table names, no input
    f"""
CREATE TRIGGER work_item_transitions_versioned
    BEFORE INSERT OR UPDATE OR DELETE ON {TRANSITIONS}
    FOR EACH ROW EXECUTE FUNCTION work_item_transitions_versioned()
""",
    """
CREATE FUNCTION work_item_lifecycle_versions_states() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.state = 'draft' THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'only a draft life cycle version may be removed'
            USING ERRCODE = 'check_violation';
    END IF;
    IF (NEW.tenant_id, NEW.type, NEW.lifecycle, NEW.number)
       IS DISTINCT FROM (OLD.tenant_id, OLD.type, OLD.lifecycle, OLD.number) THEN
        RAISE EXCEPTION 'a life cycle version keeps its type, life cycle and number'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.state = NEW.state AND OLD.state = 'draft' THEN RETURN NEW; END IF;
    IF OLD.state = 'draft' AND NEW.state = 'published' THEN RETURN NEW; END IF;
    IF OLD.state = 'published' AND NEW.state = 'retired'
       AND (NEW.published_at, NEW.published_by) IS NOT DISTINCT FROM
           (OLD.published_at, OLD.published_by) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'a life cycle version goes draft -> published -> retired only (% -> %)',
        OLD.state, NEW.state USING ERRCODE = 'check_violation';
END $$
""",
    f"""
CREATE TRIGGER work_item_lifecycle_versions_states
    BEFORE UPDATE OR DELETE ON {VERSIONS}
    FOR EACH ROW EXECUTE FUNCTION work_item_lifecycle_versions_states()
""",
)

_DROP_TRIGGERS = (
    f"DROP TRIGGER work_item_lifecycle_versions_states ON {VERSIONS}",
    "DROP FUNCTION work_item_lifecycle_versions_states()",
    f"DROP TRIGGER work_item_transitions_versioned ON {TRANSITIONS}",
    "DROP FUNCTION work_item_transitions_versioned()",
)


def _codes_now(check: str) -> list[str]:
    """The codes a check allows now, in their order (the 0092/0141/0149 pattern)."""
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": check},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _set_codes(table: str, check: str, column: str, codes: Sequence[str]) -> None:
    op.drop_constraint(op.f(check), table, type_="check")
    op.create_check_constraint(
        op.f(check), table, f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"
    )


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
    for table, check, column, added in WIDENED:
        now = _codes_now(check)
        if added not in now:
            _set_codes(table, check, column, [*now, added])
    op.execute(_DATA_STEP)
    # After the data step: every transition now has its version row.
    op.create_foreign_key(
        op.f(VERSION_FK),
        TRANSITIONS,
        VERSIONS,
        ["tenant_id", "type", "lifecycle", "lifecycle_version"],
        ["tenant_id", "type", "lifecycle", "number"],
    )
    for statement in _TRANSITIONS_GUARD:
        op.execute(statement)


def downgrade() -> None:
    """Back to before (stops while any tenant has versions or rules beyond version 1)."""
    op.execute(_GUARD)
    for statement in _DROP_TRIGGERS:
        op.execute(statement)
    op.drop_constraint(op.f(VERSION_FK), TRANSITIONS, type_="foreignkey")
    grant_app(TRANSITIONS, ("SELECT", "INSERT", "UPDATE"))  # no DELETE, as before
    for table, check, column, added in WIDENED:
        _set_codes(table, check, column, [c for c in _codes_now(check) if c != added])
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
