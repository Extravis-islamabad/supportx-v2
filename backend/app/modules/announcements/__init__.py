"""Announcements module (WP-012, ADR-024): notices for everyone, sites or groups.

Shown in console and portal banners, optionally inside a publish window.

The walking skeleton: the first business entity built end to end through every layer, used as
the template for later modules (docs/architecture/module-template.md). Licensed with the
`incident` feature (the service desk).

Public interface for other modules: none yet.
"""

from app.core.authorization import ALL_SCOPES, PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.announcements.api.routes import router
from app.modules.announcements.events import EVENTS
from app.modules.announcements.service import notifications
from app.modules.announcements.service.announcements import MANAGE, PUBLISH, VIEW
from app.modules.announcements.service.realtime import CHANNELS, ROUTES

FEATURE = "incident"

# Technicians read every announcement and write their own; publishing and the four-eyes setting
# stay with admins (and custom roles) until the product owner says otherwise.
PERMISSIONS = (
    PermissionSpec(
        VIEW,
        FEATURE,
        ALL_SCOPES,
        defaults=(("technician", "all"), ("service_desk_manager", "all"), ("site_admin", "site")),
    ),
    PermissionSpec(
        MANAGE,
        FEATURE,
        ALL_SCOPES,
        defaults=(("technician", "own"), ("service_desk_manager", "all"), ("site_admin", "site")),
    ),
    PermissionSpec(PUBLISH, FEATURE, defaults=(("service_desk_manager", "all"),)),
    PermissionSpec("config.announcements", FEATURE, defaults=(("service_desk_manager", "all"),)),
)

# Followers hear of updates and of the end (WP-032 D7): at import, for the worker too.
notifications.register()

module = ModuleSpec(
    name="announcements",
    routers=[router],
    events=EVENTS,
    feature=FEATURE,
    permissions=PERMISSIONS,
    channels=CHANNELS,
    realtime=ROUTES,
)

__all__ = ["module"]

# GDPR erasure (ADR-052): this module's port; the job refuses to run without it.
from app.modules.announcements.service import person_data as _person_data  # noqa: E402

_person_data.register()

# GDPR erasure (ADR-052 S2): the mentions report searches announcements too (required).
from app.modules.announcements.service import person_mentions as _person_mentions  # noqa: E402

_person_mentions.register()
