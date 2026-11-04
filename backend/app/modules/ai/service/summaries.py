"""Conversation summaries (WP-038, REQ-INC-137), through the gateway.

- The record's owner supplies what this person may see, from the sources the admin chose
  (`register_conversation_source`). With private notes among them the summary is kept at the
  `with_private` level; without, at `public`. The two never mix.
- Made on request (Refresh) through the gateway feature `conversation_summary`: permission, plan,
  switches, masking and the call log apply as for every AI call. Kept until a newer entry makes
  it stale (the consumer below); the page then offers Refresh. The person's own view is checked
  again on every read.
- The prompt asks for facts from the conversation only, never commitments, dates or names that
  are not in it (the eval set checks this, `make ai-eval`).
"""

import uuid

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.modules.ai.events import AiSummaryChanged
from app.modules.ai.infra.models import AiSummary
from app.modules.ai.service.conversations import ConversationText, conversation_source
from app.modules.ai.service.gateway import Gateway, Record
from app.modules.ai.service.providers import Message
from app.modules.ai.service.records import may_see
from app.modules.ai.service.settings import session_tenant, settings_row, summary_sources
from app.modules.identity_access import Subject
from app.shared.events import EventEnvelope, record_event

log = structlog.get_logger(__name__)

FEATURE = "conversation_summary"
WITH_PRIVATE = "with_private"
PUBLIC = "public"
# The conversation text sent, newest entries kept first when it is longer (about 6k tokens).
TEXT_BUDGET = 24_000
SYSTEM = (
    "You summarise an IT service desk conversation for a technician who has not read it. "
    "Write 3 to 6 short bullet points in the language most of the conversation is written in: "
    "the problem, what has been tried, where it stands now, and what is still open. "
    "State only facts written in the conversation. Never add promises, dates, names, numbers "
    "or next steps that are not in it. Placeholders such as ⟦PERSON_1⟧ stand for real values: "
    "keep them exactly as they are."
)


def level_of(sources: tuple[str, ...]) -> str:
    """The summary level a choice of sources gives."""
    return WITH_PRIVATE if "private_notes" in sources else PUBLIC


def prompt_text(conversation: ConversationText) -> str:
    """The conversation as the prompt's text: the newest entries kept within the budget."""
    head = f"Record {conversation.display_id}: {conversation.title}"
    if conversation.description:
        head += f"\n\nDescription:\n{conversation.description}"
    lines: list[str] = []
    used = len(head)
    for entry in reversed(conversation.entries):
        kind = "Reply" if entry.kind == "reply" else "Note"
        if entry.visibility == "private":
            kind = f"Private {kind.lower()}"
        line = f"[{entry.at:%Y-%m-%d %H:%M}] {kind} by {entry.author or 'someone'}:\n{entry.text}"
        if used + len(line) > TEXT_BUDGET:
            lines.append("[earlier entries left out]")
            break
        lines.append(line)
        used += len(line)
    body = "\n\n".join(reversed(lines))
    return f"{head}\n\nConversation, oldest first:\n\n{body}" if body else head


async def _visible(
    session: AsyncSession, subject: Subject, record_type: str, record_id: uuid.UUID
) -> None:
    if not await may_see(session, subject, record_type, record_id):
        raise NotFound(code="ai_record_not_visible")


async def current(
    session: AsyncSession, subject: Subject, record_type: str, record_id: uuid.UUID
) -> AiSummary | None:
    """The record's summary at the level the admin's sources give, if one was made."""
    await _visible(session, subject, record_type, record_id)
    level = level_of(summary_sources(await settings_row(session)))
    found: AiSummary | None = await session.scalar(
        select(AiSummary).where(
            AiSummary.record_type == record_type,
            AiSummary.record_id == record_id,
            AiSummary.level == level,
        )
    )
    return found


async def refresh(
    session: AsyncSession,
    subject: Subject,
    gateway: Gateway,
    record_type: str,
    record_id: uuid.UUID,
) -> AiSummary:
    """Summarise the conversation now (the gateway's checks first) and keep the result."""
    source = conversation_source(record_type)
    if source is None:
        raise NotFound(code="ai_record_not_visible")
    sources = summary_sources(await settings_row(session))
    conversation = await source(session, subject, record_id, sources)
    if not conversation.description and not conversation.entries:
        raise ValidationFailed(code="ai_summary_nothing")
    answer = await gateway.chat(
        session,
        subject,
        feature=FEATURE,
        messages=[Message("system", SYSTEM), Message("user", prompt_text(conversation))],
        record=Record(record_type, record_id),
        names=conversation.names,
        max_tokens=400,
    )
    level = level_of(sources)
    row: AiSummary | None = await session.scalar(
        select(AiSummary).where(
            AiSummary.record_type == record_type,
            AiSummary.record_id == record_id,
            AiSummary.level == level,
        )
    )
    if row is None:
        row = AiSummary(
            id=uuid.uuid4(),
            tenant_id=session_tenant(session),
            record_type=record_type,
            record_id=record_id,
            level=level,
            text=answer.text,
            model=answer.model,
            last_entry_id=conversation.last_entry_id,
            stale=False,
            call_id=answer.call_id,
            version=1,
            created_by=subject.user_id,
            updated_by=subject.user_id,
        )
        session.add(row)
    else:
        row.text = answer.text
        row.model = answer.model
        row.last_entry_id = conversation.last_entry_id
        row.stale = False
        row.call_id = answer.call_id
        row.version += 1
        row.updated_by = subject.user_id
    await session.flush()
    await record_event(
        session,
        AiSummaryChanged(record_type=record_type, record_id=record_id, stale=False),
        aggregate_id=record_id,
        aggregate_version=row.version,
    )
    return row


async def mark_stale(session: AsyncSession, record_id: uuid.UUID) -> int:
    """A newer entry: the record's summaries are no longer current. Returns how many.

    By record ID alone (IDs are unique across record types); one event per record type.
    """
    changed = await session.execute(
        update(AiSummary)
        .where(AiSummary.record_id == record_id, AiSummary.stale.is_(False))
        .values(stale=True, version=AiSummary.version + 1)
        .returning(AiSummary.record_type)
    )
    types = sorted(set(changed.scalars().all()))
    for record_type in types:
        await record_event(
            session,
            AiSummaryChanged(record_type=record_type, record_id=record_id, stale=True),
            aggregate_id=record_id,
        )
    return len(types)


async def erase_all(session: AsyncSession) -> int:
    """A person was erased: summaries may name them, and are remade on request, so all go."""
    removed = await session.execute(delete(AiSummary))
    return int(getattr(removed, "rowcount", 0) or 0)


async def on_conversation_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: a reply or note was added, or a note changed visibility."""
    assert session is not None  # noqa: S101 - transactional consumer
    record_id = uuid.UUID(str(envelope.payload["work_item_id"]))
    if await mark_stale(session, record_id):
        log.info("ai_summary_stale", record_id=str(record_id))
