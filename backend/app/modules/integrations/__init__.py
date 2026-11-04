"""Integrations module (architecture.md §6.1): connections to systems outside SupportX.

WP-024 starts it with support mailboxes: reading mail over IMAP, Microsoft Graph or the Gmail
API, turning it into incidents and replies, and the mail page. Outgoing mail stays
in the one sender, `app.shared.mail` (D-089). WP-040 adds the connector catalogue, which lists
every module's connectors through `app.shared.connectors`.

Public interface for other modules: none yet.
"""

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleSpec
from app.modules.integrations.api.catalogue import catalogue_router
from app.modules.integrations.api.connector_settings import router as connector_settings_router
from app.modules.integrations.api.directories import router as directories_router
from app.modules.integrations.api.ldap_directories import router as ldap_directories_router
from app.modules.integrations.api.routes import oauth_router, router
from app.modules.integrations.events import EVENTS
from app.modules.integrations.infra import models  # noqa: F401 - tables known to Alembic
from app.modules.integrations.service import catalogue, connector_notifications, notifications, runs
from app.modules.integrations.service.directory_sync import sync_schedule
from app.modules.integrations.service.fetching import fetch_schedule
from app.modules.integrations.service.ldap_directories import LDAP_FEDERATION_APPLY
from app.modules.integrations.service.ldap_people import ldap_people_schedule
from app.modules.integrations.service.mailboxes import LEGACY_MANAGE, MANAGE
from app.modules.integrations.service.realtime import ROUTES
from app.shared.connectors.ports import ConnectorCategory
from app.shared.schedules import ScheduleSpec

notifications.register()  # mail admins hear about failing mailboxes (WP-024 session 2)
catalogue.register()  # mailboxes are the catalogue's first connectors (WP-040)
catalogue.register_directories()  # directory sync (WP-040 session 2)
connector_notifications.register()  # failing and recovered connectors (WP-040)

module = ModuleSpec(
    name="integrations",
    routers=[
        router,
        oauth_router,
        catalogue_router,
        directories_router,
        ldap_directories_router,
        connector_settings_router,
    ],
    # Tenant admins hold every permission; mailboxes are theirs (and custom roles').
    permissions=(
        PermissionSpec(MANAGE),
        PermissionSpec(LEGACY_MANAGE),  # replaced by MANAGE; kept until the contract step
        # Directory sync (WP-040 session 2). A category gets its key when its first kind comes.
        PermissionSpec(catalogue.manage_permission(ConnectorCategory.IDENTITY)),
        # Technicians see the catalogue read-only (REQ-INT-013 AC1); set-up is per category.
        PermissionSpec(
            catalogue.VIEW, defaults=(("technician", "all"), ("service_desk_manager", "all"))
        ),
    ),
    schedules=[
        ScheduleSpec("integrations__mail_fetch", 60, fetch_schedule),
        ScheduleSpec("integrations__connector_purge", 86400, runs.purge_schedule),
        # Directory sync: every minute, each connector when due (every 30 minutes, D-118).
        ScheduleSpec("integrations__directory_sync", 60, sync_schedule),
        # AD/LDAP: the people Keycloak imported, into SupportX when due (D-118).
        ScheduleSpec("integrations__ldap_people", 60, ldap_people_schedule),
    ],
    # AD/LDAP: the consumers worker writes each directory into Keycloak (WP-040, D-118).
    consumers=[LDAP_FEDERATION_APPLY],
    events=EVENTS,
    realtime=ROUTES,
)

__all__ = ["module"]
