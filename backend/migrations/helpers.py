"""Helpers for migration scripts (docs/architecture/tenancy.md).

Every tenant-scoped table, right after `op.create_table(...)`:

    enable_tenant_rls("tickets")
    grant_app("tickets")
"""

from alembic import op

from app.shared.db.rls import (
    APP_DML_PRIVILEGES,
    actor_audit_statements,
    app_grant_statements,
    drop_tenant_rls_statements,
    report_grant_statements,
    report_revoke_statements,
    tenant_rls_statements,
)


def enable_tenant_rls(table: str, column: str = "tenant_id") -> None:
    """ENABLE + FORCE RLS and create the SELECT/INSERT/UPDATE/DELETE tenant policies."""
    for statement in tenant_rls_statements(table, column):
        op.execute(statement)


def disable_tenant_rls(table: str) -> None:
    """Reverse of `enable_tenant_rls` (only for downgrades that keep the table)."""
    for statement in drop_tenant_rls_statements(table):
        op.execute(statement)


def enable_actor_audit(table: str) -> None:
    """Fill created_by/updated_by from the transaction's app.user_id (trigger from migration 0002).

    Works for every write path, including raw SQL; created_by can never be changed afterwards.
    """
    for statement in actor_audit_statements(table):
        op.execute(statement)


def grant_app(table: str, privileges: tuple[str, ...] = APP_DML_PRIVILEGES) -> None:
    """Give supportx_app exactly `privileges` on `table` (never TRUNCATE)."""
    for statement in app_grant_statements(table, privileges):
        op.execute(statement)


def grant_report(table: str) -> None:
    """Let supportx_report read `table` (WP-035, ADR-033): tables a reporting source reads."""
    for statement in report_grant_statements(table):
        op.execute(statement)


def revoke_report(table: str) -> None:
    """Reverse of `grant_report` (downgrades)."""
    for statement in report_revoke_statements(table):
        op.execute(statement)
