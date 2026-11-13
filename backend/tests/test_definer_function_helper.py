"""The one way a migration makes a SECURITY DEFINER function (D-168, #476; WP-057 S3b-1).

Lane B's conditions: migrator-owned (the migration runs as it), a fixed search_path, closed to
PUBLIC, EXECUTE for supportx_app alone; nothing else may be shaped by the caller.
"""

import pytest

from app.shared.db.rls import (
    APP_ROLE,
    definer_function_statements,
    drop_definer_function_statements,
)


def test_a_definer_function_is_closed_to_public_and_open_to_the_app_only() -> None:
    create, revoke, grant = definer_function_statements(
        "audit_erase_access", "p_subject uuid", "integer", "SELECT 1", volatility="VOLATILE"
    )
    assert "SECURITY DEFINER SET search_path = pg_catalog, public" in create
    assert create.startswith("CREATE FUNCTION audit_erase_access(p_subject uuid) RETURNS integer")
    assert revoke == "REVOKE ALL ON FUNCTION audit_erase_access(uuid) FROM PUBLIC"
    assert grant == f"GRANT EXECUTE ON FUNCTION audit_erase_access(uuid) TO {APP_ROLE}"
    assert definer_function_statements("sx_kek_wraps", "", "TABLE (a text)", "SELECT 1")[1] == (
        "REVOKE ALL ON FUNCTION sx_kek_wraps() FROM PUBLIC"
    )


@pytest.mark.parametrize(
    ("name", "arguments", "body", "options"),
    [
        ("Bad-Name", "", "SELECT 1", {}),  # not an identifier
        ("f", "", "SELECT 1 $$; DROP TABLE x; $$", {}),  # closes its own quoting
        ("f", "", "SELECT 1", {"language": "c"}),  # only sql and plpgsql
        ("f", "", "SELECT 1", {"volatility": "IMMUTABLE"}),  # only STABLE and VOLATILE
        ("f", "p uuid); DROP TABLE x; --", "SELECT 1", {}),  # arguments that are not types
    ],
)
def test_nothing_but_the_body_is_shaped_by_the_caller(
    name: str, arguments: str, body: str, options: dict[str, str]
) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - each case raises its own message
        definer_function_statements(name, arguments, "integer", body, **options)


def test_the_downgrade_names_one_function() -> None:
    assert drop_definer_function_statements("audit_purge_access(timestamptz)") == [
        "DROP FUNCTION audit_purge_access(timestamptz)"
    ]
    with pytest.raises(ValueError):  # noqa: PT011
        drop_definer_function_statements("f(); DROP TABLE x")
