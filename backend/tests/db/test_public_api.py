"""The public API's promises (WP-041; REQ-INT-017, REQ-INT-025, REQ-WI-018).

- Every action a record page offers has an operation in the contract (REQ-INT-017 AC1).
- Invalid input to every operation never answers with a stack trace or an internal name
  (REQ-INT-025 AC2): the answer is a problem with a code, whatever goes wrong.
"""

import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.core.modules import ModuleRegistry, discover_modules
from app.core.recent_auth import SignInFreshness, record_freshness
from app.core.tenancy import SESSION_RESOLVER_STATE, TenantContext
from app.main import create_app
from conftest import create_tenant, make_settings
from tooling.db_testing import ThrowawayDatabase

pytestmark = pytest.mark.db

ACTIONS_PATH = "/api/v1/incidents/{record_id}/actions/{action}"
# Actions with an operation of their own rather than the generic status move.
OWN_OPERATIONS = {
    "assign": ("post", "/api/v1/incidents/{record_id}/assign"),
    "take": ("post", "/api/v1/incidents/{record_id}/take"),
}
LEAK = re.compile(
    r"Traceback|File \"|sqlalchemy|asyncpg|psycopg|pydantic_core|\.py\b|line \d+|"
    r"Exception\b|Error:\s|stack",
    re.IGNORECASE,
)


def _document() -> dict[str, Any]:
    return create_app(make_settings()).openapi()


def test_req_int_017_ac1_every_record_action_has_an_operation() -> None:
    document = _document()
    paths = document["paths"]
    schemas = document["components"]["schemas"]
    actions = schemas["WorkItemAction"]["enum"]
    generic = paths[ACTIONS_PATH]["post"]
    action_param = next(p for p in generic["parameters"] if p["name"] == "action")
    offered = set(schemas[action_param["schema"]["$ref"].rsplit("/", 1)[-1]]["enum"])
    missing = []
    for code in actions:
        own = OWN_OPERATIONS.get(code)
        if own is not None:
            method, path = own
            if method not in paths.get(path, {}):
                missing.append(code)
        elif code not in offered:
            missing.append(code)
    assert missing == []
    assert "delete" in paths["/api/v1/incidents/{record_id}"]  # the destructive action


FRESH = SignInFreshness(interactive=True, recent=True)


async def _admin_session(request: Request) -> TenantContext | None:
    tenant = request.headers.get("x-test-tenant")
    if tenant is None:
        return None
    # A signed-in browser that confirmed just now (REQ-SEC-027's RecentAuth passes).
    record_freshness(request, FRESH)
    return TenantContext(uuid.UUID(tenant), uuid.UUID(request.headers["x-test-user"]))


@pytest_asyncio.fixture
async def client(
    migrated_db: ThrowawayDatabase,
) -> AsyncIterator[tuple[AsyncClient, dict[str, str]]]:
    app: FastAPI = create_app(
        make_settings(database_url=migrated_db.app_url),
        ModuleRegistry.from_specs(discover_modules()),
    )
    tenant = await create_tenant(migrated_db.migrator_url, "Fuzz")
    async with app.router.lifespan_context(app):
        setattr(app.state, SESSION_RESOLVER_STATE, _admin_session)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            # A user that does not exist: every route answers as for an unknown caller or a
            # refusal; the point is the shape of every answer, never its status.
            yield http, {"X-Test-Tenant": str(tenant), "X-Test-User": str(uuid.uuid4())}


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "not-a-real-id", path)


async def test_req_int_025_ac2_no_answer_holds_a_stack_trace(
    client: tuple[AsyncClient, dict[str, str]],
) -> None:
    http, headers = client
    leaks: list[str] = []
    for path, operations in _document()["paths"].items():
        for method in operations:
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            response = await http.request(
                method.upper(),
                _fill(path),
                headers={**headers, "Content-Type": "application/json", "If-Match": '"x"'},
                params={"limit": "nope", "filter": "{not json", "sort": "%%"},
                content=b'{"broken": ',
            )
            text = response.text
            if response.headers.get("content-type", "").startswith("application/problem+json"):
                body = response.json()
                if not isinstance(body.get("code"), str):
                    leaks.append(f"{method.upper()} {path}: problem without a code")
            # Error answers are where a trace could slip out (a 200 asset may name its generator).
            if response.status_code >= 400 and LEAK.search(text):
                leaks.append(f"{method.upper()} {path}: {response.status_code} {text[:120]}")
    assert leaks == []
