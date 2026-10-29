"""Knowledge module (WP-033; architecture.md §2.15, §6.1; D-108): the knowledge base.

Topics in a tree, articles with versions per language (English and Arabic at MVP), an in-app
review that needs no mail server, and audiences for technicians (by group) and requesters
(by group, site or department). Session 1: topics, articles and drafts. Session 2: review,
publishing, withdrawal, trash, requesters, notifications. Licensed with the `knowledge` feature.

Public interface for other modules: none yet (session 4 adds links to records).
"""

from fastapi import FastAPI

from app.core.authorization import PermissionSpec, Scope
from app.core.modules import ModuleSpec
from app.modules.knowledge.api.routes import router
from app.modules.knowledge.events import EVENTS
from app.modules.knowledge.service import notifications
from app.modules.knowledge.service.access import (
    APPROVE,
    CREATE,
    DELETE,
    EDIT_ANY,
    EDIT_OWN,
    MANAGE_SETTINGS,
    MANAGE_TOPICS,
    MANAGE_TYPES,
    SUBMIT,
    VIEW,
    WITHDRAW,
)
from app.modules.knowledge.service.file_access import FILE_ACCESS
from app.modules.knowledge.service.realtime import CHANNELS, ROUTES
from app.shared.files.ports import register_owner_access, unregister_owner_access
from app.shared.schedules import ScheduleSpec

FEATURE = "knowledge"
_READ: tuple[Scope, ...] = ("all", "group", "own")  # own: reading as a requester
_WIDE: tuple[Scope, ...] = ("all", "group")

# D-108 (7): technicians read their groups' knowledge, write, edit their own and submit;
# requesters read what is published for them; approving, withdrawing and the rest are for
# administrators (and the knowledge manager role) by default.
PERMISSIONS = (
    PermissionSpec(VIEW, FEATURE, _READ, defaults=(("technician", "group"), ("requester", "own"))),
    PermissionSpec(CREATE, FEATURE, _WIDE, defaults=(("technician", "group"),)),
    PermissionSpec(EDIT_OWN, FEATURE, ("own",), defaults=(("technician", "own"),)),
    PermissionSpec(EDIT_ANY, FEATURE, _WIDE),
    PermissionSpec(DELETE, FEATURE, _WIDE),
    PermissionSpec(SUBMIT, FEATURE, ("own",), defaults=(("technician", "own"),)),
    PermissionSpec(APPROVE, FEATURE, _WIDE),
    PermissionSpec(WITHDRAW, FEATURE, _WIDE),
    PermissionSpec(MANAGE_TOPICS, FEATURE, ("all",)),
    PermissionSpec(MANAGE_TYPES, FEATURE, ("all",)),
    PermissionSpec(MANAGE_SETTINGS, FEATURE, ("all",)),
)


async def _startup(app: FastAPI) -> None:
    del app
    register_owner_access(FILE_ACCESS)


async def _shutdown(app: FastAPI) -> None:
    del app
    unregister_owner_access(FILE_ACCESS.owner_types)


module = ModuleSpec(
    name="knowledge",
    routers=[router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    channels=CHANNELS,
    realtime=ROUTES,
    on_startup=[_startup],
    on_shutdown=[_shutdown],
    schedules=[ScheduleSpec("knowledge__review_due", 3600, notifications.review_due_sweep)],
)

# Knowledge notifications (REQ-KB-086): at import, for the worker too.
notifications.register()

__all__ = ["module"]
