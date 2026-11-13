"""Row-level security policies and grants reach migrations only through migrations/helpers.py.

D-168 makes the tenant-isolation code code-owned (.github/CODEOWNERS): a change to it needs the
security reviewer's approval. Migrations are not code-owned as a whole (every work package adds
some), so the product owner chose option (b): the SQL that decides who may read or write a table
(CREATE/ALTER/DROP POLICY, GRANT, REVOKE, ALTER DEFAULT PRIVILEGES) is written only in the owned
helpers (migrations/helpers.py, which builds its statements in app/shared/db/rls.py), and this
test refuses it anywhere else under migrations/versions/.

The scan is on every string literal in the file (f-string parts included), which is where SQL
lives: comments and docstrings can't run, and explain RLS in prose ("users has FORCE ROW LEVEL
SECURITY", "no BYPASSRLS"), so they are left out. Prose in a string such as "no DELETE grant"
does not match either, as only a privilege keyword after GRANT/REVOKE (or the upper-case
statement word, which is how this repo writes SQL) counts.
"""

import ast
import re
from pathlib import Path

from migrations import helpers

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "migrations" / "versions"
RLS_SQL = BACKEND / "app" / "shared" / "db" / "rls.py"

_PRIVILEGE = (
    r"(?:select|insert|update|delete|truncate|references|trigger|create|connect|temp|temporary"
    r"|execute|usage|set|maintain|all)"
)
_ACCESS_SQL = re.compile(
    r"\b(?:create|alter|drop)\s+policy\b"
    rf"|\bgrant\s+{_PRIVILEGE}\b"
    rf"|\brevoke\s+(?:(?:grant|admin)\s+option\s+for\s+)?{_PRIVILEGE}\b"
    r"|\balter\s+default\s+privileges\b"
    # Switching row-level security off or around it (lane C, #476): DISABLE / NO FORCE (and their
    # ENABLE / FORCE twins, which belong in enable_tenant_rls), a new table owner (owners bypass
    # RLS without FORCE), SECURITY DEFINER functions (run as their owner) and roles (BYPASSRLS).
    r"|\b(?:enable|disable|force|no\s+force)\s+row\s+level\s+security\b"
    r"|\bowner\s+to\b"
    r"|\bsecurity\s+definer\b"
    r"|\b(?:create|alter)\s+role\b"
    r"|\bbypassrls\b",
    re.IGNORECASE,
)
# Role membership (GRANT supportx_app TO ...) names no privilege; the statement word in capitals
# catches it, as every SQL string in this repo is written in capitals.
_STATEMENT_WORD = re.compile(r"\b(?:GRANT|REVOKE)\b")

# Merged migrations that already hold such SQL. A merged migration is never edited (CLAUDE.md §6),
# so this set never changes: it must equal exactly what the scan finds today, which keeps it
# honest, and any other file that matches fails.
KNOWN = frozenset(
    {
        "0001_tenancy_bootstrap.py",
        "0003_outbox_and_processed_events.py",
        "0005_tenant_subscriptions.py",
        "0010_housekeeping.py",
        "0014_audit.py",
        "0017_audit_seal_batch_lookup.py",
        "0022_branding_domains.py",
        "0129_audit_fingerprints.py",
        "0146_session_key_ring.py",
        "0151_sign_in_log_and_ip_lists.py",
    }
)

ADVICE = (
    "use migrations/helpers.py (enable_tenant_rls, grant_app, grant_report, …) or add a helper "
    "there; helpers.py is code-owned (D-168)"
)


def sql_strings(source: str) -> str:
    """Every string literal in a Python source, docstrings left out, one per line."""
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return "\n".join(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    )


def access_sql(text: str) -> list[str]:
    """The policy/grant/revoke statements found in `text` (empty when there are none)."""
    found = [m.group(0) for m in _ACCESS_SQL.finditer(text)]
    found += [m.group(0) for m in _STATEMENT_WORD.finditer(text)]
    return found


def files_with_access_sql(directory: Path) -> dict[str, list[str]]:
    """Every migration file in `directory` holding policy/grant/revoke SQL, with what matched."""
    found: dict[str, list[str]] = {}
    for path in sorted(directory.glob("*.py")):
        hits = access_sql(sql_strings(path.read_text(encoding="utf-8")))
        if hits:
            found[path.name] = hits
    return found


def test_no_new_migration_writes_policies_or_grants() -> None:
    new = {
        name: hits for name, hits in files_with_access_sql(VERSIONS).items() if name not in KNOWN
    }
    assert not new, f"{ADVICE}: {new}"


def test_known_list_is_exactly_the_merged_migrations_that_match() -> None:
    assert set(files_with_access_sql(VERSIONS)) == KNOWN


def test_the_helpers_are_where_such_sql_lives() -> None:
    # helpers.py runs the statements app/shared/db/rls.py builds; both files are code-owned.
    assert access_sql(sql_strings(RLS_SQL.read_text(encoding="utf-8")))
    helpers_text = Path(helpers.__file__).read_text(encoding="utf-8")
    assert "from app.shared.db.rls import" in helpers_text
    for name in ("enable_tenant_rls", "grant_app", "grant_report", "revoke_report"):
        assert callable(getattr(helpers, name))


def test_a_new_migration_with_raw_sql_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "0999_fake.py").write_text(
        'def upgrade() -> None:\n    op.execute("grant select on widgets to supportx_report")\n',
        encoding="utf-8",
    )
    (tmp_path / "0998_policy.py").write_text(
        'op.execute(f"CREATE POLICY {t}_x ON {t} FOR SELECT USING (true)")\n', encoding="utf-8"
    )
    (tmp_path / "0997_role.py").write_text(
        'op.execute("GRANT supportx_app TO someone")\n', encoding="utf-8"
    )
    # Switching RLS off or around it (lane C, #476).
    switch_offs = {
        "0995_disable.py": 'op.execute("ALTER TABLE widgets DISABLE ROW LEVEL SECURITY")\n',
        "0994_no_force.py": 'op.execute("alter table widgets no force row level security")\n',
        "0993_owner.py": 'op.execute("ALTER TABLE widgets OWNER TO supportx_app")\n',
        "0992_definer.py": (
            'op.execute("CREATE FUNCTION f() RETURNS int LANGUAGE sql SECURITY DEFINER AS $$ '
            'SELECT 1 $$")\n'
        ),
        "0991_role.py": 'op.execute("CREATE ROLE sneaky LOGIN BYPASSRLS")\n',
    }
    for name, text in switch_offs.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "0996_clean.py").write_text(
        '"""One table, soft delete only (no DELETE grant, no BYPASSRLS)."""\n'
        "# users has FORCE ROW LEVEL SECURITY: the data step runs once per tenant.\n"
        'enable_tenant_rls("widgets")\ngrant_app("widgets")\n',
        encoding="utf-8",
    )
    assert set(files_with_access_sql(tmp_path)) == {
        "0999_fake.py",
        "0998_policy.py",
        "0997_role.py",
        *switch_offs,
    }
