"""The knowledge base's mentions port for a person's erasure (ADR-052 S2, D-171 a; lane C).

Where other people's knowledge text names the person being erased:
- **versions** (`kb_article_version`, each version its own record, older ones too): title,
  body_html (rich text: between tags only), keywords (each item), change_note, internal_note,
  reject_reason;
- **feedback** (`kb_vote`): the comment of someone else's vote (the person's own votes go with
  their erasure);
- **articles** (`kb_article`): the withdrawal reason;
- **topics** (`kb_topic`): the names (each language) and the description.
Type names are admin codes and labels: not searched (the coordinator, 2026-11-14).

A redaction turns the matched words into the reserved marker in that one field. Published and
superseded versions are frozen (0036): their title, body and keywords change only through
`kb_redact_version` (0168), which checks the mention and that nothing but the marker changed.
Every redaction writes history naming the field only (reason `erasure_redaction`), moves the
version on and raises the ordinary saved event, so screens and search follow (search reads a
computed column). A value that would no longer fit is refused, never cut. The passage is the
field's current text for someone whose own rights show it on the article screen: internal and
reject notes, superseded versions and feedback only for those who may edit the article. Trashed
rows (and live rows of a trashed article) are found too; only a holder of `people.erase` reads or
redacts them (#514's rule).
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import String, Text, Uuid

from app.core.errors import AppError, Conflict
from app.modules.identity_access import (
    MENTION_BATCH,
    Mention,
    MentionBatch,
    MentionTerms,
    Subject,
    count_matches,
    count_matches_html,
    redact_html,
    redact_matches,
    register_mentions,
)
from app.modules.knowledge.events import KbArticleSaved, KbTopicSaved
from app.modules.knowledge.infra.models import KbArticle, KbArticleVersion, KbTopic, KbVote
from app.modules.knowledge.service.access import is_staff
from app.modules.knowledge.service.articles import RECORD_TYPE as ARTICLE
from app.modules.knowledge.service.articles import get_article
from app.modules.knowledge.service.topics import NAME_MAX
from app.modules.knowledge.service.topics import RECORD_TYPE as TOPIC
from app.shared.events import record_event
from app.shared.history import Change, record_changes

VERSION = "kb_article_version"
VOTE = "kb_vote"
REDACTION_REASON = "erasure_redaction"  # the history reason code (identity_access's)
REDACTION_TOO_LONG = "erasure_redaction_too_long"  # identity_access's refusal code

# Fields per record type, and which are rich text.
VERSION_FIELDS = ("title", "body_html", "keywords", "change_note", "internal_note", "reject_reason")
FROZEN_FIELDS = frozenset({"title", "body_html", "keywords"})  # only through kb_redact_version
EDITOR_FIELDS = frozenset({"internal_note", "reject_reason"})  # never for readers (REQ-KB-001)
_LIMITS: Mapping[str, int] = {  # the tables' checks
    "title": 250,
    "body_html": 500_000,
    "keywords": 60,  # each keyword
    "change_note": 500,
    "internal_note": 2000,
    "reject_reason": 2000,
    "comment": 1000,
    "withdrawn_reason": 1000,
    "names": NAME_MAX,  # each language
    "description": 1000,
}
PHASES = ("versions", "votes", "articles", "topics")
ERASE_RIGHT = "people.erase"  # the erasure's own right (identity_access)

_REDACT_VERSION = text(
    "SELECT kb_redact_version(:mention, :value, :keywords) AS changed"
).bindparams(
    bindparam("mention", type_=Uuid()),
    bindparam("value", type_=Text()),
    bindparam("keywords", type_=ARRAY(String(60))),
)


def _counts(field: str, value: Any, terms: MentionTerms) -> dict[Any, int]:  # noqa: ANN401 - a column value
    """How often each kind matches in one field (lists and per-language names summed)."""
    if value is None:
        return {}
    if field == "body_html":
        return dict(count_matches_html(str(value), terms))
    pieces = (
        list(value.values())
        if isinstance(value, dict)
        else list(value)
        if isinstance(value, list)
        else [value]
    )
    total: dict[Any, int] = {}
    for piece in pieces:
        for kind, count in count_matches(str(piece), terms).items():
            total[kind] = total.get(kind, 0) + count
    return total


def _mentions(
    record_type: str, record_id: uuid.UUID, fields: Mapping[str, Any], terms: MentionTerms
) -> list[Mention]:
    return [
        Mention(record_type, record_id, name, kind, count)
        for name, value in fields.items()
        for kind, count in sorted(_counts(name, value, terms).items())
    ]


def _fits(field: str, value: str) -> None:
    if len(value) > _LIMITS[field]:
        raise Conflict(code=REDACTION_TOO_LONG)  # never cut (lane A's #506 review)


def _redacted(field: str, value: Any, terms: MentionTerms, mention: Mention, marker: str) -> Any:  # noqa: ANN401 - a column value
    """The field's value with the mention's matches replaced (unchanged where none)."""
    if value is None:
        return None
    if field == "body_html":
        out = redact_html(str(value), terms, mention.match_kind, marker)[0]
        _fits(field, out)
        return out
    if isinstance(value, dict):
        out_map = {
            k: redact_matches(str(v), terms, mention.match_kind, marker)[0]
            for k, v in value.items()
        }
        for item in out_map.values():
            _fits(field, item)
        return out_map
    if isinstance(value, list):
        out_list = [redact_matches(str(v), terms, mention.match_kind, marker)[0] for v in value]
        for item in out_list:
            _fits(field, item)
        return out_list
    out = redact_matches(str(value), terms, mention.match_kind, marker)[0]
    _fits(field, out)
    return out


async def _redact_vote(
    session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str
) -> bool:
    row = await session.scalar(
        select(KbVote).where(KbVote.id == mention.record_id).with_for_update()
    )
    if row is None:
        return False
    new = _redacted("comment", row.comment, terms, mention, marker)
    if new == row.comment:
        return False
    row.comment = new
    await session.flush()
    return True  # feedback keeps no history of its own; the article is unchanged


async def _redact_withdrawal(
    session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str, now: datetime
) -> bool:
    article = await session.scalar(
        select(KbArticle).where(KbArticle.id == mention.record_id).with_for_update()
    )
    if article is None:
        return False
    new = _redacted("withdrawn_reason", article.withdrawn_reason, terms, mention, marker)
    if new == article.withdrawn_reason:
        return False
    article.withdrawn_reason = new
    await _article_saved(session, article, ["withdrawn_reason"], now)
    return True


class KnowledgeMentions:
    """Knowledge text that names the person: versions, feedback, articles, topics."""

    module: ClassVar[str] = "knowledge"

    async def find_mentions(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        terms: MentionTerms,
        cursor: str | None,
    ) -> MentionBatch:
        """One batch of one phase, by ID; the cursor is "<phase>:<last id>"."""
        phase, _, last = (cursor or f"{PHASES[0]}:").partition(":")
        after = uuid.UUID(last) if last else None
        if phase == "versions":
            rows, found = await self._versions(session, terms, after)
        elif phase == "votes":
            rows, found = await self._votes(session, person_id, terms, after)
        elif phase == "articles":
            rows, found = await self._articles(session, terms, after)
        else:
            rows, found = await self._topics(session, terms, after)
        if len(rows) >= MENTION_BATCH:
            return MentionBatch(tuple(found), f"{phase}:{rows[-1]}")
        following = PHASES.index(phase) + 1
        more = f"{PHASES[following]}:" if following < len(PHASES) else None
        return MentionBatch(tuple(found), more)

    @staticmethod
    async def _versions(
        session: AsyncSession, terms: MentionTerms, after: uuid.UUID | None
    ) -> tuple[list[uuid.UUID], list[Mention]]:
        query = select(KbArticleVersion).order_by(KbArticleVersion.id).limit(MENTION_BATCH)
        if after is not None:
            query = query.where(KbArticleVersion.id > after)
        rows = list(await session.scalars(query))
        found = [
            m
            for row in rows
            for m in _mentions(VERSION, row.id, {f: getattr(row, f) for f in VERSION_FIELDS}, terms)
        ]
        return [row.id for row in rows], found

    @staticmethod
    async def _votes(
        session: AsyncSession, person: uuid.UUID, terms: MentionTerms, after: uuid.UUID | None
    ) -> tuple[list[uuid.UUID], list[Mention]]:
        query = (
            select(KbVote.id, KbVote.person_id, KbVote.comment)
            .order_by(KbVote.id)
            .limit(MENTION_BATCH)
        )
        if after is not None:
            query = query.where(KbVote.id > after)
        rows = (await session.execute(query)).all()
        found = [
            m
            for row in rows
            if row.person_id != person  # their own feedback is deleted with them
            for m in _mentions(VOTE, row.id, {"comment": row.comment}, terms)
        ]
        return [row.id for row in rows], found

    @staticmethod
    async def _articles(
        session: AsyncSession, terms: MentionTerms, after: uuid.UUID | None
    ) -> tuple[list[uuid.UUID], list[Mention]]:
        query = (
            select(KbArticle.id, KbArticle.withdrawn_reason)
            .order_by(KbArticle.id)
            .limit(MENTION_BATCH)
        )
        if after is not None:
            query = query.where(KbArticle.id > after)
        rows = (await session.execute(query)).all()
        found = [
            m
            for row in rows
            for m in _mentions(ARTICLE, row.id, {"withdrawn_reason": row.withdrawn_reason}, terms)
        ]
        return [row.id for row in rows], found

    @staticmethod
    async def _topics(
        session: AsyncSession, terms: MentionTerms, after: uuid.UUID | None
    ) -> tuple[list[uuid.UUID], list[Mention]]:
        query = (
            select(KbTopic.id, KbTopic.names, KbTopic.description)
            .order_by(KbTopic.id)
            .limit(MENTION_BATCH)
        )
        if after is not None:
            query = query.where(KbTopic.id > after)
        rows = (await session.execute(query)).all()
        found = [
            m
            for row in rows
            for m in _mentions(
                TOPIC, row.id, {"names": row.names, "description": row.description}, terms
            )
        ]
        return [row.id for row in rows], found

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
        if mention.record_type == VERSION and mention.field in VERSION_FIELDS:
            return await self._redact_version(session, mention, terms, marker, now)
        if mention.record_type == VOTE and mention.field == "comment":
            return await _redact_vote(session, mention, terms, marker)
        if mention.record_type == ARTICLE and mention.field == "withdrawn_reason":
            return await _redact_withdrawal(session, mention, terms, marker, now)
        if mention.record_type == TOPIC and mention.field in ("names", "description"):
            return await self._redact_topic(session, mention, terms, marker, now)
        return False

    @staticmethod
    async def _redact_version(
        session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str, now: datetime
    ) -> bool:
        version = await session.scalar(
            select(KbArticleVersion)
            .where(KbArticleVersion.id == mention.record_id)
            .with_for_update()
        )
        if version is None:
            return False
        before = getattr(version, mention.field)
        new = _redacted(mention.field, before, terms, mention, marker)
        if new == before:
            return False
        if mention.field in FROZEN_FIELDS:
            # The report's own row (identity_access marks it redacted first, #511).
            mention_id = mention.mention_id
            if mention_id is None:
                return False  # only the erasure's own redaction may reach a frozen field
            # The database checks the mention and that only the marker changed (0168).
            changed = await session.scalar(
                _REDACT_VERSION,
                {
                    "mention": mention_id,
                    "value": None if mention.field == "keywords" else new,
                    "keywords": new if mention.field == "keywords" else None,
                },
            )
            if not changed:
                return False
            await session.refresh(version)
        else:
            setattr(version, mention.field, new)
        version.version += 1
        version.updated_at = now
        await session.flush()
        article = await session.scalar(select(KbArticle).where(KbArticle.id == version.article_id))
        if article is not None:
            await _article_saved(session, article, [mention.field], now, language=version.language)
        return True

    @staticmethod
    async def _redact_topic(
        session: AsyncSession, mention: Mention, terms: MentionTerms, marker: str, now: datetime
    ) -> bool:
        topic = await session.scalar(
            select(KbTopic).where(KbTopic.id == mention.record_id).with_for_update()
        )
        if topic is None:
            return False
        before = getattr(topic, mention.field)
        new = _redacted(mention.field, before, terms, mention, marker)
        if new == before:
            return False
        setattr(topic, mention.field, new)
        topic.version += 1
        topic.updated_at = now
        await session.flush()
        await record_changes(
            session,
            record_type=TOPIC,
            record_id=topic.id,
            version=topic.version,
            kind="updated",
            changes=[Change(mention.field, None, None)],
            source="system",
            reason=REDACTION_REASON,
        )
        await record_event(
            session,
            KbTopicSaved(topic_id=topic.id, created=False, changed_fields=[mention.field]),
            aggregate_id=topic.id,
            aggregate_version=topic.version,
        )
        return True

    async def passage(
        self, session: AsyncSession, subject: Subject, mention: Mention
    ) -> str | None:
        """The field's current text, as the subject's own rights show it on the article screen."""
        try:
            return await _passage(session, subject, mention)
        except AppError:
            return None  # not theirs to read (404 / 403): no passage


async def _article_trashed(session: AsyncSession, article_id: uuid.UUID) -> bool:
    deleted = await session.scalar(select(KbArticle.deleted_at).where(KbArticle.id == article_id))
    return deleted is not None


def _erase_holder(subject: Subject) -> bool:
    """Whether the subject may read or redact a trashed row's text (lane B's #516 review).

    Trashed rows, and live rows of a trashed article: only someone who may erase people, as the
    other ports do (#514's rule).
    """
    return subject.holds(ERASE_RIGHT)


async def _topic_passage(session: AsyncSession, subject: Subject, mention: Mention) -> str | None:
    topic = await session.scalar(select(KbTopic).where(KbTopic.id == mention.record_id))
    if topic is None:
        return None
    allowed = _erase_holder(subject) if topic.deleted_at is not None else is_staff(subject)
    return _text(getattr(topic, mention.field)) if allowed else None


async def _vote_passage(session: AsyncSession, subject: Subject, mention: Mention) -> str | None:
    vote = await session.scalar(select(KbVote).where(KbVote.id == mention.record_id))
    if vote is None:
        return None
    if vote.deleted_at is not None or await _article_trashed(session, vote.article_id):
        return vote.comment if _erase_holder(subject) else None
    view = await get_article(session, subject, vote.article_id)
    return vote.comment if view.can_edit else None  # feedback: the article's editors only


async def _withdrawal_passage(
    session: AsyncSession, subject: Subject, mention: Mention
) -> str | None:
    if await _article_trashed(session, mention.record_id):
        if not _erase_holder(subject):
            return None
        return await session.scalar(
            select(KbArticle.withdrawn_reason).where(KbArticle.id == mention.record_id)
        )
    view = await get_article(session, subject, mention.record_id)
    editor = view.can_edit or view.can_withdraw
    return view.article.withdrawn_reason if editor else None


async def _version_passage(session: AsyncSession, subject: Subject, mention: Mention) -> str | None:
    version = await session.scalar(
        select(KbArticleVersion).where(KbArticleVersion.id == mention.record_id)
    )
    if version is None:
        return None
    if version.deleted_at is not None or await _article_trashed(session, version.article_id):
        return _text(getattr(version, mention.field)) if _erase_holder(subject) else None
    view = await get_article(session, subject, version.article_id)
    shown = {v.id: True for v in view.drafts.values()} | {
        v.id: view.can_edit for v in view.published.values()
    }
    # A superseded or rejected version is its editors' history only.
    editor = shown.get(version.id, view.can_edit)
    if version.id not in shown and not view.can_edit:
        return None
    if mention.field in EDITOR_FIELDS and not editor:
        return None
    return _text(getattr(version, mention.field))


_PASSAGES = {
    (TOPIC, "names"): _topic_passage,
    (TOPIC, "description"): _topic_passage,
    (VOTE, "comment"): _vote_passage,
    (ARTICLE, "withdrawn_reason"): _withdrawal_passage,
    **{(VERSION, name): _version_passage for name in VERSION_FIELDS},
}


async def _passage(session: AsyncSession, subject: Subject, mention: Mention) -> str | None:
    read = _PASSAGES.get((mention.record_type, mention.field))
    return None if read is None else await read(session, subject, mention)


def _text(value: Any) -> str | None:  # noqa: ANN401 - a column value
    if value is None:
        return None
    if isinstance(value, dict):
        return "\n".join(str(v) for v in value.values())
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


async def _article_saved(
    session: AsyncSession,
    article: KbArticle,
    fields: Sequence[str],
    now: datetime,
    *,
    language: str | None = None,
) -> None:
    """The article's history (field named only) and its saved event: screens and search follow."""
    article.version += 1
    article.updated_at = now
    await session.flush()
    await record_changes(
        session,
        record_type=ARTICLE,
        record_id=article.id,
        version=article.version,
        kind="updated",
        changes=[Change(name, None, None) for name in fields],
        source="system",
        reason=REDACTION_REASON,
    )
    await record_event(
        session,
        KbArticleSaved(
            article_id=article.id,
            topic_id=article.topic_id,
            owner_id=article.owner_id,
            language=language,
            created=False,
            changed_fields=list(fields),
        ),
        aggregate_id=article.id,
        aggregate_version=article.version,
    )


PORT = KnowledgeMentions()


def register() -> None:
    """Register the port (knowledge's import does; idempotent)."""
    register_mentions(PORT)
