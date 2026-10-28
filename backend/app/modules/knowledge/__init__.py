"""Knowledge module (WP-033; architecture.md §2.15, §6.1; D-108): the knowledge base.

Topics in a tree, articles with versions per language (English and Arabic at MVP), an in-app
review that needs no mail server, and audiences for technicians (by group) and requesters
(by group, site or department). Session 1: topics, articles and drafts. Session 2: review,
publishing, withdrawal, trash, requesters, notifications. Licensed with the `knowledge` feature.

Public interface for other modules: none yet (session 4 adds links to records).
"""

from app.core.authorization import PermissionSpec, Scope
from app.core.modules import ModuleSpec
from app.modules.knowledge.api.routes import router
from app.modules.knowledge.events import EVENTS
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

module = ModuleSpec(
    name="knowledge",
    routers=[router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
)

__all__ = ["module"]
