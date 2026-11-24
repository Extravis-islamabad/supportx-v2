"""Where incoming mail goes: the inbound port (WP-024; agreed with lane A, 2026-10-28).

The integrations module reads mailboxes and decides what a message becomes (new record, reply,
nothing); the module that owns the records does the rest with its own rules, registered here at
import (`work_items/service/inbound_mail.py` for incidents):

- `find_record`: the record a message answers, from the subject token ("[INC-12]") or, when the
  subject lost it, the records of the mail it answers (`record_ids`, from the notification
  delivery log by Message-ID);
- `create_from_mail`: a new record with channel "email", the requester as actor, through the
  module's create service (priority, routing, automation as for any new record); a service
  request of the mailbox's catalog item when it names one (WP-047a S4, REQ-SR-017);
- `reply_from_mail`: a public reply by the requester (or the person it is for), with the
  module's reactions (resume, reopen within the window, or a follow-up record); an automatic
  reply (out-of-office) is recorded with no reaction and no notification.

Refusals come back as `InboundRefused(code)`: the ledger keeps the message as "held" with the
code for an admin, never lost.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class InboundRefused(Exception):
    """The owning module refused the message: admins see the label of `code` on the mail page."""

    def __init__(self, code: str, params: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.params = dict(params or {})  # filled into the code's label on the mail page


@dataclass(frozen=True)
class FoundRecord:
    """A record a message answers."""

    record_type: str
    record_id: uuid.UUID
    display_id: str
    requester_ids: frozenset[uuid.UUID]  # the requester and the person it is for


@dataclass(frozen=True)
class CommandLine:
    """A command written in the mail that was not applied (WP-046a S6; REQ-INC-025)."""

    line: int
    text: str  # as the sender wrote it
    problem: str  # a code; labels: mail_command_problem.<code>


@dataclass(frozen=True)
class CreatedRecord:
    """A record made from mail (or the follow-up a late reply started)."""

    record_type: str
    record_id: uuid.UUID
    display_id: str
    # Commands written in the mail (REQ-INC-025): how many were applied, which were not, and
    # whether they were all set aside because the sender was not verified.
    commands_applied: int = 0
    commands_not_applied: tuple[CommandLine, ...] = ()
    commands_not_verified: bool = False


@dataclass(frozen=True)
class Replied:
    """A reply taken in: its conversation entry, and the follow-up a late reply started."""

    entry_id: uuid.UUID | None  # where the reply's attachments go; None: on the record
    follow_up: CreatedRecord | None = None


class InboundTarget(Protocol):
    """Registered by the module that owns the records mail turns into."""

    @property
    def record_type(self) -> str:
        """e.g. "incident"."""
        ...

    async def find_record(
        self, session: AsyncSession, *, tokens: Sequence[str], record_ids: Sequence[uuid.UUID]
    ) -> FoundRecord | None:
        """The record the message answers, or None."""
        ...

    async def create_from_mail(  # noqa: PLR0913 - the new record's fields, explicit
        self,
        session: AsyncSession,
        *,
        requester_id: uuid.UUID,
        subject: str,
        body_html: str,
        group_id: uuid.UUID | None,
        message_id: str,
        text: str = "",
        sender_verified: bool = False,
        cc: Sequence[str] = (),
        catalog_item_id: uuid.UUID | None = None,
    ) -> CreatedRecord:
        """A new record; InboundRefused when the module's rules refuse it.

        `catalog_item_id` (WP-047a S4, REQ-SR-017): the mailbox makes service requests of this
        catalog item instead of incidents.

        `text`: the mail's plain text, for commands written at its top; `sender_verified`: the
        mailbox's trusted server vouched for the sender (only then may commands apply); `cc`: the
        mail's Cc without our own addresses, who may be kept informed (REQ-INC-066).
        """
        ...

    async def reply_from_mail(  # noqa: PLR0913 - the reply's fields, explicit
        self,
        session: AsyncSession,
        record: FoundRecord,
        *,
        author_id: uuid.UUID,
        body_html: str,
        automatic: bool,
        message_id: str,
    ) -> Replied:
        """The reply on the record; a follow-up record when the record was closed too long."""
        ...


_TARGETS: dict[str, InboundTarget] = {}


def register_inbound_target(target: InboundTarget) -> None:
    """Let mail become records of `target.record_type` (call when the owning module is imported)."""
    _TARGETS[target.record_type] = target


def unregister_inbound_target(record_type: str) -> None:
    """Undo `register_inbound_target` (tests)."""
    _TARGETS.pop(record_type, None)


def inbound_target(record_type: str) -> InboundTarget | None:
    """The target for `record_type`, or None when no module registered one."""
    return _TARGETS.get(record_type)


# --- approval decisions by reply (WP-047a S4; REQ-SR-038) -------------------------------------


@dataclass(frozen=True)
class ApprovalReply:
    """What became of a reply to an approval mail.

    `reason` None: the decision was applied. Otherwise a code (labels
    `mailbox_answer.approval_reply.<reason>`) the sender is told; nothing changed.
    """

    record_type: str
    record_id: uuid.UUID
    display_id: str
    reason: str | None = None
    # False when the sender is unverified or not the approver (lane B's #627 condition 1):
    # answering would be backscatter to a forged From and would leak the request's ID.
    answer_sender: bool = True


class ApprovalReplies(Protocol):
    """Registered by the module that owns approvals (work_items)."""

    async def decide_from_mail(
        self,
        session: AsyncSession,
        *,
        thread_ids: Sequence[str],
        sender_id: uuid.UUID | None,
        sender_verified: bool,
        text: str,
    ) -> ApprovalReply | None:
        """The reply's decision, or None when it answers no approval mail (then: a reply)."""
        ...


_APPROVALS: list[ApprovalReplies] = []


def register_approval_replies(target: ApprovalReplies) -> None:
    """Let replies to approval mail decide (one owner; registering again replaces it)."""
    _APPROVALS[:] = [target]


def approval_replies() -> ApprovalReplies | None:
    """The registered owner, or None."""
    return _APPROVALS[0] if _APPROVALS else None
