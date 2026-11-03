"""Directory connectors: set up, change, remove, "sync now" (WP-040 session 2; REQ-INT-063).

Microsoft Entra ID through the customer's own least-privilege sync app (WP-040 plan decision
2): its tenant, client ID and a client secret or certificate (sealed in the secrets store, never
shown again: only its type, age and "ending in ..a3f9"). Who is synced (everyone, or members of
chosen groups), how attributes map, which directory groups fill which SupportX groups, and how
often (every 30 minutes by default, D-118; 15 minutes to a day).

Every change is recorded through the outbox in the same transaction (`DirectoryChanged`), so the
connector page and the catalogue update live. Removing a connector stops its sync and disables
its service identity; the people it brought stay, and SupportX keeps them from then on.
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Conflict, FieldError, NotFound, ServiceUnavailable, ValidationFailed
from app.modules.identity_access import Subject, check_group_grantable, release_from_directory
from app.modules.integrations.domain.connector_health import SYNC_MINUTES
from app.modules.integrations.domain.directory import (
    ATTRIBUTES,
    EmailFrom,
    SyncScope,
    group_mappings_from_json,
    groups_from_json,
    mapping_from_json,
)
from app.modules.integrations.domain.mailboxes import CredentialKind, MailboxProtocol
from app.modules.integrations.events import DirectoryChanged
from app.modules.integrations.infra.graph_directory import (
    GRAPH_SCOPE,
    DirectoryUnavailableError,
    GraphDirectory,
)
from app.modules.integrations.infra.imap import MailboxUnavailableError
from app.modules.integrations.infra.models import DirectoryConnector, DirectoryPersonLink
from app.modules.integrations.infra.oauth import Client, load_certificate
from app.modules.integrations.service import identities, secrets
from app.modules.integrations.service.connections import key_ring, oauth_for
from app.modules.integrations.service.directory_sync import CONNECTOR_KIND, SECRET_ROLE
from app.modules.integrations.service.mailboxes import KeyRingMissing
from app.modules.organization import existing_unit_ids
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.ids import new_id

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DOMAIN = re.compile(r"^(?=.{4,200}$)[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
MIN_MINUTES, MAX_MINUTES = 15, 1440
MAX_GROUPS = 100  # scope groups and mappings each: a screen, not a bulk import
SECRET_TYPES = {CredentialKind.SECRET: "client_secret", CredentialKind.CERTIFICATE: "certificate"}


class DirectoryRepository(Repository[DirectoryConnector]):
    """Directory connectors of the session's tenant (version checks, soft delete)."""

    model = DirectoryConnector


@dataclass(frozen=True)
class DirectoryView:
    """What the connector page shows: never the secret, only what may be said about it."""

    row: DirectoryConnector
    secret: secrets.SecretInfo | None
    people: int


def _error(field: str, code: str) -> FieldError:
    return FieldError(field=f"body.{field}", code=code, message_key=f"errors.{code}")


def _text(values: Mapping[str, Any], name: str, limit: int) -> str | None:
    value = values.get(name)
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= limit else None


def _problems(  # noqa: C901, PLR0912 - one check per field, in screen order
    values: Mapping[str, Any], *, credential: str | None, creating: bool
) -> list[FieldError]:
    errors: list[FieldError] = []
    if _text(values, "name", 200) is None:
        errors.append(_error("name", "required"))
    tenant = _text(values, "directory_tenant", 200)
    if tenant is None or not (_GUID.match(tenant) or _DOMAIN.match(tenant)):
        errors.append(_error("directory_tenant", "directory_tenant_invalid"))
    client = _text(values, "client_id", 200)
    if client is None or not _GUID.match(client):
        errors.append(_error("client_id", "client_id_invalid"))
    kind = values.get("credential_kind")
    if kind not in set(CredentialKind):
        errors.append(_error("credential_kind", "invalid_choice"))
    if creating and not credential:
        errors.append(_error("credential", "required"))
    elif credential and kind == CredentialKind.CERTIFICATE:
        try:
            load_certificate(credential)
        except MailboxUnavailableError:
            errors.append(_error("credential", "certificate_invalid"))
    scope = values.get("scope")
    if scope not in set(SyncScope):
        errors.append(_error("scope", "invalid_choice"))
    groups = groups_from_json(values.get("scope_groups", []))
    if scope == SyncScope.GROUPS and not groups:
        errors.append(_error("scope_groups", "directory_groups_required"))
    mapped = group_mappings_from_json(values.get("group_mappings", []))
    for name, items in (("scope_groups", groups), ("group_mappings", mapped)):
        if len(items) > MAX_GROUPS or any(not _GUID.match(g.external_id) for g in items):
            errors.append(_error(name, "directory_group_invalid"))
    if any(not _GUID.match(m.group_id) for m in mapped):
        errors.append(_error("group_mappings", "group_not_found"))
    mapping = values.get("mapping", {})
    if (
        not isinstance(mapping, Mapping)
        or any(
            mapping.get(key) is not None and mapping.get(key) not in ATTRIBUTES
            for key in ("department_from", "site_from")
        )
        or mapping.get("email_from", EmailFrom.MAIL) not in set(EmailFrom)
    ):
        errors.append(_error("mapping", "invalid_choice"))
    minutes = values.get("interval_minutes", SYNC_MINUTES)
    if not isinstance(minutes, int) or not MIN_MINUTES <= minutes <= MAX_MINUTES:
        errors.append(_error("interval_minutes", "out_of_range"))
    return errors


