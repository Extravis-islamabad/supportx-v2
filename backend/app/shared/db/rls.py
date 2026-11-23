"""Row-level security SQL for tenant isolation (architecture.md §7.2; CLAUDE.md rule a).

Migrations call these through migrations/helpers.py. Each tenant table gets RLS ENABLED and
FORCED (so even the table owner is filtered) and four policies, one per command:

    SELECT  USING      tenant_id = <current tenant>
    INSERT  WITH CHECK tenant_id = <current tenant>
    UPDATE  USING + WITH CHECK (cannot see other rows, cannot move a row to another tenant)
    DELETE  USING

PostgreSQL only allows USING on SELECT/DELETE and only WITH CHECK on INSERT, so "both" applies to
UPDATE, the one command where both matter.

<current tenant> is `NULLIF(current_setting('app.tenant_id', true), '')::uuid`:
- `true` (missing_ok) gives NULL instead of an error when the setting was never defined;
- NULLIF handles a pooled connection where an earlier transaction set it: after that transaction
  ends the value reads as '' (not NULL), and `''::uuid` would raise instead of matching nothing.
NULL never equals anything, so without a tenant every policy is false: zero rows, writes rejected.
"""

import re
from collections.abc import Sequence

APP_ROLE = "supportx_app"
MIGRATOR_ROLE = "supportx_migrator"
RELAY_ROLE = "supportx_relay"  # outbox relay (WP-007, docs/architecture/events.md)
# Reporting (WP-035, ADR-033): NOLOGIN, SELECT only; supportx_app enters it with SET LOCAL ROLE.
REPORT_ROLE = "supportx_report"
TENANT_COLUMN = "tenant_id"
CURRENT_TENANT_SQL = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
APP_DML_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE")

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _check(identifier: str) -> str:
    if not _IDENTIFIER.fullmatch(identifier):
        msg = f"unsafe SQL identifier: {identifier!r}"
        raise ValueError(msg)
    return identifier


def tenant_rls_statements(table: str, column: str = TENANT_COLUMN) -> list[str]:
    """SQL that enables, forces and defines the four tenant policies on `table`."""
    t, c = _check(table), _check(column)
    match = f"{c} = {CURRENT_TENANT_SQL}"
    return [
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {t}_tenant_select ON {t} FOR SELECT USING ({match})",
        f"CREATE POLICY {t}_tenant_insert ON {t} FOR INSERT WITH CHECK ({match})",
        f"CREATE POLICY {t}_tenant_update ON {t} FOR UPDATE USING ({match}) WITH CHECK ({match})",
        f"CREATE POLICY {t}_tenant_delete ON {t} FOR DELETE USING ({match})",
    ]


def drop_tenant_rls_statements(table: str) -> list[str]:
    """Reverse of `tenant_rls_statements` (for downgrades that keep the table)."""
    t = _check(table)
    return [
        *(
            f"DROP POLICY IF EXISTS {t}_tenant_{op} ON {t}"
            for op in ("select", "insert", "update", "delete")
        ),
        f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY",
    ]


def app_grant_statements(table: str, privileges: tuple[str, ...] = APP_DML_PRIVILEGES) -> list[str]:
    """Give the application role exactly `privileges` on `table` and nothing else.

    Revoking first removes anything a default-privilege rule granted, notably never TRUNCATE
    (TRUNCATE ignores RLS).
    """
    t = _check(table)
    allowed = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    if not set(privileges) <= allowed:
        msg = f"only {sorted(allowed)} may be granted to {APP_ROLE}"
        raise ValueError(msg)
    statements = [f"REVOKE ALL ON {t} FROM {APP_ROLE}"]
    if privileges:
        statements.append(f"GRANT {', '.join(privileges)} ON {t} TO {APP_ROLE}")
    return statements


def report_grant_statements(table: str) -> list[str]:
    """Let the reporting role read `table` (SELECT only; RLS still filters by tenant)."""
    t = _check(table)
    return [f"REVOKE ALL ON {t} FROM {REPORT_ROLE}", f"GRANT SELECT ON {t} TO {REPORT_ROLE}"]


