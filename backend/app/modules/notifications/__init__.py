"""Notifications module (WP-023, architecture.md §6.8): the one notification engine.

Modules register their notification events and record sources through
`app.shared.notifications.ports`; this module turns committed domain events into in-app entries
and e-mails (through the one mail sender, `app.shared.mail`), with rules, recipients, access at
send time, personal preferences and a delivery log. A core module: every edition has it.

Public interface for other modules: `records_for_mail` (which record a reply answers, for the
email channel, WP-024); otherwise they use the port.
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.notifications.api.routes import router
from app.modules.notifications.events import EVENTS
from app.modules.notifications.service.admin import MANAGE
from app.modules.notifications.service.engine import DISPATCH, waiting_schedule
from app.modules.notifications.service.realtime import ROUTES
from app.modules.notifications.service.threads import records_for_mail
from app.shared.schedules import ScheduleSpec

module = ModuleSpec(
    name="notifications",
    routers=[router],
    events=EVENTS,
    # Tenant admins hold every permission; the rules screen is theirs (and custom roles').
    permissions=(PermissionSpec(MANAGE),),
    realtime=ROUTES,
    consumers=[DISPATCH],
    schedules=[ScheduleSpec("notifications__mail_waiting", 60, waiting_schedule)],
)

__all__ = ["module", "records_for_mail"]