async def _groups_exist(session: AsyncSession, values: Mapping[str, Any], by: Subject) -> None:
    wanted = {
        uuid.UUID(m.group_id) for m in group_mappings_from_json(values.get("group_mappings", []))
    }
    if wanted and await existing_unit_ids(session, "group", sorted(wanted)) != wanted:
        raise ValidationFailed(errors=[_error("group_mappings", "group_not_found")])
    # Sync adds people to these groups with no person behind it, so whoever maps a directory group
    # onto a SupportX group that carries roles must be able to give those roles (lane B, WP-042).
    for group in sorted(wanted):
        await check_group_grantable(session, by, group)


def _stored(values: Mapping[str, Any]) -> dict[str, Any]:
    """The columns a request sets (validated before)."""
    mapping = mapping_from_json(values.get("mapping") or {})
    return {
        "name": str(values["name"]).strip(),
        "directory_tenant": str(values["directory_tenant"]).strip(),
        "client_id": str(values["client_id"]).strip().lower(),
        "credential_kind": str(values["credential_kind"]),
        "scope": str(values["scope"]),
        "scope_groups": [
            {"external_id": g.external_id, "name": g.name[:200]}
            for g in groups_from_json(values.get("scope_groups", []))
        ],
        "group_mappings": [
            {"external_id": m.external_id, "name": m.name[:200], "group_id": m.group_id}
            for m in group_mappings_from_json(values.get("group_mappings", []))
        ],
        "mapping": {
            "email_from": mapping.email_from.value,
            "department_from": mapping.department_from,
            "site_from": mapping.site_from,
            "include_guests": mapping.include_guests,
        },
        "interval_minutes": int(values.get("interval_minutes", SYNC_MINUTES)),
        "enabled": values.get("enabled", True) is not False,
    }


