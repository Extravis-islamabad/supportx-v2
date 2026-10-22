from collections.abc import Callable
from http import HTTPStatus
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import (
    PROBLEM_MEDIA_TYPE,
    AppError,
    BadRequest,
    Conflict,
    EntitlementRequired,
    FieldError,
    NotFound,
    PermissionDenied,
    RateLimited,
    ServiceUnavailable,
    Unauthenticated,
    ValidationFailed,
)
from app.core.modules import ModuleRegistry, ModuleSpec
from app.main import create_app

router = APIRouter(prefix="/boom")

ERRORS: dict[str, AppError] = {
    "bad_request": BadRequest(),
    "unauthenticated": Unauthenticated(),
    "permission_denied": PermissionDenied(),
    "entitlement_required": EntitlementRequired(params={"feature": "cmdb"}),
    "not_found": NotFound(code="ticket_not_found", params={"id": "INC-1"}),
    "conflict": Conflict(params={"current_version": 4}),
    "validation_failed": ValidationFailed(
        errors=[
            FieldError(field="body.title", code="too_long", message_key="errors.field.too_long")
        ]
    ),
    "rate_limited": RateLimited(),
    "service_unavailable": ServiceUnavailable(),
}


@router.get("/app/{name}")
async def raise_app_error(name: str) -> None:
    raise ERRORS[name]


@router.get("/crash")
async def crash() -> None:
    msg = "database password is hunter2"
    raise RuntimeError(msg)


class Payload(BaseModel):
    title: str = Field(max_length=5)
    count: int


@router.post("/validate")
async def validate(payload: Payload) -> Payload:
    return payload


@pytest.fixture
def app(settings_factory: Callable[..., Settings]) -> FastAPI:
    registry = ModuleRegistry.from_specs([ModuleSpec(name="boom", routers=[router])])
    return create_app(settings_factory(), registry)


@pytest.mark.parametrize(
    ("name", "status", "code"),
    [
        ("bad_request", 400, "bad_request"),
        ("unauthenticated", 401, "unauthenticated"),
        ("permission_denied", 403, "permission_denied"),
        ("entitlement_required", 403, "entitlement_required"),
        ("not_found", 404, "ticket_not_found"),
        ("conflict", 409, "conflict"),
        ("validation_failed", 422, "validation_failed"),
        ("rate_limited", 429, "rate_limited"),
        ("service_unavailable", 503, "service_unavailable"),
    ],
)
async def test_app_errors_map_to_problem_details(
    app: FastAPI, run_app: Callable[[FastAPI], Any], name: str, status: int, code: str
) -> None:
    async with run_app(app) as client:
        response = await client.get(f"/api/v1/boom/app/{name}")

    assert response.status_code == status
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = response.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["message_key"] == f"errors.{code}"
    assert body["type"] == f"urn:supportx:problem:{code}"
    assert body["title"] == HTTPStatus(status).phrase
    assert body["instance"] == f"/api/v1/boom/app/{name}"
    assert body["request_id"] == response.headers["x-request-id"]


async def test_params_and_field_errors_are_returned(
    app: FastAPI, run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(app) as client:
        conflict = (await client.get("/api/v1/boom/app/conflict")).json()
        invalid = (await client.get("/api/v1/boom/app/validation_failed")).json()

    assert conflict["params"] == {"current_version": 4}
    assert invalid["errors"] == [
        {
            "field": "body.title",
            "code": "too_long",
            "message_key": "errors.field.too_long",
            "params": {},
        }
    ]


async def test_request_validation_returns_field_level_errors(
    app: FastAPI, run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(app) as client:
        response = await client.post("/api/v1/boom/validate", json={"title": "too long title"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    by_field = {e["field"]: e for e in body["errors"]}
    assert by_field["body.title"]["code"] == "string_too_long"
    assert by_field["body.title"]["message_key"] == "errors.field.string_too_long"
    assert by_field["body.title"]["params"] == {"max_length": 5}
    assert by_field["body.count"]["code"] == "missing"


async def test_unhandled_exception_returns_generic_500_without_internals(
    app: FastAPI, run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(app) as client:
        response = await client.get("/api/v1/boom/crash", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.headers["x-request-id"] == "req-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["request_id"] == "req-123"
    text = response.text
    for leak in ("RuntimeError", "hunter2", "Traceback", "crash"):
        assert leak not in text.replace("/boom/crash", "")


async def test_framework_errors_use_problem_details(
    app: FastAPI, run_app: Callable[[FastAPI], Any]
) -> None:
    async with run_app(app) as client:
        missing = await client.get("/api/v1/nowhere")
        wrong_method = await client.delete("/api/v1/boom/crash")

    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["code"] == "method_not_allowed"
    assert "allow" in wrong_method.headers


async def test_server_side_app_errors_are_logged(
    app: FastAPI, run_app: Callable[[FastAPI], Any], caplog: pytest.LogCaptureFixture
) -> None:
    async with run_app(app) as client:
        await client.get("/api/v1/boom/app/service_unavailable")
        await client.get("/api/v1/boom/app/not_found")

    logged = [r.msg for r in caplog.records if r.name == "app.core.errors"]
    assert len(logged) == 1
    assert "service_unavailable" in str(logged[0])
