"""Announcements' mentions port for a person's erasure (ADR-052 S2, D-171 a; lane C).

An announcement's title and body (plain text) may name the person being erased. Each place is
listed in the erasure's mentions report (where and how often, never the text). On the admin's
request the matched words become the reserved marker: history names the field only (reason
`erasure_redaction`), the version moves on and the ordinary `updated` event is raised, so open
screens follow. A redaction that would no longer fit the field is refused, never cut. The
passage is the field's current text for someone who may see the announcement now.
"""

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.modules.announcements.events import AnnouncementUpdated
from app.modules.announcements.infra.models import Announcement
from app.modules.announcements.service.announcements import RECORD_TYPE, get_announcement
from app.modules.identity_access import (
    MENTION_BATCH,
    Mention,
    MentionBatch,
    MentionTerms,
    Subject,
    count_matches,
    redact_matches,
    register_mentions,
)
from app.shared.events import record_event
from app.shared.history import Change, record_changes

REDACTION_REASON = "erasure_redaction"  # the history reason code (identity_access's)
REDACTION_TOO_LONG = "erasure_redaction_too_long"  # identity_access's refusal code
FIELDS = ("title", "body")
_LIMITS = {"title": 200, "body": 20000}  # the table's checks (announcements_title/body_length)


class AnnouncementMentions:
    """Announcements whose title or body names the person."""

    module: ClassVar[str] = "announcements"

    async def find_mentions(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        terms: MentionTerms,
        cursor: str | None,
    ) -> MentionBatch:
        """One batch of announcements by ID, removed ones too (their text is still stored)."""
        del person_id  # what they wrote stays (D1a); only the words naming them can go
        query = select(Announcement.id, Announcement.title, Announcement.body)
        if cursor:
            query = query.where(Announcement.id > uuid.UUID(cursor))
        rows = (await session.execute(query.order_by(Announcement.id).limit(MENTION_BATCH))).all()
        found = [
            Mention(RECORD_TYPE, row.id, name, kind, count)
            for row in rows
            for name in FIELDS
            for kind, count in sorted(count_matches(getattr(row, name), terms).items())
        ]
        more = len(rows) >= MENTION_BATCH
        return MentionBatch(tuple(found), str(rows[-1].id) if more else None)

    async def redact_mention(
        self,
        session: AsyncSession,
        mention: Mention,
        *,
        terms: MentionTerms,
        marker: str,
        now: datetime,
    ) -> bool:
        """The matched words of that one field become the marker (False: nothing left)."""
        if mention.record_type != RECORD_TYPE or mention.field not in FIELDS:
            return False
        row = await session.scalar(
            select(Announcement).where(Announcement.id == mention.record_id).with_for_update()
        )
        if row is None:
            return False
        before = str(getattr(row, mention.field))
        after, replaced = redact_matches(before, terms, mention.match_kind, marker)
        if replaced == 0 or after == before:
            return False
        if len(after) > _LIMITS[mention.field]:
            raise Conflict(code=REDACTION_TOO_LONG)  # never cut (lane A's #506 review)
        setattr(row, mention.field, after)
        row.version += 1
        row.updated_at = now
        await session.flush()
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=row.id,
            version=row.version,
            kind="updated",
            changes=[Change(mention.field, None, None)],  # the old text is what is removed
            source="system",
            reason=REDACTION_REASON,
        )
        await record_event(
            session,
            AnnouncementUpdated(
                announcement_id=row.id, status=row.status, changed_fields=[mention.field]
            ),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
        return True

    async def passage(
        self, session: AsyncSession, subject: Subject, mention: Mention
    ) -> str | None:
        """The field's current text, when the subject may see the announcement now."""
        if mention.record_type != RECORD_TYPE or mention.field not in FIELDS:
            return None
        try:
            view = await get_announcement(session, subject, mention.record_id)
        except Exception:  # noqa: BLE001 - not visible to them (404) or gone: no passage
            return None
        return str(getattr(view.record, mention.field))


PORT = AnnouncementMentions()


def register() -> None:
    """Register the port (announcements' import does; idempotent)."""
    register_mentions(PORT)