async def _announce(
    session: AsyncSession,
    row: DirectoryConnector,
    change: Literal["added", "changed", "removed", "synced"],
) -> None:
    await record_event(
        session,
        DirectoryChanged(directory_id=row.id, change=change),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def _view(session: AsyncSession, row: DirectoryConnector) -> DirectoryView:
    info = await secrets.credential_info_of(session, row.secret_ref)
    people = await session.scalar(
        select(func.count()).where(DirectoryPersonLink.connector_id == row.id)
    )
    return DirectoryView(row=row, secret=info, people=int(people or 0))


def _ring(settings: Settings) -> Any:  # noqa: ANN401 - a KeyRing
    ring = key_ring(settings)
    if ring is None:
        raise KeyRingMissing
    return ring


async def create_directory(
    session: AsyncSession,
    settings: Settings,
    values: Mapping[str, Any],
    *,
    credential: str | None,
    by: Subject,
) -> DirectoryView:
    """A new directory connector; its first sync runs within a minute."""
    if errors := _problems(values, credential=credential, creating=True):
        raise ValidationFailed(errors=errors)
    ring = _ring(settings)
    await _groups_exist(session, values, by)
    stored = _stored(values)
    row = DirectoryConnector(id=new_id(), **stored)
    try:
        row = await DirectoryRepository(session).add(row)
    except Exception as exc:  # the partial unique index on the name
        raise Conflict(code="directory_name_taken") from exc
    assert credential is not None  # noqa: S101 - _problems requires it on create
    row.secret_ref = await secrets.put_owned(
        session,
        ring,
        owner_kind=CONNECTOR_KIND,
        owner_id=row.id,
        role=SECRET_ROLE,
        secret_type=SECRET_TYPES[CredentialKind(row.credential_kind)],
        value=credential,
    )
    await identities.ensure_identity(session, CONNECTOR_KIND, row.id, name=row.name)
    await session.flush()
    await _announce(session, row, "added")
    return await _view(session, row)


async def update_directory(  # noqa: PLR0913 - the record, the version and the change, explicit
    session: AsyncSession,
    settings: Settings,
    directory_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    credential: str | None,
    by: Subject,
) -> DirectoryView:
    """Change a connector (If-Match); a new secret replaces the old one behind the same row."""
    if errors := _problems(values, credential=credential, creating=False):
        raise ValidationFailed(errors=errors)
    await _groups_exist(session, values, by)
    current = await DirectoryRepository(session).get(directory_id)
    stored = _stored(values)
    # Who is synced changed: the next round reads everyone again (delta links start over).
    if (stored["scope"], stored["scope_groups"], stored["group_mappings"], stored["mapping"]) != (
        current.scope,
        current.scope_groups,
        current.group_mappings,
        current.mapping,
    ):
        stored["users_delta_link"] = stored["groups_delta_link"] = None
    row = await DirectoryRepository(session).update(
        directory_id, expected_version=expected_version, changes=stored
    )
    if credential:
        row.secret_ref = await secrets.put_owned(
            session,
            _ring(settings),
            owner_kind=CONNECTOR_KIND,
            owner_id=row.id,
            role=SECRET_ROLE,
            secret_type=SECRET_TYPES[CredentialKind(row.credential_kind)],
            value=credential,
        )
        row.next_sync_at = None  # try the new secret at once
    await identities.set_identity_active(session, CONNECTOR_KIND, row.id, active=row.enabled)
    await session.flush()
    await _announce(session, row, "changed")
    return await _view(session, row)


async def remove_directory(
    session: AsyncSession, directory_id: uuid.UUID, *, expected_version: int
) -> None:
    """Stop syncing: the connector and its secret go, its people stay and SupportX keeps them."""
    row = await DirectoryRepository(session).soft_delete(
        directory_id, expected_version=expected_version
    )
    await secrets.drop_owned(session, owner_kind=CONNECTOR_KIND, owner_id=row.id)
    await identities.set_identity_active(session, CONNECTOR_KIND, row.id, active=False)
    people = list(
        await session.scalars(
            select(DirectoryPersonLink.user_id).where(DirectoryPersonLink.connector_id == row.id)
        )
    )
    await release_from_directory(session, people)
    await _announce(session, row, "removed")


async def sync_now(session: AsyncSession, directory_id: uuid.UUID) -> DirectoryView:
    """Run at the next minute's schedule instead of waiting for the interval."""
    row = await DirectoryRepository(session).get(directory_id)
    if not row.enabled:
        raise Conflict(code="directory_disabled")
    row.next_sync_at = datetime.now(UTC)
    await session.flush()
    return await _view(session, row)


async def list_directories(session: AsyncSession) -> Sequence[DirectoryView]:
    """Every directory connector, by name."""
    rows = await session.scalars(
        select(DirectoryConnector)
        .where(DirectoryConnector.deleted_at.is_(None))
        .order_by(DirectoryConnector.name)
    )
    return [await _view(session, row) for row in rows]


async def get_directory(session: AsyncSession, directory_id: uuid.UUID) -> DirectoryView:
    """One connector (404 when removed or another tenant's)."""
    row = await session.get(DirectoryConnector, directory_id)
    if row is None or row.deleted_at is not None:
        raise NotFound(code="directory_not_found")
    return await _view(session, row)


async def find_groups(
    session: AsyncSession, settings: Settings, directory_id: uuid.UUID, query: str
) -> list[tuple[str, str]]:
    """Directory groups by name, asked with the connector's own sync app (for the screens)."""
    row = await session.get(DirectoryConnector, directory_id)
    if row is None or row.deleted_at is not None:
        raise NotFound(code="directory_not_found")
    secret = await secrets.read_owned(session, _ring(settings), row.secret_ref)
    if secret is None:
        raise Conflict(code="directory_secret_missing")
    client = Client(
        protocol=MailboxProtocol.GRAPH,
        client_id=row.client_id,
        credential_kind=CredentialKind(row.credential_kind),
        credential=secret,
        directory_id=row.directory_tenant,
    )
    oauth = oauth_for(settings)
    try:
        tokens = await oauth.app_token(client, (GRAPH_SCOPE,))
        graph = GraphDirectory(oauth.http(), oauth.endpoints.graph, tokens.access_token)
        try:
            return await graph.group_names(query)
        finally:
            await graph.close()
    except (MailboxUnavailableError, DirectoryUnavailableError) as exc:
        code = exc.reason if isinstance(exc, MailboxUnavailableError) else exc.code
        raise DirectoryRefused(params={"reason": code}) from exc


class DirectoryRefused(ServiceUnavailable):
    """The directory refused or did not answer; `reason` says what an admin can do."""

    code = "directory_unavailable"
