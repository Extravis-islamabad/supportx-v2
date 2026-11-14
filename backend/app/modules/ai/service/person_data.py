"""The AI features' slice of a person's erasure (ADR-052 §4; lane C's S2 port; derived band).

Their AI calls are deleted: the prompts and answers they asked for hold their own words (and the
masked values of others'), and they are the person's own use of the assistant. Counts only.

In the derived band (900s): it runs after the modules whose text an AI answer could have come
from have blanked it. Summaries and embeddings built from the records they requested follow in
the next step, once work_items' `records_requested_by` exists (lane A's S2 port).
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.infra.models import AiCall
from app.modules.identity_access import ERASE_BATCH, ErasureBatch, register_person_data


class AiData:
    """ai: the person's AI calls deleted (band 900, after the text they came from)."""

    module: ClassVar[str] = "ai"
    order: ClassVar[int] = 950
    kinds: ClassVar[frozenset[str]] = frozenset({"ai_calls_deleted"})

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
        """One batch of their AI calls."""
        del successor_id, keep_files, now, cursor
        batch = (
            select(AiCall.id)
            .where(AiCall.user_id == person_id)
            .limit(ERASE_BATCH)
            .scalar_subquery()
        )
        result = await session.execute(delete(AiCall).where(AiCall.id.in_(batch)))
        done = int(getattr(result, "rowcount", 0) or 0)
        return ErasureBatch(
            {"ai_calls_deleted": done}, cursor="calls" if done >= ERASE_BATCH else None
        )


PORT = AiData()


def register() -> None:
    """Make the erasure job erase the AI features' slice (at module import)."""
    register_person_data(PORT)
