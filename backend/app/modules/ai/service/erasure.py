"""A person's AI call text erased with their personal data (GDPR, REQ-ADM-101; lane B, #188).

When identity_access erases a person (`user.status_changed` with reason `erasure`), the text of
every AI call they made is cleared at once, whatever the retention period; the rows keep their
counts and outcomes, like the purge. Other people's calls already hold only masked text.
"""

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.ai.infra.models import AiCall
from app.shared.clock import system_clock
from app.shared.events import ConsumerSpec, EventEnvelope

log = get_logger(__name__)


async def erase_person(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Clear the text of the person's AI calls; returns how many."""
    result = await session.execute(
        update(AiCall)
        .where(AiCall.user_id == user_id, AiCall.text_purged_at.is_(None))
        .values(masked_input=None, output=None, text_purged_at=system_clock.now())
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def on_status_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: a person was erased, so their AI call text goes too."""
    assert session is not None  # noqa: S101 - transactional consumer
    if envelope.payload.get("reason") != "erasure":
        return
    cleared = await erase_person(session, uuid.UUID(str(envelope.payload["user_id"])))
    if cleared:
        log.info("ai_call_text_erased", calls=cleared)


PERSON_ERASED = ConsumerSpec(
    name="ai__person_erased",
    event_types=("identity_access.user.status_changed",),
    handler=on_status_changed,
)
