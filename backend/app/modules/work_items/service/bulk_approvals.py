"""Approve several requests at once (WP-032 D6; REQ-PRT-008).

One comment for all, after the person confirmed the list; at most BULK_APPROVE_MAX at a time
(D-143). Each decision runs through the single-decision service in its own savepoint, so every
rule, the audit entry, the outbox event and the live update are those of one decision, and a
request that changed meanwhile (withdrawn, decided by someone else, a newer version) is skipped
with its reason while the others go ahead. There is no bulk reject: each rejection needs its own
reason (AC2).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.identity_access import Subject
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.service import approvals
from app.modules.work_items.service import work_items as items
from app.shared.history import Source

BULK_APPROVE_MAX = 20


@dataclass(frozen=True)
class ApprovalRef:
    """One approval to approve, at the version the person saw."""

    record_id: uuid.UUID
    approval_id: uuid.UUID
    version: int


@dataclass(frozen=True)
class BulkOutcome:
    """What happened to one of them."""

    ref: ApprovalRef
    decided: bool
    code: str | None = None


async def approve_many(  # noqa: PLR0913 - the approvals, the comment and the context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    refs: list[ApprovalRef],
    *,
    comment: str | None,
    channel: rules.DecisionChannel,
    source: Source,
) -> list[BulkOutcome]:
    """Approve each, in the order given; one that cannot be approved now is skipped with why."""
    unique = list({r.approval_id: r for r in refs}.values())
    if not unique:
        raise items.field_errors([("items", "required")])
    if len(unique) > BULK_APPROVE_MAX:
        raise items.field_errors([("items", "too_many_records")], max=BULK_APPROVE_MAX)
    outcomes: list[BulkOutcome] = []
    for ref in unique:
        try:
            async with session.begin_nested():
                await approvals.decide(
                    session,
                    subject,
                    wtype,
                    ref.record_id,
                    ref.approval_id,
                    decision=rules.Decision.APPROVE,
                    comment=comment,
                    private=False,
                    expected_version=ref.version,
                    channel=channel,
                    source=source,
                )
        except AppError as error:
            outcomes.append(BulkOutcome(ref, decided=False, code=error.instance_code))
        else:
            outcomes.append(BulkOutcome(ref, decided=True))
    return outcomes


__all__ = ["BULK_APPROVE_MAX", "ApprovalRef", "BulkOutcome", "approve_many"]
