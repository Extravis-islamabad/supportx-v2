"""Where incoming mail goes: the inbound port (WP-024; agreed with lane A, 2026-10-28).

The integrations module reads mailboxes and decides what a message becomes (new record, reply,
nothing); the module that owns the records does the rest with its own rules, registered here at
import (`work_items/service/inbound_mail.py` for incidents):

- `find_record`: the record a message answers, from the subject token ("[INC-12]") or the
  Message-ID of a mail sent about the record;
- `create_from_mail`: a new record with channel "email", the requester as actor, through the
  module's create service (priority, routing, automation as for any new record);
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
class CreatedRecord:
    """A record made from mail (or the follow-up a late reply started)."""

    record_type: str
    record_id: uuid.UUID
    display_id: str


class InboundTarget(Protocol):
    """Registered by the module that owns the records mail turns into."""

    @property
    def record_type(self) -> str:
        """e.g. "incident"."""
        ...

    async def find_record(
        self, session: AsyncSession, *, tokens: Sequence[str], thread_message_ids: Sequence[str]
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
    ) -> CreatedRecord:
        """A new record; InboundRefused when the module's rules refuse it."""
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
    ) -> CreatedRecord | None:
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
