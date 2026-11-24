"""Approve or reject by replying to the approval mail (WP-047a S4; REQ-SR-038).

Integrations hands every fetched reply here first (`app.shared.mail.ports.ApprovalReplies`).
A reply decides only when all of these hold, else nothing changes and the sender is told why:

1. it answers an approval mail (In-Reply-To/References name one this tenant sent; the
   coordinator's condition 2): otherwise it is not an approval reply at all (None);
2. the mailbox's trusted server vouched for the sender (`sender_verified`, as mail commands;
   the coordinator's Q2): `sender_not_verified`;
3. the sender is the person that mail went to (a delegate's mail is the delegate's):
   `wrong_sender`;
4. their approval is still pending and was open when that mail was sent (so a late reply never
   decides a newer round; condition 1): `already_decided`;
5. the reply's first line is a clear decision (`domain.approval_replies`, no AI at V1):
   `unclear`; a stage that asks for a comment needs one: `comment_required`.

Then the decision is the engine's own (`approvals.decide`, as the approver, channel
`email_reply`), with the reply's comment. Every reply, applied or not, is audited. No new
no-sign-in link is ever minted here: the answer points to the app's approvals page.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict, PermissionDenied, ValidationFailed
from app.modules.audit import WORKER as AUDIT_WORKER
from app.modules.audit import AuditActorType
from app.modules.audit import record as record_audit
from app.modules.identity_access import subject_for
from app.modules.notifications import mail_recipients_for
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.approval_replies import read_reply
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval
from app.modules.work_items.service import approvals
from app.modules.work_items.service.request_notifications import REQUESTED
from app.shared.mail.ports import ApprovalReply, register_approval_replies

DECIDED = "service_request.approval_mail_decided"
IGNORED = "service_request.approval_mail_ignored"
NOT_VERIFIED = "sender_not_verified"
WRONG_SENDER = "wrong_sender"
ALREADY_DECIDED = "already_decided"
UNCLEAR = "unclear"
COMMENT_REQUIRED = "comment_required"
NOT_ALLOWED = "not_allowed"  # the engine's own rules refused it (segregation of duties ...)
REASONS = frozenset(
    {NOT_VERIFIED, WRONG_SENDER, ALREADY_DECIDED, UNCLEAR, COMMENT_REQUIRED, NOT_ALLOWED}
)
# Never answered (lane B's #627 condition 1): the From is unverified or not the approver, so an
# answer would be backscatter to a possibly forged address, naming the request. Ledger and audit
# keep them.
SILENT = frozenset({NOT_VERIFIED, WRONG_SENDER})


async def _audit(
    session: AsyncSession, record: WorkItem, reason: str | None, row: WorkItemApproval | None
) -> None:
    # A decision is the approver's own act (lane B's condition 3); an ignored reply is the
    # system's, as nobody verified acted.
    decided_by = row.approver_id if reason is None and row is not None else None
    await record_audit(
        session,
        action_code=DECIDED if reason is None else IGNORED,
        facts=AUDIT_WORKER,
        actor=(AuditActorType.PERSON, decided_by) if decided_by is not None else None,
        object_type="service_request",
        object_id=str(record.id),
        details={
            "display_id": record.display_id,
            **({"approval_id": str(row.id)} if row is not None else {}),
            **({"reason": reason} if reason is not None else {}),
        },
    )


async def _outcome(
    session: AsyncSession,
    record: WorkItem,
    reason: str | None,
    row: WorkItemApproval | None = None,
) -> ApprovalReply:
    await _audit(session, record, reason, row)
    return ApprovalReply(
        SERVICE_REQUEST.code.value,
        record.id,
        record.display_id,
        reason,
        answer_sender=reason not in SILENT,
    )


class ApprovalsFromMail:
    """`ApprovalReplies` for service request approvals."""

    async def decide_from_mail(  # noqa: PLR0911 - one answer per reason, flat
        self,
        session: AsyncSession,
        *,
        thread_ids: Sequence[str],
        sender_id: uuid.UUID | None,
        sender_verified: bool,
        text: str,
    ) -> ApprovalReply | None:
        """The reply's decision (see the module), or None when it answers no approval mail."""
        mails = await mail_recipients_for(session, thread_ids, event_code=REQUESTED)
        if not mails:
            return None
        # The mail that went to this sender, if any; else the thread's first approval mail.
        record_id, recipient_id, sent_at = next((m for m in mails if m[1] == sender_id), mails[0])
        record = await session.get(WorkItem, record_id)
        if record is None or record.deleted_at is not None:
            return None  # gone: an ordinary reply (the record lookup decides what becomes of it)
        if not sender_verified:
            return await _outcome(session, record, NOT_VERIFIED)
        if sender_id != recipient_id:
            return await _outcome(session, record, WRONG_SENDER)
        row = await session.scalar(
            select(WorkItemApproval)
            .where(
                WorkItemApproval.work_item_id == record.id,
                WorkItemApproval.approver_id == recipient_id,
                WorkItemApproval.state == rules.ApprovalState.PENDING.value,
                WorkItemApproval.deleted_at.is_(None),
                WorkItemApproval.created_at <= sent_at,
            )
            .order_by(WorkItemApproval.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if row is None:
            return await _outcome(session, record, ALREADY_DECIDED)
        intent = read_reply(text)
        if intent.decision is None:
            return await _outcome(session, record, UNCLEAR, row)
        if row.comments_required and intent.comment is None:
            return await _outcome(session, record, COMMENT_REQUIRED, row)
        approver = await subject_for(session, record.tenant_id, recipient_id)
        try:
            await approvals.decide(
                session,
                approver,
                SERVICE_REQUEST,
                record.id,
                row.id,
                decision=intent.decision,
                comment=intent.comment,
                private=False,
                expected_version=row.version,
                channel=rules.DecisionChannel.EMAIL_REPLY,
                source="email",
            )
        except (Conflict, PermissionDenied, ValidationFailed) as refused:
            # The engine's own rules (segregation of duties, a closed stage): told, not applied.
            reason = ALREADY_DECIDED if isinstance(refused, Conflict) else NOT_ALLOWED
            return await _outcome(session, record, reason, row)
        except AppError:  # pragma: no cover - any other refusal is still never a 500 for mail
            return await _outcome(session, record, NOT_ALLOWED, row)
        return await _outcome(session, record, None, row)


TARGET = ApprovalsFromMail()


def register() -> None:
    """Replies to approval mail decide (at import, so the mail worker has it too)."""
    register_approval_replies(TARGET)


__all__ = ["DECIDED", "IGNORED", "REASONS", "TARGET", "register"]
