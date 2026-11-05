"""Writing help in the reply and note editors (WP-038, REQ-INC-136), through the gateway.

Two modes, each its own AI feature (and switch):
- `draft` (`reply_draft`): a reply or note written from the person's instruction.
- `improve` (`text_improve`): the person's own text made correct, shorter, longer, more formal
  or friendlier, or translated between English, Arabic and Urdu.

The prompt holds only what the person may see of the record (its owner's conversation reader,
REQ-AI-025) and their instruction. A reply goes to the requester, so private notes are never
read for it, whatever the admin chose for summaries; a note may read them when the admin chose
them. The answer only ever goes to a review panel: nothing is sent or saved here. The prompt
forbids promises, dates, names and numbers that are not in the conversation (`make ai-eval`
checks it).
"""

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.modules.ai.domain.prompts import RULES
from app.modules.ai.service.conversations import conversation_source
from app.modules.ai.service.gateway import AiAnswer, Gateway, Record
from app.modules.ai.service.providers import Message
from app.modules.ai.service.settings import settings_row, summary_sources
from app.modules.ai.service.summaries import prompt_text
from app.modules.identity_access import Subject

Mode = Literal["draft", "improve"]
Kind = Literal["reply", "note"]
Style = Literal["correct", "shorter", "longer", "formal", "friendly", "translate"]
Language = Literal["en", "ar", "ur"]

FEATURES: dict[Mode, str] = {"draft": "reply_draft", "improve": "text_improve"}
LANGUAGE_NAMES: dict[Language, str] = {"en": "English", "ar": "Arabic", "ur": "Urdu"}
INSTRUCTION_MAX = 1000
TEXT_MAX = 8000

STYLES: dict[Style, str] = {
    "correct": "Correct its spelling, grammar and punctuation. Change nothing else.",
    "shorter": "Make it shorter and clearer, keeping every fact.",
    "longer": "Make it fuller and clearer, adding no new facts.",
    "formal": "Make it more formal and polite, keeping every fact.",
    "friendly": "Make it warmer and friendlier, keeping every fact.",
    "translate": "Translate it, keeping every fact and the meaning exactly.",
}


def _language_line(language: Language | None) -> str:
    if language is None:
        return "Write in the language the person wrote their instruction or text in."
    return f"Write in {LANGUAGE_NAMES[language]}."


def messages_for(  # noqa: PLR0913 - the request's parts, explicit
    *,
    mode: Mode,
    kind: Kind,
    record_text: str,
    instruction: str | None,
    text: str | None,
    style: Style | None,
    language: Language | None,
) -> list[Message]:
    """The prompt: the rules, the record as the person sees it, and their request."""
    audience = (
        "a reply to the requester (they will read it)"
        if kind == "reply"
        else "an internal note for other technicians"
    )
    if mode == "draft":
        system = (
            f"You help an IT service desk technician write {audience}. {RULES} "
            f"{_language_line(language)}"
        )
        request = f"Write it from this instruction:\n{instruction}"
    else:
        chosen = style or "correct"
        target = (
            _language_line(language)
            if chosen == "translate"
            else ("Keep the language it is written in.")
        )
        system = (
            f"You improve {audience} written by an IT service desk technician. {RULES} "
            f"{STYLES[chosen]} {target}"
        )
        request = f"The text:\n{text}"
    return [
        Message("system", system),
        Message("user", f"The record, as the technician sees it:\n\n{record_text}"),
        Message("user", request),
    ]


async def write(  # noqa: PLR0913 - the request's parts, explicit
    session: AsyncSession,
    subject: Subject,
    gateway: Gateway,
    *,
    record_type: str,
    record_id: uuid.UUID,
    mode: Mode,
    kind: Kind,
    instruction: str | None = None,
    text: str | None = None,
    style: Style | None = None,
    language: Language | None = None,
) -> AiAnswer:
    """A draft or an improved text for the review panel (the gateway's checks first)."""
    if mode == "draft" and not (instruction or "").strip():
        raise ValidationFailed(code="ai_writing_instruction_required")
    if mode == "improve" and not (text or "").strip():
        raise ValidationFailed(code="ai_writing_text_required")
    if style == "translate" and language is None:
        raise ValidationFailed(code="ai_writing_language_required")
    source = conversation_source(record_type)
    if source is None:
        raise NotFound(code="ai_record_not_visible")
    chosen = summary_sources(await settings_row(session))
    # A reply reaches the requester: private notes never feed it (REQ-AI-025, D-077).
    sources = tuple(s for s in chosen if s != "private_notes") if kind == "reply" else chosen
    conversation = await source(session, subject, record_id, sources)
    return await gateway.chat(
        session,
        subject,
        feature=FEATURES[mode],
        messages=messages_for(
            mode=mode,
            kind=kind,
            record_text=prompt_text(conversation),
            instruction=(instruction or "").strip()[:INSTRUCTION_MAX] or None,
            text=(text or "").strip()[:TEXT_MAX] or None,
            style=style,
            language=language,
        ),
        record=Record(record_type, record_id),
        names=conversation.names,
        max_tokens=700,
    )
