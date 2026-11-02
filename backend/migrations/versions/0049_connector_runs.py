"""Connector runs, errors and health; mailbox notices and set-up rights move to the connectors.

WP-040 session 1, expand only (D-113):
- connector_health, connector_runs, connector_errors (RLS, FORCE): any connector kind's
  standing, its runs with counts (kept 7 days) and its error list (kept 90 days).
- Data, per tenant under FORCE RLS: a tenant's saved rule for `mailbox.failing` is copied to
  `connector.failing` (its people become the connector's admins), so an admin's choice (switched
  off, other channels, extra people) carries over. `mailbox.failing` stays a known event, and
  its rule stays, until the contract step. The downgrade removes only the copies it made
  (`connector.*` rules), never a mailbox rule.
- Data, per tenant: every role holding `mailboxes.manage` also gets `integrations.manage_email`
  at the same scope (REQ-INT-013: set-up rights per connector category). The old key stays and
  is still accepted until the contract step; the downgrade removes the copies.

Revision ID: 0049
Revises: 0045 (lane A's 0047 and lane C's 0046 and 0048 come first at merge; down_revision is re-pointed when queued)
Created: 2026-11-02
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0049"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOOP_HEAD = """
DO $$
DECLARE
    t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
"""
_LOOP_TAIL = """
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""


def _per_tenant(statement: str) -> str:
    """Fixed statements (written in this file) for each tenant, under FORCE RLS."""
    return _LOOP_HEAD + statement + _LOOP_TAIL


COPY_RULE = _per_tenant(
    """
        INSERT INTO notification_rules
            (id, tenant_id, event_code, enabled, recipients, channels, user_ids, group_ids,
             conditions, notify_actor)
        SELECT gen_random_uuid(), r.tenant_id, 'connector.failing', r.enabled,
               array_replace(r.recipients, 'mail_admins', 'connector_admins'), r.channels,
               r.user_ids, r.group_ids, '[]'::jsonb, r.notify_actor
          FROM notification_rules r
         WHERE r.tenant_id = t AND r.event_code = 'mailbox.failing' AND r.deleted_at IS NULL
        ON CONFLICT (tenant_id, event_code) DO NOTHING;
"""
)
COPY_GRANT = _per_tenant(
    """
        INSERT INTO role_permissions (tenant_id, role_id, permission, scope, condition)
        SELECT p.tenant_id, p.role_id, 'integrations.manage_email', p.scope, p.condition
          FROM role_permissions p
         WHERE p.tenant_id = t AND p.permission = 'mailboxes.manage'
        ON CONFLICT DO NOTHING;
"""
)
DROP_GRANT_COPIES = _per_tenant(
    """
        DELETE FROM role_permissions n
         USING role_permissions o
         WHERE n.tenant_id = t AND o.tenant_id = t AND n.role_id = o.role_id
           AND n.permission = 'integrations.manage_email' AND o.permission = 'mailboxes.manage';
"""
)
DROP_COPIES = _per_tenant(
    "DELETE FROM notification_rules WHERE tenant_id = t"
    " AND event_code IN ('connector.failing', 'connector.recovered');"
)


def _timestamp(name: str, *, nullable: bool = False) -> "sa.Column[datetime]":
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "connector_health",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("failing", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        _timestamp("failing_since", nullable=True),
        _timestamp("last_success_at", nullable=True),
        _timestamp("last_error_at", nullable=True),
        sa.Column("last_error_code", sa.String(length=60), nullable=True),
        _timestamp("updated_at"),
        _tenant_fk("connector_health"),
        sa.PrimaryKeyConstraint(
            "tenant_id", "kind", "instance_id", name=op.f("pk_connector_health")
        ),
    )
    counts = [
        sa.Column(name, sa.Integer(), server_default="0", nullable=False)
        for name in ("read", "created", "updated", "skipped", "failed")
    ]
    op.create_table(
        "connector_runs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        _timestamp("started_at"),
        _timestamp("finished_at"),
        sa.Column("ok", sa.Boolean(), nullable=False),
        *counts,
        sa.Column("error_code", sa.String(length=60), nullable=True),
        _tenant_fk("connector_runs"),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_connector_runs")),
    )
    op.create_index(
        "ix_connector_runs_tenant_instance_finished",
        "connector_runs",
        ["tenant_id", "instance_id", "finished_at"],
    )
    op.create_index(
        "ix_connector_runs_tenant_finished", "connector_runs", ["tenant_id", "finished_at"]
    )
    op.create_table(
        "connector_errors",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        _timestamp("occurred_at"),
        sa.Column("code", sa.String(length=60), nullable=False),
        _tenant_fk("connector_errors"),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_connector_errors")),
    )
    op.create_index(
        "ix_connector_errors_tenant_instance_at",
        "connector_errors",
        ["tenant_id", "instance_id", "occurred_at"],
    )
    op.create_index(
        "ix_connector_errors_tenant_at", "connector_errors", ["tenant_id", "occurred_at"]
    )
    for table in ("connector_health", "connector_runs", "connector_errors"):
        enable_tenant_rls(table)
    grant_app("connector_health", ("SELECT", "INSERT", "UPDATE"))
    grant_app("connector_runs", ("SELECT", "INSERT", "DELETE"))
    grant_app("connector_errors", ("SELECT", "INSERT", "DELETE"))
    op.execute(COPY_RULE)
    op.execute(COPY_GRANT)


def downgrade() -> None:
    op.execute(DROP_GRANT_COPIES)
    op.execute(DROP_COPIES)
    op.drop_table("connector_errors")
    op.drop_table("connector_runs")
    op.drop_table("connector_health")
