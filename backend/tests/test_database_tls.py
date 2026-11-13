"""Verified TLS to PostgreSQL (audit row 5): sslmode verify-full when a root CA is configured.

No database and no network: the connect arguments are caught before asyncpg dials anything.
"""

import ast
import ssl
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event

from app.core.config import Settings
from app.core.database import Database, create_engine, database_ssl
from tests.tls_certs import make_certs
from tooling import deploy_migrate
from tooling.deploy_migrate import DeployConfig, alembic_config


class _Caught(Exception):
    """Stops the connect once its arguments are seen."""


async def _connect_params(context: ssl.SSLContext | None) -> dict[str, Any]:  # Any: asyncpg's
    engine = create_engine(
        "postgresql://app:pw@pooler:5432/supportx", application_name="t", use_null_pool=True,
        ssl=context,
    )  # fmt: skip
    seen: dict[str, Any] = {}

    @event.listens_for(engine.sync_engine, "do_connect")
    def _catch(_dialect: object, _record: object, _args: object, params: dict[str, Any]) -> None:
        seen.update(params)
        raise _Caught

    with pytest.raises(_Caught):
        async with engine.connect():
            pass
    await engine.dispose()
    return seen


def test_the_context_is_verify_full(tmp_path: Path) -> None:
    context = database_ssl(make_certs(tmp_path, ["pooler"]).ca)
    assert context is not None
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True  # verify-full, not verify-ca
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert database_ssl(None) is None


async def test_the_engine_hands_the_context_to_asyncpg(tmp_path: Path) -> None:
    context = database_ssl(make_certs(tmp_path, ["pooler"]).ca)
    params = await _connect_params(context)
    assert params["ssl"] is context
    assert params["statement_cache_size"] == 0  # the PgBouncer-safe arguments stay
    assert "ssl" not in await _connect_params(None)


async def test_the_application_database_uses_the_setting(tmp_path: Path) -> None:
    ca = make_certs(tmp_path, ["pooler"]).ca
    settings = Settings.load(
        env_file=None,
        profile="test",
        database_url="postgresql://app:pw@pooler:5432/supportx",
        database_ssl_root_cert=str(ca),
    )
    assert settings.database_ssl_root_cert == ca
    database = Database.from_settings(settings)
    assert database is not None
    seen: dict[str, Any] = {}

    @event.listens_for(database.engine.sync_engine, "do_connect")
    def _catch(_dialect: object, _record: object, _args: object, params: dict[str, Any]) -> None:
        seen.update(params)
        raise _Caught

    with pytest.raises(_Caught):
        async with database.engine.connect():
            pass
    await database.dispose()
    found = seen["ssl"]
    assert isinstance(found, ssl.SSLContext)
    assert found.verify_mode == ssl.CERT_REQUIRED
    assert found.check_hostname is True


def test_the_deploy_job_reads_the_root_cert(tmp_path: Path) -> None:
    ca = make_certs(tmp_path, ["pg-rw"]).ca
    env = {"SUPPORTX_MIGRATION_DATABASE_URL": "postgresql://m@db/x"}
    assert DeployConfig.from_env(env).ssl is None
    config = DeployConfig.from_env({**env, "SUPPORTX_DATABASE_SSL_ROOT_CERT": str(ca)})
    assert config.ssl_root_cert == ca
    found = config.ssl
    assert found is not None
    assert found.check_hostname is True


def test_the_deploy_job_hands_its_context_to_every_migration_run(tmp_path: Path) -> None:
    """migrations/env.py uses the code-passed URL with the code-passed context, or none at all:
    a URL handed over without the context would connect unverified (lane C, #466)."""
    ca = make_certs(tmp_path, ["pg-rw"]).ca
    context = DeployConfig.from_env(
        {"SUPPORTX_MIGRATION_DATABASE_URL": "postgresql://m@db/x",
         "SUPPORTX_DATABASE_SSL_ROOT_CERT": str(ca)}
    ).ssl  # fmt: skip
    assert alembic_config("postgresql://m@db/x", context).attributes["database_ssl"] is context
    # Every alembic_config call that runs a command passes the context; reading the script
    # directory (ScriptDirectory.from_config) opens no connection and may leave it out.
    tree = ast.parse(Path(deploy_migrate.__file__).read_text())
    readers = {
        id(arg)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "from_config"
        for arg in node.args
    }
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "alembic_config"
    ]
    assert calls
    for call in calls:
        if id(call) in readers:
            continue
        assert len(call.args) + len(call.keywords) >= 2, f"line {call.lineno}: no ssl context"
