"""The ai module over HTTP (WP-037, 038): AI settings, the outcome of a call, and summaries.

Summaries are served here for any record type an owning module registers a conversation reader
for (incidents now). Reply drafts and possible duplicates live with the record they work on; all
of them call the gateway.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.ai.domain.features import FEATURES, AiArea
from app.modules.ai.infra.models import AiSettings, AiSummary
from app.modules.ai.service import calls, summaries, writing
from app.modules.ai.service.gateway import Gateway
from app.modules.ai.service.settings import (
    RETENTION_DAYS,
    settings_row,
    summary_sources,
    update_settings,
)
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


SummarySource = Literal["description", "replies", "public_notes", "private_notes"]


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
    # What conversation summaries read (WP-038); the default when the admin has not chosen.
    summary_sources: list[SummarySource]
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
            summary_sources=list(summary_sources(row)),  # type: ignore[arg-type]  # known codes (check constraint)
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
    summary_sources: list[SummarySource] | None = Field(default=None, min_length=1, max_length=4)


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


# --- conversation summaries (WP-038, REQ-INC-137) -------------------------------------------------

SummaryRecordType = Literal["incident"]


class SummaryOut(BaseModel):
    """A record's conversation summary, or none yet (`summary` null)."""

    summary: str | None
    model: str | None
    made_at: datetime | None
    stale: bool
    # Private notes were read (staff only); the card says so.
    includes_private: bool
    call_id: uuid.UUID | None
    version: int | None

    @classmethod
    def of(cls, row: AiSummary | None, *, includes_private: bool) -> "SummaryOut":
        """From the stored row (or none)."""
        if row is None:
            return cls(
                summary=None,
                model=None,
                made_at=None,
                stale=False,
                includes_private=includes_private,
                call_id=None,
                version=None,
            )
        return cls(
            summary=row.text,
            model=row.model,
            made_at=row.updated_at,
            stale=row.stale,
            includes_private=row.level == summaries.WITH_PRIVATE,
            call_id=row.call_id,
            version=row.version,
        )


SUMMARY_ERRORS: Responses = {
    404: {"model": ProblemDetail, "description": "No such record, or not visible to you."},
}


@router.get(
    "/summaries/{record_type}/{record_id}",
    summary="A record's conversation summary",
    responses=SUMMARY_ERRORS,
)
async def get_summary(
    record_type: SummaryRecordType, record_id: uuid.UUID, session: TenantSession, subject: SignedIn
) -> SummaryOut:
    """The latest summary at your level (with private notes when the admin chose them)."""
    row = await summaries.current(session, subject, record_type, record_id)
    sources = summary_sources(await settings_row(session))
    return SummaryOut.of(row, includes_private="private_notes" in sources)


@router.post(
    "/summaries/{record_type}/{record_id}/refresh",
    summary="Summarise a record's conversation now",
    responses={
        **SUMMARY_ERRORS,
        422: {"model": ProblemDetail, "description": "Nothing to summarise yet."},
        503: {"model": ProblemDetail, "description": "The model did not answer."},
    },
)
async def refresh_summary(
    record_type: SummaryRecordType,
    record_id: uuid.UUID,
    session: TenantSession,
    subject: SignedIn,
    gateway: Gw,
) -> SummaryOut:
    """Through the gateway: your permission, the plan, the switches, masking and the log."""
    row = await summaries.refresh(session, subject, gateway, record_type, record_id)
    return SummaryOut.of(row, includes_private=row.level == summaries.WITH_PRIVATE)


# --- writing help (WP-038, REQ-INC-136) -----------------------------------------------------------


WritingStyle = Literal["correct", "shorter", "longer", "formal", "friendly", "translate"]


class WritingIn(BaseModel):
    """A draft from an instruction, or the person's own text improved."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["draft", "improve"]
    # Where it goes: a reply reaches the requester (private notes are never read for it).
    kind: Literal["reply", "note"]
    instruction: str | None = Field(default=None, max_length=writing.INSTRUCTION_MAX)
    text: str | None = Field(default=None, max_length=writing.TEXT_MAX)
    style: WritingStyle | None = None
    language: Literal["en", "ar", "ur"] | None = None


class WritingOut(BaseModel):
    """The suggested text, for the review panel (Insert, Replace or Discard); never sent here."""

    text: str
    model: str
    call_id: uuid.UUID


@router.post(
    "/writing/{record_type}/{record_id}",
    summary="Writing help: a draft or an improved text",
    responses={
        **SUMMARY_ERRORS,
        422: {"model": ProblemDetail, "description": "Nothing to work from."},
        503: {"model": ProblemDetail, "description": "The model did not answer."},
    },
)
async def post_writing(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    record_type: SummaryRecordType,
    record_id: uuid.UUID,
    body: WritingIn,
    session: TenantSession,
    subject: SignedIn,
    gateway: Gw,
) -> WritingOut:
    """Through the gateway: your permission, the plan, the switches, masking and the log."""
    answer = await writing.write(
        session,
        subject,
        gateway,
        record_type=record_type,
        record_id=record_id,
        mode=body.mode,
        kind=body.kind,
        instruction=body.instruction,
        text=body.text,
        style=body.style,
        language=body.language,
    )
    return WritingOut(text=answer.text, model=answer.model, call_id=answer.call_id)
