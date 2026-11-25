"""Tenant addresses as sign-in callbacks of the console and portal clients (ADR-031, plan A).

A sign-in from a tenant's own address keeps its callback there (ADR-031 §4), so Keycloak must
hold each tenant host as a redirect URI and web origin of both clients. This keeps them in step:

- **The consumer** (`organization.domain.changed`, `organization.tenant.provisioned`): adds the
  tenant's wanted addresses, and on a removed or failed domain removes that domain's own entries,
  only when no tenant's verified address is still that host (`tenant_for_host`), so one tenant's
  event never takes away another's address. Idempotent by event ID (the worker's claim); audited
  in the tenant (`identity.client_addresses_changed`).
- **The reconcile** (hourly): every tenant's wanted addresses, then each client's full change.
  It adds what's missing and removes managed entries nobody wants (a stray). If any tenant can't
  be read, that run removes nothing, so a failed read never empties the clients.

**Who writes to Keycloak.** Never the API's identity client (manage-users only). A separate
service account allowed to manage these two clients only (Keycloak fine-grained admin
permissions v2) is the adapter of `ClientAddressAdmin`; it waits on the product owner's OK for
that realm setting, so `admin_factory` gives None and both paths log once and do nothing.
"""

import uuid
from collections.abc import Callable, Iterable
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.audit import WORKER, record
from app.modules.identity_access.domain import client_addresses as rules
from app.modules.identity_access.domain.client_addresses import Addresses, Change, ClientBase
from app.modules.organization import domain_host, host_in_use, tenant_addresses
from app.shared.events import ConsumerSpec, EventEnvelope

log = get_logger(__name__)

ACTION = "identity.client_addresses_changed"
OBJECT_TYPE = "sign_in_client"
DOMAIN_CHANGED = "organization.domain.changed"
TENANT_PROVISIONED = "organization.tenant.provisioned"
# A domain change that can take an address away: it is no longer a verified domain.
GONE = frozenset({"removed", "failed"})
EVERY_SECONDS = 3600


class ClientAddressAdmin(Protocol):
    """Reads and changes the redirect URIs and web origins of one OIDC client."""

    async def current(self, client_id: str) -> Addresses: ...  # noqa: D102

    async def add(self, client_id: str, addresses: Addresses) -> None: ...  # noqa: D102

    async def remove(self, client_id: str, addresses: Addresses) -> None: ...  # noqa: D102


def _no_admin(_settings: Settings) -> ClientAddressAdmin | None:
    # The real adapter waits on fine-grained admin permissions v2 (the product owner's OK).
    return None


admin_factory: Callable[[Settings], ClientAddressAdmin | None] = _no_admin


def clients(settings: Settings) -> tuple[ClientBase, ...]:
    """The console and portal clients, each with the base URL its callbacks derive from."""
    return (
        ClientBase(settings.oidc_console_client_id, settings.console_url),
        ClientBase(settings.oidc_portal_client_id, settings.portal_url),
    )


async def _apply(admin: ClientAddressAdmin, found: Change) -> None:
    if found.add:
        await admin.add(found.client_id, found.add)
    if found.remove:
        await admin.remove(found.client_id, found.remove)


def _details(changes: Iterable[Change]) -> dict[str, object]:
    return {
        c.client_id: {
            "added": sorted(c.add.redirect_uris | c.add.web_origins),
            "removed": sorted(c.remove.redirect_uris | c.remove.web_origins),
        }
        for c in changes
        if c
    }


async def sync_tenant(
    session: AsyncSession,
    admin: ClientAddressAdmin,
    settings: Settings,
    *,
    gone_host: str | None = None,
) -> list[Change]:
    """One tenant's addresses onto both clients; `gone_host` is removed if nobody holds it."""
    mine = await tenant_addresses(session)
    hosts = rules.tenant_hosts(mine.slug, settings.tenant_base_domain, mine.verified_hosts)
    removable: frozenset[str] = frozenset()
    host = rules.normalise_host(gone_host) if gone_host is not None else None
    if (
        host is not None
        and host not in hosts
        and not await host_in_use(session, host, settings.tenant_base_domain)
    ):
        removable = frozenset({host})
    changes = []
    for client in clients(settings):
        found = rules.change(
            client,
            await admin.current(client.client_id),
            rules.wanted(client, hosts),
            removable=removable,
        )
        if found:
            await _apply(admin, found)
            changes.append(found)
    if changes:
        await record(
            session,
            action_code=ACTION,
            facts=WORKER,
            object_type=OBJECT_TYPE,
            details=_details(changes),
        )
    return changes


