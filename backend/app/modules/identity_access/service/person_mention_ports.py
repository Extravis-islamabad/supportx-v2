"""Lane B's mentions ports (ADR-052 S1b, D-171 a): other people's profiles, and file names.

- **identity_access:** other people's profile free text (description, job title, signature)
  that names the person. The person's own row is the erasure's to clear (step 5), so it is
  skipped. The passage needs `users.view` on that person (the description also
  `users.manage`, as the people screens show it).
- **files:** file names only, never contents (attachment contents are not searched; the report
  says so). Redaction renames the file; the passage needs the right to see the file.

Same registry keys as the erasure ports of S1. Mentions only, never text, in what they return.
"""

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules.identity_access.domain import erasure as rules
from app.modules.identity_access.domain.mentions import MentionTerms, count_matches, redact
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.events import UserUpdated
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service import directory
from app.modules.identity_access.service.directory import USER_RECORD_TYPE
from app.modules.identity_access.service.person_data import (
    MENTION_BATCH,
    Mention,
    MentionBatch,
    register_mentions,
)
from app.shared.events import record_event
from app.shared.files.ports import Action
from app.shared.files.service import access as file_access
from app.shared.files.service.cleanup import file_name, live_names, rename_for_erasure
from app.shared.history import Change, record_changes

PROFILE_FIELDS = ("description", "job_title", "signature")
FILE_RECORD_TYPE = "file"
_LIMITS = {"description": 1000, "job_title": 200, "signature": 2000}  # as the table's checks


def _found(
    record_type: str, record_id: uuid.UUID, field: str, text: str | None, terms: MentionTerms
) -> list[Mention]:
    return [
        Mention(record_type, record_id, field, kind, count)
        for kind, count in sorted(count_matches(text, terms).items())
    ]


def _cursor(cursor: str | None) -> uuid.UUID | None:
    return uuid.UUID(cursor) if cursor else None


async def _trashed_user(session: AsyncSession, subject: Subject, user_id: uuid.UUID) -> User | None:
    """A soft-deleted person, for a subject who may erase (its text still names someone).

    The same rule as lane A's ports (#514): trashed rows are read and redacted by
    `people.erase` holders only; live rows keep the users API's own rights.
    """
    if not subject.holds(rules.ERASE_RIGHT):
        return None
    found: User | None = await session.scalar(
        select(User).where(User.id == user_id, User.deleted_at.is_not(None))
    )
    return found


class IdentityAccessMentions:
    """Other people's profiles that name the person."""

    module: ClassVar[str] = "identity_access"

    async def find_mentions(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        terms: MentionTerms,
        cursor: str | None,
    ) -> MentionBatch:
        """One batch of other people's profiles, by ID."""
        query = select(User.id, User.description, User.job_title, User.signature).where(
            User.id != person_id,
            or_(*(getattr(User, name).is_not(None) for name in PROFILE_FIELDS)),
        )
        after = _cursor(cursor)
        if after is not None:
            query = query.where(User.id > after)
        rows = (await session.execute(query.order_by(User.id).limit(MENTION_BATCH))).all()
        found: list[Mention] = []
        for row in rows:
            for name in PROFILE_FIELDS:
                found += _found(USER_RECORD_TYPE, row.id, name, getattr(row, name), terms)
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
        """The matched occurrences in that one profile field become the marker."""
        del now
        if mention.record_type != USER_RECORD_TYPE or mention.field not in PROFILE_FIELDS:
            return False
        user = await session.scalar(
            select(User).where(User.id == mention.record_id).with_for_update()
        )
        text = getattr(user, mention.field) if user is not None else None
        if user is None or not text:
            return False
        new, replaced = redact(text, terms, mention.match_kind, marker)
        if not replaced:
            return False
        if len(new) > _LIMITS[mention.field]:
            # Never cut the text silently (lane A's #506 review): the admin edits it instead.
            raise Conflict(code=rules.REDACTION_TOO_LONG)
        setattr(user, mention.field, new)
        user.version += 1
        await session.flush()
        await record_changes(
            session,
            record_type=USER_RECORD_TYPE,
            record_id=user.id,
            version=user.version,
            kind="updated",
            changes=[Change(mention.field, None, None)],  # never the text being removed
            source="system",
            reason=rules.REDACTION_HISTORY_REASON,
        )
        await record_event(
            session,
            UserUpdated(user_id=user.id, changed_fields=[mention.field], managers=[]),
            aggregate_id=user.id,
            aggregate_version=user.version,
        )
        return True

    async def passage(
        self, session: AsyncSession, subject: Subject, mention: Mention
    ) -> str | None:
        """The field's current text, when the subject may read that person's profile."""
        if mention.record_type != USER_RECORD_TYPE or mention.field not in PROFILE_FIELDS:
            return None
        rule = directory.USERS.field_rules.get(mention.field)  # the users API's own field rules
        if rule is not None and not subject.holds(rule.permission):
            return None
        try:
            user: User | None = await directory.get_user(session, subject, mention.record_id)
        except (NotFound, PermissionDenied):
            user = await _trashed_user(session, subject, mention.record_id)
        if user is None:
            return None
        text: str | None = getattr(user, mention.field)
        return text


class FilesMentions:
    """File names that name the person (never contents)."""

    module: ClassVar[str] = "files"

    async def find_mentions(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        terms: MentionTerms,
        cursor: str | None,
    ) -> MentionBatch:
        """One batch of live files' names, by ID (the person's own uploads too)."""
        del person_id
        rows = await live_names(
            session, after=_cursor(cursor), limit=MENTION_BATCH, include_deleted=True
        )
        found: list[Mention] = []
        for file_id, name in rows:
            found += _found(FILE_RECORD_TYPE, file_id, "name", name, terms)
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
        """The matched occurrences in the file's name become the marker."""
        del now
        if mention.record_type != FILE_RECORD_TYPE or mention.field != "name":
            return False
        return await rename_for_erasure(
            session,
            mention.record_id,
            lambda name: redact(name, terms, mention.match_kind, marker)[0],
            rules.REDACTION_HISTORY_REASON,
            include_deleted=True,  # a trashed file's name still names them (#514's rule)
        )

    async def passage(
        self, session: AsyncSession, subject: Subject, mention: Mention
    ) -> str | None:
        """The file's name, when the subject may see the file (a trashed one: `people.erase`)."""
        if mention.record_type != FILE_RECORD_TYPE or mention.field != "name":
            return None
        live = await file_name(session, mention.record_id)
        if live is None:
            if not subject.holds(rules.ERASE_RIGHT):
                return None
            return await file_name(session, mention.record_id, include_deleted=True)
        try:
            await file_access.authorize(session, subject, mention.record_id, Action.VIEW)
        except (NotFound, PermissionDenied):
            return None
        return live


LANE_B_MENTION_PORTS = (IdentityAccessMentions(), FilesMentions())


def register_lane_b_mention_ports() -> None:
    """Register lane B's mentions ports (identity_access's import does; idempotent)."""
    for port in LANE_B_MENTION_PORTS:
        register_mentions(port)
