"""Liveness and readiness endpoints (architecture.md §15)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app import __version__
from app.modules.system.domain.readiness import CheckStatus, FailureReason, ReadinessReport
from app.modules.system.service.readiness import ReadinessService

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Liveness: the process is up and serving."""

    status: Literal["ok"]
    version: str


class CheckResponse(BaseModel):
    """One dependency's readiness."""

    status: CheckStatus
    latency_ms: float | None = Field(default=None, description="Probe duration.")
    reason: FailureReason | None = Field(default=None, description="Why it failed, if it did.")


class ReadinessResponse(BaseModel):
    """Readiness: every dependency this process needs, and which one failed."""

    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckResponse]
    failed: list[str]


def get_readiness_service(request: Request) -> ReadinessService:
    """The service built by the system module's startup hook."""
    service: ReadinessService = request.app.state.readiness
    return service


@router.get("/health", summary="Liveness")
async def get_health() -> HealthResponse:
    """Return 200 while the process runs.

    Checks no dependency, so a database outage never makes the orchestrator restart healthy API
    pods.
    """
    return HealthResponse(status="ok", version=__version__)


@router.get(
    "/ready",
    summary="Readiness",
    responses={503: {"model": ReadinessResponse, "description": "A dependency is not ready."}},
)
async def get_ready(
    response: Response,
    service: Annotated[ReadinessService, Depends(get_readiness_service)],
) -> ReadinessResponse:
    """Return 200 when PostgreSQL, Valkey, NATS and Keycloak all answer within the timeout.

    Otherwise 503, naming the failing dependency with a reason code.
    """
    report = await service.check()
    if not report.ready:
        response.status_code = 503
    return _to_response(report)


def _to_response(report: ReadinessReport) -> ReadinessResponse:
    return ReadinessResponse(
        status="ready" if report.ready else "not_ready",
        checks={
            name: CheckResponse(status=r.status, latency_ms=r.latency_ms, reason=r.reason)
            for name, r in report.checks.items()
        },
        failed=report.failed,
    )
