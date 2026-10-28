"""Incidents from mail: the work items side of the inbound port (WP-024; REQ-INC-023).

`integrations` reads mailboxes and decides what a message is; this module owns what it does to an
incident (`app.shared.mail.ports.InboundTarget`):

- `find_record`: the incident a message answers, by its token ("[INC-12]", old prefixes too) or
  by the incidents of the notification e-mails it answers;
- `reply_from_mail`: the requester's public reply through `add_requester_reply`, so the record
  moves as for any requester reply (WP-020f) and an automatic reply only records itself;
- `create_from_mail`: a new incident in the requester's name, channel "email".

Mail runs in a worker, so the requester's subject is compiled now and the policy is the worker's
(`identity_access.subject_for`, `worker_policy`): the same decisions as in the API.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.tenancy import TenantContext
from app.modules.identity_access import subject_for, worker_policy
from app.modules.work_items.domain.types import INCIDENT, parse_display_id
from app.modules.work_items.infra.models import WorkItem
from app.modules.work_items.service import catalogue
from app.modules.work_items.service.conversations import add_requester_reply
from app.shared.mail.ports import CreatedRecord, FoundRecord

RECORD_TYPE = INCIDENT.code.value


def _tenant(session: AsyncSession) -> uuid.UUID:
    context = session.info[SESSION_TENANT_KEY]
    if not isinstance(context, TenantContext):  # pragma: no cover - a tenant session always
        msg = "mail is handled in a tenant session"
        raise TypeError(msg)
    return context.tenant_id


def _found(row: WorkItem) -> FoundRecord:
    people = {row.requester_id, row.on_behalf_of_id} - {None}
    return FoundRecord(RECORD_TYPE, row.id, row.display_id, frozenset(p for p in people if p))


async def _by_token(session: AsyncSession, token: str) -> WorkItem | None:
    cat = await catalogue.load(session, INCIDENT)
    prefix, number = parse_display_id(token, cat.prefix)
    if number is None:
        return None
    row = await session.scalar(
        select(WorkItem).where(
            WorkItem.type == RECORD_TYPE,
            WorkItem.deleted_at.is_(None),
            WorkItem.display_number == number,
        )
    )
    if row is None:
        return None
    # The incident's own prefix, or today's (an old prefix keeps working, REQ-WI-002).
    if prefix is not None and prefix not in {row.display_id.rsplit("-", 1)[0], cat.prefix}:
        return None
    return row


class IncidentsFromMail:
    """`InboundTarget` for incidents."""

    record_type = RECORD_TYPE

    async def find_record(
        self, session: AsyncSession, *, tokens: Sequence[str], record_ids: Sequence[uuid.UUID]
    ) -> FoundRecord | None:
        """The incident named in the subject, else the one the answered mail was about."""
        for token in tokens:
            if (row := await _by_token(session, token)) is not None:
                return _found(row)
        if record_ids:
            row = await session.scalar(
                select(WorkItem).where(
                    WorkItem.type == RECORD_TYPE,
                    WorkItem.deleted_at.is_(None),
                    WorkItem.id.in_(list(record_ids)),
                )
            )
            if row is not None:
                return _found(row)
        return None

    async def reply_from_mail(  # noqa: PLR0913 - the port's fields, explicit
        self,
        session: AsyncSession,
        record: FoundRecord,
        *,
        author_id: uuid.UUID,
        body_html: str,
        automatic: bool,
        message_id: str,
    ) -> CreatedRecord | None:
        """The requester's reply; the follow-up incident when the record was closed too long."""
        del message_id  # the ledger keeps it; the entry is the reply itself
        row = await session.get(WorkItem, record.record_id)
        if row is None:  # pragma: no cover - found in this transaction
            return None
        subject = await subject_for(session, _tenant(session), author_id)
        follow_up = await add_requester_reply(
            session,
            INCIDENT,
            row,
            body=body_html,
            source="email",
            automatic=automatic,
            subject=subject,
            holders=worker_policy(),
        )
        if follow_up is None:
            return None
        return CreatedRecord(RECORD_TYPE, follow_up.id, follow_up.display_id)
