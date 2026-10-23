"""Unit tests (no database) for tenant resolution, RLS SQL and engine helpers."""

import uuid
from collections.abc import Callable

import pytest

from app.core.config import Settings
from app.core.database import Database, to_async_url
from app.core.errors import BadRequest
from app.core.tenancy import TenantContext, tenant_from_header
from app.shared.db.rls import (
    CURRENT_TENANT_SQL,
    app_grant_statements,
    drop_tenant_rls_statements,
    tenant_rls_statements,
)

TENANT = uuid.UUID("01900000-0000-7000-8000-000000000001")


@pytest.mark.parametrize("profile", ["dev", "test"])
def test_header_is_trusted_in_dev_and_test(
    settings_factory: Callable[..., Settings], profile: str
) -> None:
    settings = settings_factory(profile=profile, dev_tenant_header=True)
    assert tenant_from_header(settings, f" {TENANT} ") == TenantContext(TENANT)
    assert tenant_from_header(settings, None) is None
    with pytest.raises(BadRequest):
        tenant_from_header(settings, "acme")


@pytest.mark.parametrize("profile", ["dev", "test"])
def test_header_is_off_by_default(settings_factory: Callable[..., Settings], profile: str) -> None:
    assert tenant_from_header(settings_factory(profile=profile), str(TENANT)) is None


def test_header_is_ignored_in_production(settings_factory: Callable[..., Settings]) -> None:
    production = settings_factory(
        profile="production",
        database_url="postgresql://u:p@db/x",
        valkey_url="valkey://:p@kv:6379/0",
        nats_url="nats://bus:4222",
        oidc_issuer="https://id.example.com/realms/supportx",
        oidc_console_client_secret="x",
        oidc_portal_client_secret="x",
        session_secret="s" * 32,
        centrifugo_api_url="http://127.0.0.1:1",
        centrifugo_api_key="k",
        centrifugo_token_secret="c" * 32,
        dev_tenant_header=True,  # even explicitly enabled
    )
    assert production.tenant_header_enabled is False
    assert tenant_from_header(production, str(TENANT)) is None
    assert tenant_from_header(production, "not-even-a-uuid") is None


def test_rls_statements_enable_force_and_cover_every_command() -> None:
    statements = tenant_rls_statements("tickets")
    assert statements[:2] == [
        "ALTER TABLE tickets ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE tickets FORCE ROW LEVEL SECURITY",
    ]
    policies = statements[2:]
    for command in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert any(f"FOR {command}" in p for p in policies)
    update = next(p for p in policies if "FOR UPDATE" in p)
    assert update.count(f"tenant_id = {CURRENT_TENANT_SQL}") == 2  # USING and WITH CHECK
    assert CURRENT_TENANT_SQL == "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def test_rls_helpers_reject_unsafe_identifiers() -> None:
    for bad in ("tickets; DROP TABLE tenants", "Tickets", "a b", ""):
        with pytest.raises(ValueError, match="unsafe SQL identifier"):
            tenant_rls_statements(bad)


def test_drop_statements_reverse_enable() -> None:
    statements = drop_tenant_rls_statements("tickets")
    assert "DROP POLICY IF EXISTS tickets_tenant_select ON tickets" in statements
    assert statements[-1] == "ALTER TABLE tickets DISABLE ROW LEVEL SECURITY"


def test_app_grants_never_include_truncate() -> None:
    assert app_grant_statements("tickets") == [
        "REVOKE ALL ON tickets FROM supportx_app",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON tickets TO supportx_app",
    ]
    assert app_grant_statements("tickets", ()) == ["REVOKE ALL ON tickets FROM supportx_app"]
    with pytest.raises(ValueError, match="may be granted"):
        app_grant_statements("tickets", ("TRUNCATE",))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@h:1/d", "postgresql+asyncpg://u:p@h:1/d"),
        ("postgres://u:p@h/d", "postgresql+asyncpg://u:p@h/d"),
        ("postgresql+asyncpg://u:p@h/d", "postgresql+asyncpg://u:p@h/d"),
    ],
)
def test_to_async_url(url: str, expected: str) -> None:
    assert to_async_url(url) == expected


def test_to_async_url_rejects_other_databases() -> None:
    with pytest.raises(ValueError, match="postgresql://"):
        to_async_url("mysql://u:p@h/d")


async def test_database_from_settings(settings_factory: Callable[..., Settings]) -> None:
    assert Database.from_settings(settings_factory()) is None
    database = Database.from_settings(
        settings_factory(database_url="postgresql://u:p@127.0.0.1:1/d")
    )
    assert database is not None
    assert database.engine.url.drivername == "postgresql+asyncpg"
    await database.dispose()
