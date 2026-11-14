"""Assets' mentions port for a person's erasure (ADR-052 S1b, D-171 a): notes on assets.

The text people write about assets is their notes (sanitised rich text). A note that names the
person being erased is listed in the erasure's mentions report (where and how often, never the
text); the admin may redact the matched words, which become the reserved marker; the passage
is the note's current text for an admin who may see the asset. Deleted notes are searched too
(their text is still stored) but show no passage, as the notes list shows none.

Other asset text (descriptions, loan and audit comments) is not searched in S1b: it describes
the asset rather than people. Lane B's note in the session log; S2 may add it.
"""

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets.infra.models import AssetNote
from app.modules.assets.service.notes import NOTE_RECORD_TYPE, readable_note_body, redact_note
from app.modules.identity_access import (
    MENTION_BATCH,
    Mention,
    MentionBatch,
    MentionTerms,
    Subject,
    count_matches_html,
    redact_html,
    register_mentions,
)

REDACTION_REASON = "erasure_redaction"  # the history reason code (identity_access's)


class AssetNoteMentions:
    """Asset notes that name the person."""

    module: ClassVar[str] = "assets"

    async def find_mentions(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        terms: MentionTerms,
        cursor: str | None,
    ) -> MentionBatch:
        """One batch of notes, by ID (the person's own notes too: they are about the asset)."""
        del person_id
        query = select(AssetNote.id, AssetNote.body)
        if cursor:
            query = query.where(AssetNote.id > uuid.UUID(cursor))
        rows = (await session.execute(query.order_by(AssetNote.id).limit(MENTION_BATCH))).all()
        found = [
            Mention(NOTE_RECORD_TYPE, note_id, "body", kind, count)
            for note_id, body in rows
            for kind, count in sorted(count_matches_html(body, terms).items())
        ]
        more = len(rows) >= MENTION_BATCH
        return MentionBatch(tuple(found), str(rows[-1][0]) if more else None)

    async def redact_mention(
        self,
        session: AsyncSession,
        mention: Mention,
        *,
        terms: MentionTerms,
        marker: str,
        now: datetime,
    ) -> bool:
        """The matched occurrences in that one note become the marker."""
        del now
        if mention.record_type != NOTE_RECORD_TYPE or mention.field != "body":
            return False
        return await redact_note(
            session,
            mention.record_id,
            lambda body: redact_html(body, terms, mention.match_kind, marker)[0],
            REDACTION_REASON,
        )

    async def passage(
        self, session: AsyncSession, subject: Subject, mention: Mention
    ) -> str | None:
        """The note's current text, when the subject may see its asset."""
        if mention.record_type != NOTE_RECORD_TYPE or mention.field != "body":
            return None
        return await readable_note_body(session, subject, mention.record_id)


PORT = AssetNoteMentions()


def register() -> None:
    """Register the port (assets' import does; idempotent)."""
    register_mentions(PORT)
