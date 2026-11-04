"""AI module (WP-037, architecture.md §12): the one AI gateway.

Every AI feature calls `Gateway` (on `app.state.ai_gateway`): permissions, the plan, the
switches, masking, the provider and the call log, in that order. Providers stay inside this
module (import-linter). The settings screen is Admin > AI; the call text is cleared after the
tenant's retention period by a daily job.

Public interface for other modules: `Gateway`, `Message`, `Record`, `GATEWAY_STATE`, and
`register_record_access` (each module vouches for its record types; unregistered types are refused).
Meaning-based search goes through `Embeddings` (on `app.state.ai_embeddings`): a module indexes its
records' text and registers `register_embedding_source` so a model change can re-embed them.
"""

from fastapi import FastAPI

from app.core.authorization import PermissionSpec
from app.core.config import get_settings
from app.core.modules import ModuleSpec
from app.modules.ai.api.routes import GATEWAY_STATE, router
from app.modules.ai.events import EVENTS
from app.modules.ai.service.calls import purge_sweep
from app.modules.ai.service.conversations import (
    ConversationEntry,
    ConversationSource,
    ConversationText,
    register_conversation_source,
    unregister_conversation_source,
)
from app.modules.ai.service.embeddings import (
    Embeddings,
    Hit,
    TextSource,
    reembed_job,
    register_embedding_source,
    unregister_embedding_source,
)
from app.modules.ai.service.erasure import PERSON_ERASED
from app.modules.ai.service.gateway import AI_FEATURE, AiAnswer, Gateway, Record
from app.modules.ai.service.providers import Message, provider_from
from app.modules.ai.service.realtime import ROUTES
from app.modules.ai.service.records import (
    RecordAccess,
    register_record_access,
    unregister_record_access,
)
from app.modules.ai.service.settings import MANAGE
from app.modules.ai.service.summaries import on_conversation_changed
from app.shared.events import ConsumerSpec
from app.shared.schedules import ScheduleSpec

PERMISSIONS = (PermissionSpec(MANAGE, AI_FEATURE),)


EMBEDDINGS_STATE = "ai_embeddings"


async def _startup(app: FastAPI) -> None:
    settings = getattr(app.state, "settings", None) or get_settings()
    provider = provider_from(settings)
    setattr(app.state, GATEWAY_STATE, Gateway(provider, app.state.db))
    setattr(app.state, EMBEDDINGS_STATE, Embeddings(provider))


async def _shutdown(app: FastAPI) -> None:
    gateway: Gateway | None = getattr(app.state, GATEWAY_STATE, None)
    if gateway is not None:
        await gateway.provider.aclose()


module = ModuleSpec(
    name="ai",
    routers=[router],
    on_startup=[_startup],
    on_shutdown=[_shutdown],
    events=EVENTS,
    permissions=PERMISSIONS,
    consumers=[
        PERSON_ERASED,
        # A newer reply or note makes a record's summary stale (WP-038).
        ConsumerSpec(
            name="ai__summary_stale",
            event_types=(
                "work_items.conversation.added",
                "work_items.conversation.visibility_changed",
            ),
            handler=on_conversation_changed,
        ),
    ],
    realtime=ROUTES,
    schedules=[
        ScheduleSpec("ai__purge_text", 86400, purge_sweep),
        # Vectors of a previous embedding model, re-embedded with the configured one (D-131).
        ScheduleSpec("ai__reembed", 3600, reembed_job),
    ],
)

__all__ = [
    "EMBEDDINGS_STATE",
    "GATEWAY_STATE",
    "AiAnswer",
    "ConversationEntry",
    "ConversationSource",
    "ConversationText",
    "Embeddings",
    "Gateway",
    "Hit",
    "Message",
    "Record",
    "RecordAccess",
    "TextSource",
    "module",
    "register_conversation_source",
    "register_embedding_source",
    "register_record_access",
    "unregister_conversation_source",
    "unregister_embedding_source",
    "unregister_record_access",
]
