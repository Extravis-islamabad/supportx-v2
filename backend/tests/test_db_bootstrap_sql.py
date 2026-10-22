"""The bootstrap SQL runner understands exactly the psql subset tooling/sql uses, and the dev
stack's init script runs the same files (single source of truth)."""

from pathlib import Path

import pytest

from app.shared.db.rls import APP_ROLE, MIGRATOR_ROLE
from tooling.db_bootstrap import SQL_DIR, parse, quote_identifier, quote_literal

REPO = Path(__file__).resolve().parents[2]


def test_variables_are_quoted_safely() -> None:
    (statement,) = parse("SELECT :'pw', :\"db\";\n", {"pw": "it's", "db": 'we"ird'})
    assert statement.sql == "SELECT 'it''s', \"we\"\"ird\""
    assert not statement.gexec
    assert quote_literal("a'b") == "'a''b'"
    assert quote_identifier("x") == '"x"'
    with pytest.raises(ValueError, match="NUL"):
        quote_literal("a\x00")
    with pytest.raises(ValueError, match="NUL"):
        quote_identifier("a\x00")


def test_gexec_comments_and_multiline_statements() -> None:
    script = "-- comment\n\nSELECT 'CREATE ROLE x'\nWHERE true \\gexec\nALTER ROLE x\n  LOGIN;\n"
    first, second = parse(script, {})
    assert first.gexec
    assert first.sql == "SELECT 'CREATE ROLE x'\nWHERE true"
    assert (second.sql, second.gexec) == ("ALTER ROLE x\n  LOGIN", False)


def test_unterminated_statement_is_rejected() -> None:
    with pytest.raises(ValueError, match="ends without"):
        parse("SELECT 1\n", {})


def test_unknown_variable_is_an_error() -> None:
    with pytest.raises(KeyError):
        parse("SELECT :'missing';\n", {})


def test_bootstrap_files_define_the_rls_roles() -> None:
    roles = (SQL_DIR / "roles.sql").read_text()
    assert f"'{APP_ROLE}'" in roles
    assert f"'{MIGRATOR_ROLE}'" in roles
    assert "NOBYPASSRLS NOINHERIT" in roles
    statements = parse(
        roles, {"app_password": "a", "migrator_password": "m", "relay_password": "r"}
    )
    assert [s.gexec for s in statements] == [True, True, True, False, False, False]
    assert "'supportx_relay'" in roles
    assert "ALTER ROLE supportx_relay LOGIN NOSUPERUSER" in roles
    assert (
        "supportx_relay LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        in roles
    )


def test_dev_stack_init_runs_the_same_files() -> None:
    init = (REPO / "deploy/compose/postgres/initdb/10-supportx.sh").read_text()
    compose = (REPO / "deploy/compose/docker-compose.yml").read_text()
    for name in ("roles.sql", "database.sql", "schema.sql"):
        assert f'"$SQL_DIR/{name}"' in init
    assert "../../backend/tooling/sql:/supportx-sql:ro" in compose
    # The old hand-written copies must not come back.
    assert "CREATE ROLE supportx_app" not in init
    assert "ALTER DEFAULT PRIVILEGES" not in init
