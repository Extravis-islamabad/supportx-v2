"""The ai module over HTTP (WP-037): AI settings and the outcome of a call.

The features themselves (summaries, reply drafts, duplicates) have their routes with the record
they work on (WP-038); they all call the gateway.
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.ai.domain.features import FEATURES, AiArea
from app.modules.ai.infra.models import AiSettings
from app.modules.ai.service import calls
from app.modules.ai.service.gateway import Gateway
from app.modules.ai.service.settings import RETENTION_DAYS, settings_row, update_settings
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

Responses = dict[int | str, dict[str, Any]]
router = APIRouter(
    prefix="/ai",
    tags=["ai"],
    dependencies=[Depends(rate_limit("ai"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    },
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]
GATEWAY_STATE = "ai_gateway"


def get_gateway(request: Request) -> Gateway:
    """The running gateway (made at start-up from the installation's provider settings)."""
    gateway: Gateway = getattr(request.app.state, GATEWAY_STATE)
    return gateway


class FeatureOut(BaseModel):
    """An AI feature the settings screen lists (labels `ai_feature.<code>`, `ai_area.<area>`)."""

    code: str
    area: AiArea
    enabled: bool


class ProviderOut(BaseModel):
    """Which model answers, and whether it is outside the installation (masking always on)."""

    name: str
    model: str
    external: bool


class AiSettingsOut(BaseModel):
    """The tenant's AI settings, the features with their state, and the provider."""

    enabled: bool
    disabled_features: list[str]
    mask_local: bool
    log_retention_days: int
    version: int
    features: list[FeatureOut]
    provider: ProviderOut

    @classmethod
    def of(cls, row: AiSettings, gateway: Gateway) -> "AiSettingsOut":
        """From the row and the running provider."""
        return cls(
            enabled=row.enabled,
            disabled_features=list(row.disabled_features),
            mask_local=row.mask_local,
            log_retention_days=row.log_retention_days,
            version=row.version,
            features=[
                FeatureOut(
                    code=f.code,
                    area=f.area,
                    enabled=row.enabled and f.code not in row.disabled_features,
                )
                for f in FEATURES
            ],
            provider=ProviderOut(
                name=gateway.provider.name,
                model=gateway.provider.model,
                external=gateway.provider.external,
            ),
        )


class AiSettingsPatch(BaseModel):
    """Change the AI settings (If-Match)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    disabled_features: list[str] | None = Field(default=None, max_length=50)
    mask_local: bool | None = None
    log_retention_days: int | None = Field(
        default=None, ge=RETENTION_DAYS.start, le=RETENTION_DAYS.stop - 1
    )


class OutcomeIn(BaseModel):
    """What the person did with an AI answer (REQ-AI-031, REQ-AI-034)."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["accepted", "edited", "discarded"]


Gw = Annotated[Gateway, Depends(get_gateway)]


@router.get("/settings", summary="AI settings")
async def get_settings(
    session: TenantSession, subject: SignedIn, gateway: Gw, response: Response
) -> AiSettingsOut:
    """Read by everyone signed in: screens hide AI features that are off."""
    del subject
    row = await settings_row(session)
    set_etag(response, row.version)
    return AiSettingsOut.of(row, gateway)


@router.patch(
    "/settings",
    summary="Change AI settings",
    responses={409: {"model": ProblemDetail, "description": "Stale If-Match."}},
    dependencies=[audited("ai.settings_changed", object_type="ai_settings")],
)
async def patch_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: AiSettingsPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    gateway: Gw,
    request: Request,
    response: Response,
) -> AiSettingsOut:
    """Needs `ai.manage`. Switching a feature off stops its calls at once, for everyone."""
    values = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    row = await update_settings(
        session, subject, values, expected_version=version, source=source_of(request)
    )
    set_etag(response, row.version)
    return AiSettingsOut.of(row, gateway)


@router.post(
    "/calls/{call_id}/outcome", summary="Say what you did with an AI answer", status_code=204
)
async def post_outcome(
    call_id: uuid.UUID, body: OutcomeIn, session: TenantSession, subject: SignedIn
) -> None:
    """Accepted, edited or discarded: for quality and usage reporting. Your own calls only."""
    await calls.set_outcome(session, subject, call_id, body.outcome)