def report_column_grant_statements(table: str, columns: Sequence[str]) -> list[str]:
    """Let the reporting role read only `columns` of `table` (SELECT; RLS still filters).

    For a table that also holds free text or people's words (an approval's comment): the grant
    is the boundary, so a later report can never read a column nobody granted.
    """
    t = _check(table)
    if not columns:
        msg = "a column grant needs at least one column"
        raise ValueError(msg)
    listed = ", ".join(_check(c) for c in columns)
    return [
        f"REVOKE ALL ON {t} FROM {REPORT_ROLE}",
        f"GRANT SELECT ({listed}) ON {t} TO {REPORT_ROLE}",
    ]


def report_revoke_statements(table: str) -> list[str]:
    """Reverse of `report_grant_statements` (downgrades)."""
    return [f"REVOKE ALL ON {_check(table)} FROM {REPORT_ROLE}"]


# Trigger function (created once by migration 0002) that stamps the acting user from the
# transaction's app.user_id onto created_by/updated_by, and keeps created_by immutable.
ACTOR_AUDIT_FUNCTION = """
CREATE OR REPLACE FUNCTION supportx_stamp_actor() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    actor uuid := NULLIF(current_setting('app.user_id', true), '')::uuid;
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.created_by := COALESCE(actor, NEW.created_by);
        NEW.updated_by := COALESCE(actor, NEW.updated_by);
    ELSE
        NEW.created_by := OLD.created_by;
        NEW.updated_by := COALESCE(actor, NEW.updated_by);
    END IF;
    RETURN NEW;
END
$$
"""


def actor_audit_statements(table: str) -> list[str]:
    """Attach the actor trigger to `table` (BEFORE INSERT OR UPDATE, per row)."""
    t = _check(table)
    return [
        (
            f"CREATE TRIGGER {t}_stamp_actor BEFORE INSERT OR UPDATE ON {t} "
            "FOR EACH ROW EXECUTE FUNCTION supportx_stamp_actor()"
        )
    ]


# --- SECURITY DEFINER functions (D-168, #476) -----------------------------------------------------
# The only way a migration creates one. Each is owned by the migrator (the migration runs as it),
# runs with a fixed search_path, is closed to PUBLIC and open to supportx_app alone. The body is
# the caller's; nothing in it may grant, alter roles or switch row-level security (the policy
# guard scans migrations' strings, and these words are refused there).
_SIGNATURE = re.compile(
    r"^[a-z_][a-z0-9_]{0,62}\((?:[a-z_ ]+(?:\[\])?(?:, ?[a-z_ ]+(?:\[\])?)*)?\)$"
)
_VOLATILITY = {"STABLE", "VOLATILE"}
_LANGUAGES = {"sql", "plpgsql"}


def _check_signature(signature: str) -> str:
    if not _SIGNATURE.match(signature):
        msg = f"not a function signature: {signature!r}"
        raise ValueError(msg)
    return signature


def definer_function_statements(  # noqa: PLR0913 - one statement's parts, explicit
    name: str,
    arguments: str,
    returns: str,
    body: str,
    *,
    language: str = "sql",
    volatility: str = "STABLE",
) -> list[str]:
    """CREATE a migrator-owned SECURITY DEFINER function, closed to PUBLIC, for supportx_app.

    `arguments` are named (`p_subject uuid`); the signature for the grants is derived from
    their types.
    """
    if language not in _LANGUAGES or volatility not in _VOLATILITY:
        msg = f"language {language!r} / volatility {volatility!r} not allowed"
        raise ValueError(msg)
    if "$$" in body:
        msg = "the body may not close its own quoting"
        raise ValueError(msg)
    types = ", ".join(
        part.strip().split(" ", 1)[1] for part in arguments.split(",") if part.strip()
    )
    signature = _check_signature(f"{_check(name)}({types})")
    return [
        (
            f"CREATE FUNCTION {_check(name)}({arguments}) RETURNS {returns} "
            f"LANGUAGE {language} {volatility} SECURITY DEFINER "
            f"SET search_path = pg_catalog, public AS $${body}$$"
        ),
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}",
    ]


def drop_definer_function_statements(signature: str) -> list[str]:
    """Reverse of `definer_function_statements` (downgrades)."""
    return [f"DROP FUNCTION {_check_signature(signature)}"]
