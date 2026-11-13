"""Block rules for unwanted mail on Admin > Mail (WP-046a S6; REQ-INC-026).

The mailbox managers' right. Creates take an Idempotency-Key, changes and removals If-Match; every
write is audited. Plain text rules only: a sender, a domain, or text in the subject or body.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.modules.integrations.domain.mailboxes import BlockKind
from app.modules.integrations.infra.models import MailBlockRule
from app.modules.integrations.service import block_rules as service
from app.modules.integrations.service.mailboxes import MANAGE_KEYS
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/integrations/mail-block-rules",
    tags=["integrations"],
    dependencies=[Depends(rate_limit("integrations"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing integrations.manage_email."},
        404: {"model": ProblemDetail, "description": "No such rule (mail_block_rule_not_found)."},
    },
)
Manage = Annotated[Subject, Depends(require_permission(*MANAGE_KEYS))]
CONFLICT: dict[int | str, dict[str, Any]] = {  # Any: FastAPI's own responses type
    409: {"model": ProblemDetail, "description": "Stale If-Match, the same rule exists, or full."}
}


class BlockRuleIn(BaseModel):
    """A new rule."""

    model_config = ConfigDict(extra="forbid")

    kind: BlockKind
    value: str = Field(min_length=1, max_length=320, description="Plain text, never a pattern.")
    enabled: bool = True


class BlockRulePatch(BaseModel):
    """What to change of a rule (its kind stays)."""

    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(default=None, min_length=1, max_length=320)
    enabled: bool | None = None


class BlockRuleOut(BaseModel):
    """A rule as Admin > Mail shows it."""

    id: uuid.UUID
    kind: BlockKind
    value: str
    enabled: bool
    updated_at: datetime
    version: int

    @classmethod
    def of(cls, row: MailBlockRule) -> "BlockRuleOut":
        """From the stored rule."""
        return cls(
            id=row.id,
            kind=BlockKind(row.kind),
            value=row.value,
            enabled=row.enabled,
            updated_at=row.updated_at,
            version=row.version,
        )


@router.get("", summary="Block rules for unwanted mail")
async def list_rules(session: TenantSession, subject: Manage) -> list[BlockRuleOut]:
    """Every rule, by kind and value."""
    del subject
    return [BlockRuleOut.of(row) for row in await service.list_rules(session)]


@router.post(
    "",
    summary="Add a block rule",
    status_code=status.HTTP_201_CREATED,
    response_model=BlockRuleOut,
    responses=CONFLICT,
    dependencies=[audited("mail_block_rule.created", object_type="mail_block_rule")],
)
async def create_rule(
    body: BlockRuleIn, session: TenantSession, subject: Manage, idempotency: Idempotency
) -> Response:
    """Send an Idempotency-Key: a retried request returns the same 201."""
    del subject

    async def run() -> Created:
        row = await service.create_rule(session, body.kind, body.value, enabled=body.enabled)
        out = BlockRuleOut.of(row)
        return Created(body=out, headers={"ETag": f'"{out.version}"'})

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/{rule_id}",
    summary="Change a block rule",
    responses=CONFLICT,
    dependencies=[
        audited("mail_block_rule.changed", object_type="mail_block_rule", object_param="rule_id")
    ],
)
async def update_rule(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    rule_id: uuid.UUID,
    body: BlockRulePatch,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
) -> BlockRuleOut:
    """If-Match: the version you read."""
    del subject
    row = await service.update_rule(
        session, rule_id, expected_version=version, value=body.value, enabled=body.enabled
    )
    set_etag(response, row.version)
    return BlockRuleOut.of(row)


@router.delete(
    "/{rule_id}",
    summary="Remove a block rule",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[
        audited("mail_block_rule.removed", object_type="mail_block_rule", object_param="rule_id")
    ],
)
async def remove_rule(
    rule_id: uuid.UUID, session: TenantSession, subject: Manage, version: ExpectedVersion
) -> None:
    """If-Match: the version you read."""
    del subject
    await service.remove_rule(session, rule_id, expected_version=version)
