"""The AI features' slice of a person's erasure (ADR-052 §4; lane C's S2 port; derived band).

The text of their AI calls (prompts and answers) is cleared; the rows stay, because they are the
tenant's AI usage and cost record (D-131). This is the same audited, idempotent clear that the
erasure consumer and the retention purge use (`service/erasure.py`, #188). Counts only.

In the derived band (900s): it runs after the modules whose text an answer could have come from.
Conversation summaries keep restored names; the erasure consumer deletes them (D-131).
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.service import erasure
from app.modules.identity_access import ErasureBatch, register_person_data


class AiData:
    """ai: the text of the person's AI calls cleared, the rows kept (band 900)."""

    module: ClassVar[str] = "ai"
    order: ClassVar[int] = 950
    kinds: ClassVar[frozenset[str]] = frozenset({"ai_call_texts_cleared"})

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """All their AI call texts in one statement (audited when any, D-131)."""
        del successor_id, keep_files, now, cursor
        cleared = await erasure.erase_person(session, person_id)
        return ErasureBatch({"ai_call_texts_cleared": cleared}, cursor=None)


PORT = AiData()


def register() -> None:
    """Make the erasure job erase the AI features' slice (at module import)."""
    register_person_data(PORT)
