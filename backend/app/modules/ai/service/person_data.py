"""The AI features' slice of a person's erasure (ADR-052 §4; lane C's S2 port; derived band).

Two phases:
- **texts**: the text of their AI calls (prompts and answers) is cleared; the rows stay, because
  they are the tenant's AI usage and cost record (D-131). This is the same audited, idempotent
  clear that the erasure consumer and the retention purge use (`service/erasure.py`, #188).
- **embeddings**: the vectors of the records they requested (work_items'
  `records_requested_by`, lane A #504) are removed. No text is kept in them, but they are derived
  from the record text, which work_items' port blanks; the re-embed job makes them again from the
  blanked text when a record is next indexed.

In the derived band (900s): it runs after the modules whose text an AI answer or vector came
from. Conversation summaries keep restored names; the erasure consumer deletes them (D-131).
Counts only.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy import delete, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.infra.models import AiEmbedding
from app.modules.ai.service import erasure
from app.modules.identity_access import ErasureBatch, ErasureStepFailed, register_person_data

EMBEDDINGS = "embeddings:"  # the phase's cursor prefix; work_items' own cursor follows it
RECORDS_UNAVAILABLE = "erasure_records_unavailable"

# (session, person, cursor) -> ((record type, record ID) pairs, next cursor or None): the records
# a person requested. work_items registers its `records_requested_by` at start, as it registers
# its embedding sources: ai never imports work_items (it would import ai back; layers, rule e).
RequestedRecords = Callable[
    [AsyncSession, uuid.UUID, str | None],
    Awaitable[tuple[list[tuple[str, uuid.UUID]], str | None]],
]
_requested: list[RequestedRecords] = []


def register_requested_records(lister: RequestedRecords) -> None:
    """The lister of the records a person requested (work_items, at start)."""
    _requested[:] = [lister]


def unregister_requested_records() -> None:
    """Forget it (tests stop the app)."""
    _requested.clear()


async def _embeddings(
    session: AsyncSession, person: uuid.UUID, cursor: str | None
) -> tuple[int, str | None]:
    """One page of their requested records' vectors removed: (rows removed, next cursor)."""
    if not _requested:
        # Never skipped quietly: the erasure retries until work_items has registered (D-171).
        raise ErasureStepFailed(RECORDS_UNAVAILABLE)
    records, following = await _requested[0](session, person, cursor)
    if not records:
        return 0, None
    result = await session.execute(
        delete(AiEmbedding).where(
            tuple_(AiEmbedding.source_type, AiEmbedding.source_id).in_(records)
        )
    )
    return int(getattr(result, "rowcount", 0) or 0), following


class AiData:
    """ai: AI call texts cleared (rows kept), requested records' vectors removed (band 900)."""

    module: ClassVar[str] = "ai"
    order: ClassVar[int] = 950
    kinds: ClassVar[frozenset[str]] = frozenset({"ai_call_texts_cleared", "ai_embeddings_removed"})

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
        """The texts first (one statement, audited when any, D-131), then a page of vectors."""
        del successor_id, keep_files, now
        if cursor is None or not cursor.startswith(EMBEDDINGS):
            cleared = await erasure.erase_person(session, person_id)
            return ErasureBatch({"ai_call_texts_cleared": cleared}, cursor=EMBEDDINGS)
        removed, following = await _embeddings(
            session, person_id, cursor[len(EMBEDDINGS) :] or None
        )
        more = None if following is None else EMBEDDINGS + following
        return ErasureBatch({"ai_embeddings_removed": removed}, cursor=more)


PORT = AiData()


def register() -> None:
    """Make the erasure job erase the AI features' slice (at module import)."""
    register_person_data(PORT)
