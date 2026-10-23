"""Integration: /api/v1/ready against the local dev stack (deploy/compose, `make dev-up`).

Skipped automatically when deploy/compose/.env is missing or the stack's ports are closed (for
example in CI's unit-test job). Reads only the dev stack's own generated credentials.
"""

import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app

STACK_ENV = Path(__file__).resolve().parents[3] / "deploy" / "compose" / ".env"


def read_stack_env() -> dict[str, str] | None:
    if not STACK_ENV.is_file():
        return None
    values: dict[str, str] = {}
    for line in STACK_ENV.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.fixture
def stack() -> dict[str, str]:
    env = read_stack_env()
    if env is None:
        pytest.skip("dev stack not initialised (deploy/compose/.env missing)")
    ports = [int(env[k]) for k in ("PGBOUNCER_PORT", "VALKEY_PORT", "NATS_PORT")]
    if not all(port_open(p) for p in ports):
        pytest.skip("dev stack not running (make dev-up)")
    return env


@pytest.mark.integration
async def test_ready_against_the_running_dev_stack(
    stack: dict[str, str],
    settings_factory: Callable[..., Settings],
    run_app: Callable[[FastAPI], Any],
) -> None:
    settings = settings_factory(
        database_url=(
            f"postgresql://supportx_app:{stack['SUPPORTX_APP_PASSWORD']}"
            f"@127.0.0.1:{stack['PGBOUNCER_PORT']}/supportx"
        ),
        valkey_url=f"valkey://:{stack['VALKEY_PASSWORD']}@127.0.0.1:{stack['VALKEY_PORT']}/0",
        nats_url=f"nats://127.0.0.1:{stack['NATS_PORT']}",
        oidc_issuer=f"http://localhost:{stack['KEYCLOAK_PORT']}/realms/supportx",
    )
    async with run_app(create_app(settings)) as client:
        response = await client.get("/api/v1/ready")

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "ready"
    critical = {name for name, check in body["checks"].items() if check["critical"]}
    assert critical == {"postgres", "valkey", "nats", "keycloak"}
    assert all(body["checks"][name]["status"] == "ok" for name in critical)
    # The event workers are reported from their heartbeats but never make the API unready.
    assert {"outbox_relay", "event_consumers", "realtime_fanout"} <= set(body["checks"])
    assert set(body["degraded"]) <= {"outbox_relay", "event_consumers", "realtime_fanout"}


@pytest.mark.integration
async def test_wrong_password_is_reported_as_auth_failed(
    stack: dict[str, str],
    settings_factory: Callable[..., Settings],
    run_app: Callable[[FastAPI], Any],
) -> None:
    settings = settings_factory(
        database_url=f"postgresql://supportx_app:wrong@127.0.0.1:{stack['PGBOUNCER_PORT']}/supportx",
        valkey_url=f"valkey://:wrong@127.0.0.1:{stack['VALKEY_PORT']}/0",
        nats_url=f"nats://127.0.0.1:{stack['NATS_PORT']}",
        oidc_issuer="http://127.0.0.1:1/realms/supportx",  # nothing listens here
    )
    async with run_app(create_app(settings)) as client:
        response = await client.get("/api/v1/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["failed"] == ["postgres", "valkey", "keycloak"]
    assert body["checks"]["keycloak"]["reason"] == "unreachable"
    assert body["checks"]["postgres"]["reason"] == "auth_failed"
    assert body["checks"]["valkey"]["reason"] == "auth_failed"
    assert body["checks"]["nats"]["status"] == "ok"
    assert "wrong" not in response.text
