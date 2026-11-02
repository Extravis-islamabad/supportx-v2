"""One directory sync run from Microsoft Entra ID (WP-040 session 2; REQ-INT-063, REQ-INT-064).

A run: the connector's own service identity acts (history and `created_by` name it), its sync
app gets a token by client credentials, then

1. groups: the members of the scope groups and of the mapped groups, by delta (bookkeeping in
   `directory_memberships`);
2. users: every changed person, by delta: created, adopted (same address) or updated through
   identity_access, department and site matched by name or code, never created;
3. leavers: removed or disabled people, and people no longer in any scope group, are
   deactivated (sessions end), never deleted; people enabled again are reactivated;
4. managers, once everyone of the round exists; then the mapped SupportX groups follow.

Each page is its own transaction, and the delta links are saved only when the whole run worked:
a run cut short is repeated from the same place, which is safe because applying a change twice
changes nothing. One person a rule refuses is counted and skipped, never the whole run. The run,
its counts and the connector's health go through `runs.record_run` like every connector.
"""

import asyncio
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import AFTER_COMMIT_KEY, Database
from app.core.errors import AppError, Conflict, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access import (
    LeaverOutcome,
    TenantSessionEnder,
    directory_leaver,
    directory_returner,
    sync_directory_person,
    worker_session_ender,
)
from app.modules.integrations.domain.connector_health import RunCounts
from app.modules.integrations.domain.directory import (
    AttributeMapping,
    DirectoryPerson,
    DirectoryRemoval,
    PersonSkipped,
    SkipReason,
    SyncScope,
    from_graph,
    group_mappings_from_json,
    groups_from_json,
    mapping_from_json,
)
from app.modules.integrations.domain.mailboxes import CredentialKind, MailboxProtocol
from app.modules.integrations.infra.graph_directory import (
    DELTA_EXPIRED,
    GRAPH_SCOPE,
    DirectoryUnavailableError,
    GraphDirectory,
)
from app.modules.integrations.infra.imap import MailboxUnavailableError
from app.modules.integrations.infra.models import (
    DirectoryConnector,
    DirectoryMembership,
    DirectoryPersonLink,
)
from app.modules.integrations.infra.oauth import Client
from app.modules.integrations.service import identities, runs, secrets
from app.modules.integrations.service.connections import key_ring, oauth_for
from app.modules.organization import add_member, find_department, find_site, remove_member
from app.shared.files.keyring import KeyRing

log = get_logger(__name__)
CONNECTOR_KIND = "directory"
SECRET_ROLE = "credential"  # noqa: S105 - a role name, not a secret
# No client secret or certificate stored, or it does not open.
SECRET_MISSING = "directory_secret_missing"  # noqa: S105 - a reason code


@dataclass(frozen=True)
class _Config:
    """What a run needs from the connector row, read once."""

    id: uuid.UUID
    identity: uuid.UUID
    client: Client | None
    scope: SyncScope
    scope_groups: frozenset[str]
    mapped: Mapping[str, uuid.UUID]  # directory group -> SupportX group
    mapping: AttributeMapping
    users_link: str | None
    groups_link: str | None
    interval: timedelta


@dataclass
class _Run:
    """A run's tally and what it touched (for managers and group mappings at the end)."""

    counts: Counter[str] = field(default_factory=Counter)
    skips: Counter[str] = field(default_factory=Counter)
    managers: dict[str, str | None] = field(default_factory=dict)  # person -> manager ext. ID
    joined: list[tuple[str, str]] = field(default_factory=list)  # (group, person) added
    left: list[tuple[str, str]] = field(default_factory=list)  # (group, person) removed

    def skip(self, reason: SkipReason) -> None:
        self.skips[reason.value] += 1

    def result(self) -> RunCounts:
        return RunCounts(
            read=self.counts["read"],
            created=self.counts["created"],
            updated=self.counts["updated"],
            skipped=self.counts["skipped"],
            failed=self.counts["failed"],
        )