async def on_address_event(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Consumer: a tenant's address set may have changed."""
    assert session is not None  # noqa: S101 - transactional consumer
    settings = get_settings()
    admin = admin_factory(settings)
    if admin is None:
        log.info("client_addresses_no_admin", event_type=envelope.event_type)
        return
    gone_host: str | None = None
    if envelope.event_type == DOMAIN_CHANGED:
        change = envelope.payload.get("change")
        if change not in GONE | {"verified"}:
            return  # added (pending) or a certificate: no address changes
        if change in GONE:
            gone_host = await domain_host(session, uuid.UUID(str(envelope.payload["domain_id"])))
    # An unreachable Keycloak raises: the worker retries (the claim is rolled back with it).
    await sync_tenant(session, admin, settings, gone_host=gone_host)


CLIENT_ADDRESSES = ConsumerSpec(
    name="identity_access__client_addresses",
    event_types=(DOMAIN_CHANGED, TENANT_PROVISIONED),
    handler=on_address_event,
)


# --- the reconcile -------------------------------------------------------------------------------


async def _tenant_ids(database: Database) -> list[uuid.UUID]:
    async with database.platform_session() as session:
        return list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())


async def reconcile(database: Database, settings: Settings, admin: ClientAddressAdmin) -> int:
    """Every tenant's wanted addresses onto both clients; how many entries changed.

    Adds are audited in the tenant that wants them. Removing a stray (a managed entry no tenant
    wants) is logged with its host: it belongs to no tenant any more.
    """
    wanted_by: dict[str, uuid.UUID] = {}
    complete = True
    for tenant in await _tenant_ids(database):
        try:
            async with database.tenant_session(TenantContext(tenant)) as session:
                mine = await tenant_addresses(session)
        except Exception:  # one tenant's failure never stops the others; it is logged
            log.exception("client_addresses_tenant_unreadable", tenant_id=str(tenant))
            complete = False
            continue
        for host in rules.tenant_hosts(mine.slug, settings.tenant_base_domain, mine.verified_hosts):
            wanted_by.setdefault(host, tenant)
    changed = 0
    added: dict[uuid.UUID, list[Change]] = {}
    for client in clients(settings):
        found = rules.change(
            client, await admin.current(client.client_id), rules.wanted(client, wanted_by)
        )
        if not complete:
            # A tenant we couldn't read may still want a host: remove nothing this run.
            found = Change(found.client_id, found.add, Addresses())
        if not found:
            continue
        await _apply(admin, found)
        changed += len(found.add.redirect_uris | found.add.web_origins)
        changed += len(found.remove.redirect_uris | found.remove.web_origins)
        for entry in found.remove.redirect_uris | found.remove.web_origins:
            log.info("client_addresses_stray_removed", client_id=client.client_id, entry=entry)
        for tenant in {wanted_by[h] for h in _hosts(client, found.add)}:
            mine_only = _only(client, found.add, {h for h, t in wanted_by.items() if t == tenant})
            added.setdefault(tenant, []).append(Change(client.client_id, mine_only, Addresses()))
    for tenant, changes in added.items():
        async with database.tenant_session(TenantContext(tenant)) as session:
            await record(
                session,
                action_code=ACTION,
                facts=WORKER,
                object_type=OBJECT_TYPE,
                details=_details(changes),
            )
    return changed


def _hosts(client: ClientBase, addresses: Addresses) -> set[str]:
    return {
        h
        for e in addresses.redirect_uris | addresses.web_origins
        if (h := rules.managed_host(client, e)) is not None
    }


def _only(client: ClientBase, addresses: Addresses, hosts: set[str]) -> Addresses:
    return Addresses(
        redirect_uris=frozenset(
            e for e in addresses.redirect_uris if rules.managed_host(client, e) in hosts
        ),
        web_origins=frozenset(
            e for e in addresses.web_origins if rules.managed_host(client, e) in hosts
        ),
    )


async def reconcile_schedule(database: Database, settings: Settings) -> None:
    """Hourly: the clients' tenant addresses re-synced from the database."""
    admin = admin_factory(settings)
    if admin is None:
        log.info("client_addresses_no_admin", job="reconcile")
        return
    await reconcile(database, settings, admin)
