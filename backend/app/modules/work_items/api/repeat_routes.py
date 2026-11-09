"""Repeat incident rules and what they found (WP-044c S3, D16; REQ-PRB-068).

    GET    /problem-repeats/rules             the rules, the default first (admins)
    POST   /problem-repeats/rules             a new rule (Idempotency-Key)
    PATCH  /problem-repeats/rules/{id}        change it (If-Match)
    DELETE /problem-repeats/rules/{id}        remove it (If-Match; the default is only switched off)
    GET    /problem-repeats/hits              the open sets, newest first (who may create problems)
    GET    /problem-repeats/hits/{id}/incidents   the set's incidents you may see
    POST   /problem-repeats/hits/{id}/handle  a problem was made from it, or dismiss it (If-Match)

The router is the problem module's feature (D-140 item 5: not in Essentials), so the server
refuses it for a tenant without problems; the console shows it off with an upgrade hint.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import PROBLEM
from app.modules.work_items.infra.models import ProblemRepeatHit, ProblemRepeatRule
from app.modules.work_items.service import repeat_rules as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Idempotency
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/problem-repeats",
    tags=["problems"],
    dependencies=[Depends(rate_limit("work_items"))],
)
Admin = Annotated[Subject, Depends(require_permission("config.service_desk", "settings.manage"))]
Creator = Annotated[Subject, Depends(require_permission(PROBLEM.permission("create")))]
Match = Literal["category", "category_site"]


class RepeatRuleOut(BaseModel):
    """A repeat incident rule."""

    id: uuid.UUID
    name: str = Field(description="As typed; the default's is labelled `repeat_rule.default`.")
    match: Match
    threshold: int
    window_hours: int
    notify_group_id: uuid.UUID | None = Field(description="None: the incidents' own group.")
    enabled: bool
    is_default: bool
    version: int

    @classmethod
    def of(cls, row: ProblemRepeatRule) -> "RepeatRuleOut":
        """From the row."""
        return cls.model_validate(row, from_attributes=True)


class RepeatRuleIn(BaseModel):
    """A new rule."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    match: Match
    threshold: int = Field(ge=2, le=1000)
    window_hours: int = Field(ge=1, le=2160)
    notify_group_id: uuid.UUID | None = None
    enabled: bool = True


class RepeatRulePatch(BaseModel):
    """What to change (only what is sent)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    match: Match | None = None
    threshold: int | None = Field(default=None, ge=2, le=1000)
    window_hours: int | None = Field(default=None, ge=1, le=2160)
    notify_group_id: uuid.UUID | None = None
    enabled: bool | None = None


class RepeatHitOut(BaseModel):
    """One open set of matching incidents."""

    id: uuid.UUID
    rule_id: uuid.UUID
    category_id: uuid.UUID | None
    site_id: uuid.UUID | None
    group_id: uuid.UUID | None
    incident_count: int = Field(description="Every match; the set keeps the newest 100.")
    first_at: datetime
    last_at: datetime
    version: int

    @classmethod
    def of(cls, row: ProblemRepeatHit) -> "RepeatHitOut":
        """From the row."""
        return cls.model_validate(row, from_attributes=True)


class RepeatHitIncidentOut(BaseModel):
    """An incident of the set, as the list shows it."""

    id: uuid.UUID
    display_id: str
    subject: str
    created_at: datetime


class RepeatHandleIn(BaseModel):
    """What was done with the set."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["problem_created", "dismissed"]
    problem_id: uuid.UUID | None = Field(default=None, description="With problem_created.")


@router.get("/rules", summary="Repeat incident rules")
async def list_rules(session: TenantSession, subject: Admin) -> list[RepeatRuleOut]:
    """Every rule, the default first (made on first use)."""
    del subject
    return [RepeatRuleOut.of(r) for r in await service.list_rules(session)]


@router.post("/rules", summary="Add a repeat incident rule", status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: RepeatRuleIn,
    session: TenantSession,
    subject: Admin,
    idempotency: Idempotency,
    note: Annotated[
        AuditNote, audited("problem.repeat_rule_created", object_type="problem_repeat_rule")
    ],
) -> Response:
    """A new rule, on unless sent off."""
    del subject

    async def run() -> RepeatRuleOut:
        rule = await service.create_rule(session, body.model_dump())
        note.object_id = str(rule.id)
        return RepeatRuleOut.of(rule)

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/rules/{rule_id}",
    summary="Change a repeat incident rule",
    dependencies=[
        audited(
            "problem.repeat_rule_changed",
            object_type="problem_repeat_rule",
            object_param="rule_id",
        )
    ],
)
async def update_rule(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    rule_id: uuid.UUID,
    body: RepeatRulePatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Admin,
    response: Response,
) -> RepeatRuleOut:
    """Only what is sent changes; a stale If-Match is a 409."""
    del subject
    rule = await service.update_rule(
        session,
        rule_id,
        body.model_dump(include=body.model_fields_set),
        expected_version=version,
    )
    set_etag(response, rule.version)
    return RepeatRuleOut.of(rule)


@router.delete(
    "/rules/{rule_id}",
    summary="Remove a repeat incident rule",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited(
            "problem.repeat_rule_removed",
            object_type="problem_repeat_rule",
            object_param="rule_id",
        )
    ],
)
async def delete_rule(
    rule_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Admin
) -> Response:
    """The default rule is only switched off, never removed."""
    del subject
    await service.delete_rule(session, rule_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/hits", summary="Open sets of repeated incidents")
async def list_hits(session: TenantSession, subject: Creator) -> list[RepeatHitOut]:
    """For who may create problems: what the rules found and nobody handled yet."""
    return [RepeatHitOut.of(h) for h in await service.open_hits(session, subject)]


@router.get("/hits/{hit_id}/incidents", summary="The incidents of a set")
async def hit_incidents(
    hit_id: uuid.UUID, session: TenantSession, subject: Creator
) -> list[RepeatHitIncidentOut]:
    """The newest 100 of the set, only those you may see (their own scope applies)."""
    rows = await service.hit_incidents(session, subject, hit_id)
    return [
        RepeatHitIncidentOut(
            id=r.id, display_id=r.display_id, subject=r.subject, created_at=r.created_at
        )
        for r in rows
    ]


@router.post(
    "/hits/{hit_id}/handle",
    summary="Create a problem from a set, or dismiss it",
    dependencies=[
        audited(
            "problem.repeat_hit_handled", object_type="problem_repeat_hit", object_param="hit_id"
        )
    ],
)
async def handle_hit(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    hit_id: uuid.UUID,
    body: RepeatHandleIn,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Creator,
    response: Response,
) -> RepeatHitOut:
    """Handled sets leave the list; only new incidents open the key again (AC2)."""
    hit = await service.handle(
        session,
        subject,
        hit_id,
        outcome=body.outcome,
        expected_version=version,
        problem_id=body.problem_id,
    )
    set_etag(response, hit.version)
    return RepeatHitOut.of(hit)