async def _config(session: AsyncSession, row: DirectoryConnector, ring: KeyRing) -> _Config:
    identity = await identities.ensure_identity(session, CONNECTOR_KIND, row.id, name=row.name)
    secret = await secrets.read_owned(session, ring, row.secret_ref)
    client = (
        None
        if secret is None
        else Client(
            protocol=MailboxProtocol.GRAPH,
            client_id=row.client_id,
            credential_kind=CredentialKind(row.credential_kind),
            credential=secret,
            directory_id=row.directory_tenant,
        )
    )
    return _Config(
        id=row.id,
        identity=identity,
        client=client,
        scope=SyncScope(row.scope),
        scope_groups=frozenset(g.external_id for g in groups_from_json(row.scope_groups)),
        mapped={
            m.external_id: uuid.UUID(m.group_id)
            for m in group_mappings_from_json(row.group_mappings)
        },
        mapping=mapping_from_json(row.mapping),
        users_link=row.users_delta_link,
        groups_link=row.groups_delta_link,
        interval=timedelta(minutes=row.interval_minutes),
    )


def _first_name(values: Mapping[str, Any]) -> str | None:
    """A new person needs a first name: the display name, else the address before the @."""
    display = values.get("display_name")
    if isinstance(display, str) and len(display) <= 100:  # noqa: PLR2004 - the person limit
        return display
    email = values.get("email")
    return email.split("@", 1)[0][:100] if isinstance(email, str) else None


def _codes(error: Exception) -> str:
    if isinstance(error, ValidationFailed):
        return ",".join(sorted({e.code for e in error.errors}))
    return str(getattr(error, "instance_code", type(error).__name__))


