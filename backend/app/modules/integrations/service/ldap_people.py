"""The people of an AD/LDAP directory into SupportX (WP-040, D-118).

Keycloak imports the directory's people (every 30 minutes for changes, daily in full). This
schedule then reads the users that directory's component holds and keeps SupportX's people as
the directory says, through the same engine and rules as Entra
(`directory_sync._Sync`): new people are made, changes are applied, a person disabled in the
directory is a leaver, and one gone from it is a leaver too. Every person is read on every run
(Keycloak has no delta), so a full read decides who has gone.

A run that finds nobody while SupportX still keeps people from this directory changes no one:
an empty answer is far more likely a broken search base than everyone leaving at once.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access import (
    FederationFailed,
    FederationNotInstalled,
    TenantSessionEnder,
    federated_users,
    worker_session_ender,
)
from app.modules.integrations.domain.connector_health import RunCounts
from app.modules.integrations.domain.directory import SyncScope, mapping_from_json
from app.modules.integrations.domain.ldap import from_keycloak
from app.modules.integrations.infra.graph_directory import DirectoryUnavailableError
from app.modules.integrations.infra.models import DirectoryConnector, DirectoryPersonLink
from app.modules.integrations.service import identities
from app.modules.integrations.service.directory_sync import (
    CONNECTOR_KIND,
    _Config,
    _finish,
    _Sync,
)
from app.modules.integrations.service.ldap_directories import APPLIED, LDAP, ldap_settings

log = get_logger(__name__)

PAGE = 100  # people per transaction
NOBODY_FOUND = "ldap_no_people_found"


async def _config(
    database: Database, tenant: uuid.UUID, directory_id: uuid.UUID
) -> tuple[_Config, str, int] | None:
    """The run's configuration, the component and how many people SupportX keeps from it."""
    async with database.tenant_session(TenantContext(tenant)) as session:
        row = await session.get(DirectoryConnector, directory_id)
        if (
            row is None
            or row.source != LDAP
            or not row.enabled
            or row.deleted_at is not None
            or row.federation_state != APPLIED
            or row.keycloak_component_id is None
        ):
            return None
        identity = await identities.ensure_identity(session, CONNECTOR_KIND, row.id, name=row.name)
        kept = await session.scalar(
            select(func.count()).where(DirectoryPersonLink.connector_id == row.id)
        )
        config = _Config(
            id=row.id,
            identity=identity,
            client=None,
            scope=SyncScope.ALL_USERS,
            scope_groups=frozenset(),
            mapped={},
            mapping=mapping_from_json({}),
            users_link=None,
            groups_link=None,
            interval=timedelta(seconds=ldap_settings(row).changed_sync_seconds),
            source="ldap",
        )
        return config, row.keycloak_component_id, int(kept or 0)


async def sync_ldap_people(
    database: Database,
    settings: Settings,
    tenant: uuid.UUID,
    directory_id: uuid.UUID,
    *,
    end_sessions: TenantSessionEnder | None = None,
) -> RunCounts | None:
    """One run now; its counts, or None when the directory is gone, off or not connected yet."""
    found = await _config(database, tenant, directory_id)
    if found is None:
        return None
    config, component_id, kept = found
    started = datetime.now(UTC)
    sync = _Sync(database, tenant, config, end_sessions)
    error: DirectoryUnavailableError | None = None
    try:
        users = await federated_users(settings, component_id)
    except (FederationFailed, FederationNotInstalled) as exc:
        users, error = [], DirectoryUnavailableError(exc.code)
    if error is None and not users and kept:
        error = DirectoryUnavailableError(NOBODY_FOUND)  # never make everyone a leaver at once
    if error is None:
        seen: set[str] = set()
        for start in range(0, len(users), PAGE):
            async with sync._session() as session:  # noqa: SLF001 - the shared engine's unit
                for user in users[start : start + PAGE]:
                    change = from_keycloak(user)
                    seen.add(change.external_id)
                    await sync.change(session, change)
        await sync.removed_except(seen)
    else:
        log.warning("ldap_people_sync_failed", directory_id=str(directory_id), code=error.code)
    await _finish(
        database,
        tenant=tenant,
        config=config,
        run=sync.run,
        started=started,
        links=(None, None),
        error=error,
    )
    return sync.run.result()


async def ldap_people_schedule(database: Database, settings: Settings) -> None:
    """Every minute: read the people of the AD/LDAP directories that are due, in every tenant."""
    end_sessions = worker_session_ender(settings)
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    now = datetime.now(UTC)
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            due: list[uuid.UUID] = list(
                await session.scalars(
                    select(DirectoryConnector.id).where(
                        DirectoryConnector.source == LDAP,
                        DirectoryConnector.enabled.is_(True),
                        DirectoryConnector.deleted_at.is_(None),
                        DirectoryConnector.federation_state == APPLIED,
                        (DirectoryConnector.next_sync_at.is_(None))
                        | (DirectoryConnector.next_sync_at <= now),
                    )
                )
            )
        for directory_id in due:
            await sync_ldap_people(
                database, settings, tenant, directory_id, end_sessions=end_sessions
            )


__all__ = ["ldap_people_schedule", "sync_ldap_people"]
