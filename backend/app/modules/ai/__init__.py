"""AI module (WP-037, architecture.md §12): the one AI gateway.

Every AI feature calls `Gateway` (on `app.state.ai_gateway`): permissions, the plan, the
switches, masking, the provider and the call log, in that order. Providers stay inside this
module (import-linter). The settings screen is Admin > AI; the call text is cleared after the
tenant's retention period by a daily job.

Public interface for other modules: `Gateway`, `Message`, `Record`, `GATEWAY_STATE`, and
`register_record_access` (each module vouches for its record types; unregistered types are refused).
"""

from fastapi import FastAPI

from app.core.authorization import PermissionSpec
from app.core.config import get_settings
from app.core.modules import ModuleSpec
from app.modules.ai.api.routes import GATEWAY_STATE, router
from app.modules.ai.events import EVENTS
from app.modules.ai.service.calls import purge_sweep
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
from app.shared.schedules import ScheduleSpec

PERMISSIONS = (PermissionSpec(MANAGE, AI_FEATURE),)


async def _startup(app: FastAPI) -> None:
    settings = getattr(app.state, "settings", None) or get_settings()
    setattr(app.state, GATEWAY_STATE, Gateway(provider_from(settings), app.state.db))


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
    consumers=[PERSON_ERASED],
    realtime=ROUTES,
    schedules=[ScheduleSpec("ai__purge_text", 86400, purge_sweep)],
)

__all__ = [
    "GATEWAY_STATE",
    "AiAnswer",
    "Gateway",
    "Message",
    "Record",
    "RecordAccess",
    "module",
    "register_record_access",
    "unregister_record_access",
]