class _Sync:
    """One run against one connector; every page in its own transaction as the identity."""

    def __init__(
        self,
        database: Database,
        tenant: uuid.UUID,
        config: _Config,
        end_sessions: TenantSessionEnder | None,
    ) -> None:
        self.database, self.tenant, self.config = database, tenant, config
        self.run = _Run()
        self._end = end_sessions

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        """One transaction as the connector's identity; what waits for the commit runs after."""
        async with self.database.tenant_session(
            TenantContext(self.tenant, self.config.identity)
        ) as session:
            yield session
        # Committed: now the leavers' sessions end (best effort; sign-in refuses them anyway).
        for callback in session.info.pop(AFTER_COMMIT_KEY, ()):
            try:
                await callback()
            except Exception:
                log.warning("directory_after_commit_failed", exc_info=True)

    def _ender(self) -> Callable[[uuid.UUID], Awaitable[None]] | None:
        if self._end is None:
            return None
        end, tenant = self._end, self.tenant

        async def end_one(user_id: uuid.UUID) -> None:
            await end(tenant, user_id)

        return end_one

    # --- groups ---------------------------------------------------------------------------------

    async def groups(self, pages: Any) -> str | None:  # noqa: ANN401 - an async iterator of pages
        link: str | None = None
        async for page in pages:
            async with self._session() as session:
                for item in page.items:
                    await self._group(session, item)
            link = page.delta_link
        return link

    async def _group(self, session: AsyncSession, item: Mapping[str, Any]) -> None:
        group = str(item.get("id") or "")
        members = item.get("members@delta")
        for member in members if isinstance(members, list) else []:
            if not isinstance(member, Mapping) or not isinstance(member.get("id"), str):
                continue
            kind = str(member.get("@odata.type") or "#microsoft.graph.user")
            person = member["id"]
            key = {
                "connector_id": self.config.id,
                "group_external_id": group,
                "external_id": person,
            }
            if "@removed" in member:
                gone = await session.execute(
                    delete(DirectoryMembership).where(
                        *(getattr(DirectoryMembership, k) == v for k, v in key.items())
                    )
                )
                if gone.rowcount:  # type: ignore[attr-defined]  # CursorResult of a DELETE
                    self.run.left.append((group, person))
            elif kind == "#microsoft.graph.user":  # nested groups and devices are not people
                added = await session.execute(
                    insert(DirectoryMembership)
                    .values(tenant_id=self.tenant, **key)
                    .on_conflict_do_nothing()
                )
                if added.rowcount:  # type: ignore[attr-defined]  # CursorResult of an INSERT
                    self.run.joined.append((group, person))

    # --- users ----------------------------------------------------------------------------------

    async def users(self, pages: Any) -> str | None:  # noqa: ANN401 - an async iterator of pages
        link: str | None = None
        async for page in pages:
            async with self._session() as session:
                for item in page.items:
                    await self._user(session, item)
            link = page.delta_link
        return link

    async def _in_scope(self, session: AsyncSession, person: str) -> bool:
        if self.config.scope is SyncScope.ALL_USERS:
            return True
        found = await session.scalar(
            select(DirectoryMembership.external_id)
            .where(
                DirectoryMembership.connector_id == self.config.id,
                DirectoryMembership.external_id == person,
                DirectoryMembership.group_external_id.in_(self.config.scope_groups),
            )
            .limit(1)
        )
        return found is not None

    async def _link(self, session: AsyncSession, person: str) -> DirectoryPersonLink | None:
        return await session.get(DirectoryPersonLink, (self.tenant, self.config.id, person))

    async def _user(self, session: AsyncSession, item: Mapping[str, Any]) -> None:
        change = from_graph(item, self.config.mapping)
        link = await self._link(session, change.external_id)
        if isinstance(change, DirectoryRemoval):
            if link is not None:
                await self._leave(session, link.user_id)
            return
        if not await self._in_scope(session, change.external_id):
            if link is not None:
                await self._leave(session, link.user_id)
            return
        self.run.counts["read"] += 1
        if isinstance(change, PersonSkipped):
            self.run.counts["skipped"] += 1
            self.run.skip(change.reason)
            return
        await self._person(session, change, link)

    async def _values(
        self, session: AsyncSession, change: DirectoryPerson
    ) -> dict[str, Any]:  # Any: text and UUID person values
        values: dict[str, Any] = dict(change.values)
        for _field, reason in change.skipped:
            self.run.skip(reason)
        lookups = (
            ("department", "department_id", find_department, SkipReason.UNKNOWN_DEPARTMENT),
            ("site", "site_id", find_site, SkipReason.UNKNOWN_SITE),
        )
        for ref, column, find, unknown in lookups:
            if ref not in change.refs:
                continue
            name = change.refs[ref]
            if name is None:
                values[column] = None
                continue
            found = await find(session, name)
            if found is None:
                self.run.skip(unknown)  # never created: the admin adds it, the next change maps it
            else:
                values[column] = found
        return values

    async def _person(
        self, session: AsyncSession, change: DirectoryPerson, link: DirectoryPersonLink | None
    ) -> None:
        if link is None and change.enabled is False:
            self.run.counts["skipped"] += 1
            self.run.skip(SkipReason.DISABLED)
            return
        values = await self._values(session, change)
        if link is None and not values.get("first_name"):
            values["first_name"] = _first_name(values)
        try:
            async with session.begin_nested():
                synced = await sync_directory_person(
                    session, link.user_id if link else None, values, directory="entra"
                )
        except (ValidationFailed, Conflict, NotFound) as refused:
            self.run.counts["failed"] += 1
            self.run.skip(SkipReason.REFUSED)
            # Codes only: never a name, an address or a value.
            log.info(
                "directory_person_refused", connector_id=str(self.config.id), code=_codes(refused)
            )
            return
        if link is None:
            link = DirectoryPersonLink(
                tenant_id=self.tenant,
                connector_id=self.config.id,
                external_id=change.external_id,
                user_id=synced.user_id,
            )
            session.add(link)
        if "manager" in change.refs:
            link.manager_external_id = change.refs["manager"]
            self.run.managers[change.external_id] = change.refs["manager"]
        link.updated_at = datetime.now(UTC)
        await session.flush()
        if synced.created:
            self.run.counts["created"] += 1
        elif synced.changed:
            self.run.counts["updated"] += 1
        if change.enabled is True:
            await self._return(session, synced.user_id)
        elif change.enabled is False:
            await self._leave(session, synced.user_id)

    async def _return(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        """Reactivate; a refusal (no technician seat left) is counted, never the run's end."""
        try:
            async with session.begin_nested():
                await directory_returner(session, user_id, directory="entra")
        except AppError as refused:
            self.run.counts["failed"] += 1
            self.run.skip(SkipReason.REFUSED)
            log.info(
                "directory_return_refused", connector_id=str(self.config.id), code=_codes(refused)
            )

    async def _leave(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        outcome = await directory_leaver(
            session, user_id, directory="entra", end_sessions=self._ender()
        )
        if outcome is LeaverOutcome.LEFT:
            self.run.counts["left"] += 1
        elif outcome is LeaverOutcome.LAST_ADMIN_KEPT:
            self.run.skip(SkipReason.LAST_ADMIN)

    # --- after the round ------------------------------------------------------------------------

    async def out_of_scope(self) -> None:
        """People who left the last scope group they were in are leavers."""
        if self.config.scope is not SyncScope.GROUPS:
            return
        candidates = {p for g, p in self.run.left if g in self.config.scope_groups}
        async with self._session() as session:
            for person in sorted(candidates):
                link = await self._link(session, person)
                if link is not None and not await self._in_scope(session, person):
                    await self._leave(session, link.user_id)

    async def managers(self) -> None:
        """Managers once everyone of the round exists (a manager may come after their staff)."""
        async with self._session() as session:
            for person, manager in sorted(self.run.managers.items()):
                link = await self._link(session, person)
                if link is None:
                    continue
                manager_id: uuid.UUID | None = None
                if manager is not None:
                    boss = await self._link(session, manager)
                    if boss is None:
                        self.run.skip(SkipReason.UNKNOWN_MANAGER)
                        continue
                    manager_id = boss.user_id
                try:
                    async with session.begin_nested():
                        await sync_directory_person(
                            session, link.user_id, {"manager_id": manager_id}, directory="entra"
                        )
                except (ValidationFailed, Conflict, NotFound):
                    self.run.skip(SkipReason.REFUSED)  # e.g. a manager loop in the directory

    async def mapped_groups(self) -> None:
        """The mapped SupportX groups follow their directory groups' membership changes."""
        if not self.config.mapped:
            return
        async with self._session() as session:
            for changes, member in ((self.run.joined, True), (self.run.left, False)):
                for group, person in changes:
                    target = self.config.mapped.get(group)
                    link = await self._link(session, person) if target else None
                    if target is None or link is None:
                        continue
                    try:
                        if member:
                            await add_member(session, "group", target, link.user_id)
                        else:
                            await remove_member(session, "group", target, link.user_id)
                    except NotFound:
                        self.run.skip(SkipReason.REFUSED)  # the SupportX group was removed


async def sync_directory(  # noqa: PLR0913 - the connector and its collaborators, explicit
    database: Database,
    settings: Settings,
    tenant: uuid.UUID,
    connector_id: uuid.UUID,
    *,
    ring: KeyRing,
    end_sessions: TenantSessionEnder | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> RunCounts | None:
    """One run now; its counts, or None when the connector is gone or switched off."""
    async with database.tenant_session(TenantContext(tenant)) as session:
        row = await session.get(DirectoryConnector, connector_id)
        if row is None or not row.enabled or row.deleted_at is not None:
            return None
        await session.refresh(row, ["users_delta_link", "groups_delta_link"])
        config = await _config(session, row, ring)
    started = datetime.now(UTC)
    sync = _Sync(database, tenant, config, end_sessions)
    links: tuple[str | None, str | None] = (None, None)
    error: DirectoryUnavailableError | None = None
    try:
        links = await _rounds(settings, config, sync, sleep)
    except DirectoryUnavailableError as exc:
        error = exc
        log.warning("directory_sync_failed", connector_id=str(connector_id), reason=exc.code)
    await _finish(
        database,
        tenant=tenant,
        config=config,
        run=sync.run,
        started=started,
        links=links,
        error=error,
    )
    return sync.run.result()


async def _rounds(
    settings: Settings,
    config: _Config,
    sync: _Sync,
    sleep: Callable[[float], Awaitable[None]],
) -> tuple[str | None, str | None]:
    if config.client is None:
        raise DirectoryUnavailableError(SECRET_MISSING)
    oauth = oauth_for(settings)
    try:
        tokens = await oauth.app_token(config.client, (GRAPH_SCOPE,))
    except MailboxUnavailableError as exc:
        raise DirectoryUnavailableError(exc.reason) from exc
    graph = GraphDirectory(oauth.http(), oauth.endpoints.graph, tokens.access_token, sleep=sleep)
    try:
        group_ids = sorted(config.scope_groups | set(config.mapped))
        groups_link = (
            await sync.groups(graph.groups(config.groups_link, group_ids)) if group_ids else None
        )
        users_link = await sync.users(graph.users(config.users_link, config.mapping.graph_select()))
        await sync.out_of_scope()
        await sync.managers()
        await sync.mapped_groups()
    finally:
        await graph.close()
    return users_link, groups_link


async def _finish(  # noqa: PLR0913 - one run's outcome, explicit
    database: Database,
    *,
    tenant: uuid.UUID,
    config: _Config,
    run: _Run,
    started: datetime,
    links: tuple[str | None, str | None],
    error: DirectoryUnavailableError | None,
) -> None:
    now = datetime.now(UTC)
    async with database.tenant_session(TenantContext(tenant, config.identity)) as session:
        row = await session.get(DirectoryConnector, config.id)
        if row is None:
            return
        if error is None:
            row.users_delta_link, row.groups_delta_link = links
            row.last_synced_at = now
        elif error.code == DELTA_EXPIRED:  # Graph forgot where we were: start again, soon
            row.users_delta_link = row.groups_delta_link = None
        row.next_sync_at = now + (config.interval if error is None else timedelta(minutes=5))
        row.last_skips = dict(run.skips)
        await runs.record_run(
            session,
            CONNECTOR_KIND,
            config.id,
            started_at=started,
            counts=run.result(),
            error_code=None if error is None else error.code,
            auth_failure=error is not None and (error.auth_failure or error.code == SECRET_MISSING),
        )


async def sync_schedule(database: Database, settings: Settings) -> None:
    """Every minute: run the directory connectors that are due, in every tenant."""
    ring = key_ring(settings)
    if ring is None:
        return  # no key ring, no stored secrets: nothing can sign in (the page says so)
    end_sessions = worker_session_ender(settings)
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    now = datetime.now(UTC)
    for tenant in tenants:
        async with database.tenant_session(TenantContext(tenant)) as session:
            due: Sequence[uuid.UUID] = list(
                await session.scalars(
                    select(DirectoryConnector.id).where(
                        DirectoryConnector.enabled.is_(True),
                        DirectoryConnector.deleted_at.is_(None),
                        (DirectoryConnector.next_sync_at.is_(None))
                        | (DirectoryConnector.next_sync_at <= now),
                    )
                )
            )
        for connector_id in due:
            await sync_directory(
                database, settings, tenant, connector_id, ring=ring, end_sessions=end_sessions
            )


__all__ = ["CONNECTOR_KIND", "sync_directory", "sync_schedule"]
