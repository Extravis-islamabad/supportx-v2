"""Helpers for migration scripts (docs/architecture/tenancy.md).

Every tenant-scoped table, right after `op.create_table(...)`:

    enable_tenant_rls("tickets")
    grant_app("tickets")
"""

from collections.abc import Sequence

from alembic import op

from app.shared.db.rls import (
    APP_DML_PRIVILEGES,
    actor_audit_statements,
    app_grant_statements,
    definer_function_statements,
    drop_definer_function_statements,
    drop_policy_statements,
    drop_tenant_rls_statements,
    migrator_read_policy_statements,
    report_column_grant_statements,
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


def grant_report_columns(table: str, columns: Sequence[str]) -> None:
    """Let supportx_report read only `columns` of `table` (a table with free text in it)."""
    for statement in report_column_grant_statements(table, columns):
        op.execute(statement)


def revoke_report(table: str) -> None:
    """Reverse of `grant_report` (downgrades)."""
    for statement in report_revoke_statements(table):
        op.execute(statement)


def create_definer_function(  # noqa: PLR0913 - one function's parts, explicit
    name: str,
    arguments: str,
    returns: str,
    body: str,
    *,
    language: str = "sql",
    volatility: str = "STABLE",
) -> None:
    """A migrator-owned SECURITY DEFINER function, fixed search_path, EXECUTE for the app only.

    The one way a migration makes one (#476, D-168): the body is reviewed with the migration;
    everything that decides who may run it is here.
    """
    for statement in definer_function_statements(
        name, arguments, returns, body, language=language, volatility=volatility
    ):
        op.execute(statement)


def drop_definer_function(signature: str) -> None:
    """Reverse of `create_definer_function` (downgrades), e.g. `audit_erase_access(uuid)`."""
    for statement in drop_definer_function_statements(signature):
        op.execute(statement)


def allow_migrator_read(table: str, policy: str) -> None:
    """A SELECT policy for the migrator on `table` (for a cross-tenant count function only)."""
    for statement in migrator_read_policy_statements(table, policy):
        op.execute(statement)


def drop_policy(table: str, policy: str) -> None:
    """Reverse of `allow_migrator_read` (downgrades)."""
    for statement in drop_policy_statements(table, policy):
        op.execute(statement)
