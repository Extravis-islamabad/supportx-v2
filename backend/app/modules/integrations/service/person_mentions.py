"""Integrations' mentions port for a person's erasure (ADR-052 S2, D-171 a; lane B's answer 6).

Fetched mail keeps its subject in the ledger (`mail_fetched`): a subject someone else sent can
name the person being erased. Only the subject is searched (the bodies are not kept, except
while a message waits for an admin, and the report says so). Mail the person sent is skipped:
their erasure port clears those rows.

A ledger row has no single ID (its key is the mailbox and the message ID), so a mention names it
by a stable UUID made from both (`row_ref`): an identity, never a secret. The passage is for
someone who may set up the email connectors (they see the ledger).
"""

import hashlib
import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import ColumnElement, Text, Uuid, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import (
    MENTION_BATCH,
    Mention,
    MentionBatch,
    MentionTerms,
    Subject,
    count_matches,
    redact_matches,
    register_mentions,
    user_contacts,
)
from app.modules.integrations.infra.models import MailFetched
from app.modules.integrations.service.mailboxes import MANAGE_KEYS
from app.shared.erasure import ERASED_ON_REQUEST

RECORD_TYPE = "mail_fetched"
FIELD = "subject"


def row_ref(mailbox_id: uuid.UUID, message_id: str) -> uuid.UUID:
    """The UUID a ledger row is named by: md5 of its key (as `_ref_sql` computes it)."""
    digest = hashlib.md5(f"{mailbox_id}|{message_id}".encode(), usedforsecurity=False)
    return uuid.UUID(digest.hexdigest())


def _ref_sql() -> ColumnElement[uuid.UUID]:
    """The same UUID in SQL, to find the row a mention names."""
    key = func.concat(cast(MailFetched.mailbox_id, Text), "|", MailFetched.message_id)
    return cast(func.md5(key), Uuid)


async def _row(session: AsyncSession, ref: uuid.UUID, *, lock: bool = False) -> MailFetched | None:
    query = select(MailFetched).where(_ref_sql() == ref)
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)


class MailMentions:
    """Subjects of fetched mail that name the person (sent by someone else)."""

    module: ClassVar[str] = "integrations"

    async def find_mentions(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        terms: MentionTerms,
        cursor: str | None,
    ) -> MentionBatch:
        """One batch of the ledger, by its key; their own mail left to their erasure port."""
        own = {
            email.lower()
            for _, email in (await user_contacts(session, [str(person_id)])).values()
            if email
        } | {e.lower() for e in terms.emails}
        query = select(MailFetched.mailbox_id, MailFetched.message_id, MailFetched.sender,
                       MailFetched.subject)  # fmt: skip
        if cursor:
            mailbox, _, message = cursor.partition("|")
            query = query.where(
                func.row(MailFetched.mailbox_id, MailFetched.message_id)
                > func.row(uuid.UUID(mailbox), message)
            )
        rows = (
            await session.execute(
                query.order_by(MailFetched.mailbox_id, MailFetched.message_id).limit(MENTION_BATCH)
            )
        ).all()
        found = [
            Mention(RECORD_TYPE, row_ref(mailbox_id, message_id), FIELD, kind, count)
            for mailbox_id, message_id, sender, subject in rows
            if sender.lower() not in own and sender != ERASED_ON_REQUEST
            for kind, count in sorted(count_matches(subject, terms).items())
        ]
        last = rows[-1] if len(rows) >= MENTION_BATCH else None
        return MentionBatch(tuple(found), f"{last[0]}|{last[1]}" if last is not None else None)

    async def redact_mention(
        self,
        session: AsyncSession,
        mention: Mention,
        *,
        terms: MentionTerms,
        marker: str,
        now: datetime,
    ) -> bool:
        """The matched words of that one subject become the marker; False if none are left."""
        del now
        if mention.record_type != RECORD_TYPE or mention.field != FIELD:
            return False
        row = await _row(session, mention.record_id, lock=True)
        if row is None:
            return False
        text, replaced = redact_matches(row.subject, terms, mention.match_kind, marker)
        if not replaced:
            return False
        await session.execute(
            update(MailFetched)
            .where(
                MailFetched.mailbox_id == row.mailbox_id,
                MailFetched.message_id == row.message_id,
            )
            # The kept message holds the original Subject header too (lane B's #514 review).
            .values(subject=text, raw=None)
        )
        return True

    async def passage(
        self, session: AsyncSession, subject: Subject, mention: Mention
    ) -> str | None:
        """The subject line, for someone who may set up the email connectors."""
        if mention.record_type != RECORD_TYPE or mention.field != FIELD:
            return None
        if not any(subject.holds(key) for key in MANAGE_KEYS):
            return None
        row = await _row(session, mention.record_id)
        return None if row is None else row.subject


PORT = MailMentions()


def register() -> None:
    """Register the port (integrations' import does; idempotent)."""
    register_mentions(PORT)
