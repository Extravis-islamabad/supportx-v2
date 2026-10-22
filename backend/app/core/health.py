"""Health endpoint. Liveness/readiness with dependency checks arrive in WP-004."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Service health summary."""

    status: Literal["ok"]
    version: str


@router.get("/health")
async def get_health() -> HealthResponse:
    """Report that the API process is up and which version it runs."""
    return HealthResponse(status="ok", version=__version__)
