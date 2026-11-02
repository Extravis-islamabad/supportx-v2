"""Integrations module (architecture.md §6.1): connections to systems outside SupportX.

WP-024 starts it with support mailboxes: reading mail over IMAP (Microsoft Graph and the Gmail
API in session 2), turning it into incidents and replies, and the mail page. Outgoing mail stays
in the one sender, `app.shared.mail` (D-089).

Public interface for other modules: none yet.
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.integrations.api.routes import router
from app.modules.integrations.events import EVENTS
from app.modules.integrations.infra import models  # noqa: F401 - tables known to Alembic
from app.modules.integrations.service.fetching import fetch_schedule
from app.modules.integrations.service.mailboxes import MANAGE
from app.modules.integrations.service.realtime import ROUTES
from app.shared.schedules import ScheduleSpec

module = ModuleSpec(
    name="integrations",
    routers=[router],
    # Tenant admins hold every permission; mailboxes are theirs (and custom roles').
    permissions=(PermissionSpec(MANAGE),),
    schedules=[ScheduleSpec("integrations__mail_fetch", 60, fetch_schedule)],
    events=EVENTS,
    realtime=ROUTES,
)

__all__ = ["module"]
