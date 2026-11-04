"""AD/LDAP directories: set up, change, remove, and their federation in Keycloak (WP-040, D-118).

An admin enters the directory: server, protection, bind account and where people live. The
bind password is sealed in the secrets store and never shown again. Keycloak connects to it
through user federation. The consumers worker writes the component as `supportx-federation`
(through identity_access's public interface), records `pending` -> `applied` or `failed` on the
row, and audits every use of that account.

Only where the realm serves one tenant (product owner, 2026-11-03: on-prem LDAP only, never on a
shared realm). The guard is the installation's own facts: `multi_tenant` off, and the federation
account installed (the Helm chart creates it only with `directory.ldap.enabled` and refuses that
with `multiTenant`). It is never a deployment-mode branch (CLAUDE.md rule 5f). The feature is
licensed as the `directory_federation` add-on.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.modules.audit import WORKER, record
from app.modules.identity_access import (
    FederationFailed,
    FederationNotInstalled,
    federation_installed,
    put_ldap_federation,
    release_from_directory,
    remove_ldap_federation,
)
from app.modules.integrations.domain import ldap
from app.modules.integrations.events import DirectoryChanged
from app.modules.integrations.infra.models import DirectoryConnector, DirectoryPersonLink
from app.modules.integrations.service import secrets
from app.modules.integrations.service.directories import (
    DirectoryRepository,
    DirectoryView,
    _announce,
    _ring,
    _view,
)
from app.modules.integrations.service.directory_sync import CONNECTOR_KIND
from app.modules.licensing import Feature, require_feature
from app.shared.events import ConsumerSpec, EventEnvelope
from app.shared.ids import new_id

log = get_logger(__name__)

LDAP = "ldap"
BIND_ROLE = "bind_password"
PENDING, APPLIED, FAILED = "pending", "applied", "failed"
_TEXT_LIMIT = 500


def _error(field: str, code: str) -> FieldError:
    return FieldError(field=f"body.{field}", code=code, message_key=f"errors.{code}")


def _text(values: Mapping[str, Any], name: str) -> str | None:
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:_TEXT_LIMIT]


def _choice[E: (ldap.Security, ldap.Vendor)](kind: type[E], value: object, default: E) -> E | None:
    if value is None:
        return default
    try:
        return kind(str(value))
    except ValueError:
        return None


def _settings_of(values: Mapping[str, Any]) -> tuple[ldap.LdapSettings | None, list[FieldError]]:
    """What the admin entered as domain settings, and every field refused."""
    errors: list[FieldError] = []
    security = _choice(ldap.Security, values.get("security"), ldap.Security.LDAPS)
    vendor = _choice(ldap.Vendor, values.get("vendor"), ldap.Vendor.ACTIVE_DIRECTORY)
    for name, chosen in (("security", security), ("vendor", vendor)):
        if chosen is None:
            errors.append(_error(name, "invalid_choice"))
    numbers: dict[str, int] = {}
    defaults = {
        "port": 636 if security is ldap.Security.LDAPS else 389,
        "changed_sync_seconds": ldap.CHANGED_SYNC_SECONDS,
        "full_sync_seconds": ldap.FULL_SYNC_SECONDS,
    }
    for name, default in defaults.items():
        value = values.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(_error(name, "out_of_range"))
        else:
            numbers[name] = value
    texts = {name: _text(values, name) for name in ("host", "bind_dn", "users_dn")}
    errors += [_error(name, "required") for name, value in texts.items() if value is None]
    if errors or security is None or vendor is None:
        return None, errors
    found = ldap.LdapSettings(
        host=str(texts["host"]),
        port=numbers["port"],
        security=security,
        vendor=vendor,
        bind_dn=str(texts["bind_dn"]),
        users_dn=str(texts["users_dn"]),
        allow_plain=values.get("allow_plain") is True,
        groups_dn=_text(values, "groups_dn"),
        user_filter=_text(values, "user_filter"),
        department_from=_text(values, "department_from") or "department",
        site_from=_text(values, "site_from") or "physicalDeliveryOfficeName",
        changed_sync_seconds=numbers["changed_sync_seconds"],
        full_sync_seconds=numbers["full_sync_seconds"],
    )
    return found, [_error(field, code) for field, code in ldap.problems(found)]


def _stored(settings: ldap.LdapSettings) -> dict[str, Any]:  # Any: the JSONB column
    return {
        "host": settings.host,
        "port": settings.port,
        "security": settings.security.value,
        "vendor": settings.vendor.value,
        "bind_dn": settings.bind_dn,
        "users_dn": settings.users_dn,
        "allow_plain": settings.allow_plain,
        "groups_dn": settings.groups_dn,
        "user_filter": settings.user_filter,
        "department_from": settings.department_from,
        "site_from": settings.site_from,
        "changed_sync_seconds": settings.changed_sync_seconds,
        "full_sync_seconds": settings.full_sync_seconds,
    }


def ldap_settings(row: DirectoryConnector) -> ldap.LdapSettings:
    """The stored settings of an AD/LDAP directory (404 for an Entra one)."""
    if row.source != LDAP or row.ldap is None:
        raise NotFound(code="directory_not_found")
    stored = row.ldap
    return ldap.LdapSettings(
        host=stored["host"],
        port=int(stored["port"]),
        security=ldap.Security(stored["security"]),
        vendor=ldap.Vendor(stored["vendor"]),
        bind_dn=stored["bind_dn"],
        users_dn=stored["users_dn"],
        allow_plain=bool(stored.get("allow_plain")),
        groups_dn=stored.get("groups_dn"),
        user_filter=stored.get("user_filter"),
        department_from=stored.get("department_from") or "department",
        site_from=stored.get("site_from") or "physicalDeliveryOfficeName",
        changed_sync_seconds=int(stored["changed_sync_seconds"]),
        full_sync_seconds=int(stored["full_sync_seconds"]),
    )


async def _allowed(tenant_id: uuid.UUID, settings: Settings, *, multi_tenant: bool) -> None:
    """Licensed, on a realm that serves one tenant, with the federation account installed."""
    await require_feature(tenant_id, Feature.DIRECTORY_FEDERATION)
    if multi_tenant:
        raise Conflict(code="ldap_single_tenant_only")
    if not federation_installed(settings):
        raise FederationNotInstalled


def _validated(
    values: Mapping[str, Any], *, bind_password: str | None, creating: bool
) -> tuple[str, ldap.LdapSettings]:
    found, errors = _settings_of(values)
    name = _text(values, "name")
    if name is None or len(name) > 200:  # noqa: PLR2004 - the column's length
        errors.append(_error("name", "required"))
    if creating and not bind_password:
        errors.append(_error("bind_password", "required"))
    if errors or found is None or name is None:
        raise ValidationFailed(errors=errors)
    return name, found


async def create_ldap_directory(  # noqa: PLR0913 - the tenant, the installation and the request
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    bind_password: str | None,
    multi_tenant: bool,
) -> DirectoryView:
    """A new AD/LDAP directory; the worker connects it in Keycloak within moments."""
    await _allowed(tenant_id, settings, multi_tenant=multi_tenant)
    name, found = _validated(values, bind_password=bind_password, creating=True)
    ring = _ring(settings)
    row = DirectoryConnector(
        id=new_id(),
        name=name,
        source=LDAP,
        ldap=_stored(found),
        enabled=values.get("enabled", True) is not False,
        federation_state=PENDING,
    )
    try:
        row = await DirectoryRepository(session).add(row)
    except Exception as exc:  # the partial unique index on the name
        raise Conflict(code="directory_name_taken") from exc
    assert bind_password is not None  # noqa: S101 - _validated requires it on create
    row.secret_ref = await secrets.put_owned(
        session,
        ring,
        owner_kind=CONNECTOR_KIND,
        owner_id=row.id,
        role=BIND_ROLE,
        secret_type="password",  # noqa: S106 - a type code, not a password
        value=bind_password,
    )
    await session.flush()
    await _announce(session, row, "added")
    return await _view(session, row)


async def update_ldap_directory(  # noqa: PLR0913 - the record, the version and the change
    session: AsyncSession,
    settings: Settings,
    tenant_id: uuid.UUID,
    directory_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    expected_version: int,
    bind_password: str | None,
    multi_tenant: bool,
) -> DirectoryView:
    """Change a directory (If-Match); a new bind password replaces the old one, same row."""
    await _allowed(tenant_id, settings, multi_tenant=multi_tenant)
    ldap_settings(await DirectoryRepository(session).get(directory_id))  # 404 for Entra
    name, found = _validated(values, bind_password=bind_password, creating=False)
    row = await DirectoryRepository(session).update(
        directory_id,
        expected_version=expected_version,
        changes={
            "name": name,
            "ldap": _stored(found),
            "enabled": values.get("enabled", True) is not False,
            "federation_state": PENDING,
            "federation_error": None,
        },
    )
    if bind_password:
        row.secret_ref = await secrets.put_owned(
            session,
            _ring(settings),
            owner_kind=CONNECTOR_KIND,
            owner_id=row.id,
            role=BIND_ROLE,
            secret_type="password",  # noqa: S106 - a type code, not a password
            value=bind_password,
        )
    await session.flush()
    await _announce(session, row, "changed")
    return await _view(session, row)


async def remove_ldap_directory(
    session: AsyncSession, directory_id: uuid.UUID, *, expected_version: int
) -> None:
    """Stop federating: the worker removes the component; SupportX keeps the people it brought."""
    ldap_settings(await DirectoryRepository(session).get(directory_id))  # 404 for Entra
    row = await DirectoryRepository(session).soft_delete(
        directory_id, expected_version=expected_version
    )
    await secrets.drop_owned(session, owner_kind=CONNECTOR_KIND, owner_id=row.id)
    people = list(
        await session.scalars(
            select(DirectoryPersonLink.user_id).where(DirectoryPersonLink.connector_id == row.id)
        )
    )
    await release_from_directory(session, people)
    await _announce(session, row, "removed")


async def list_ldap_directories(session: AsyncSession) -> Sequence[DirectoryView]:
    """Every AD/LDAP directory, by name."""
    rows = await session.scalars(
        select(DirectoryConnector)
        .where(DirectoryConnector.deleted_at.is_(None), DirectoryConnector.source == LDAP)
        .order_by(DirectoryConnector.name)
    )
    return [await _view(session, row) for row in rows]


async def get_ldap_directory(session: AsyncSession, directory_id: uuid.UUID) -> DirectoryView:
    """One AD/LDAP directory (404 when removed, an Entra one, or another tenant's)."""
    row = await session.get(DirectoryConnector, directory_id)
    if row is None or row.deleted_at is not None or row.source != LDAP:
        raise NotFound(code="directory_not_found")
    return await _view(session, row)


# --- the worker: the directory in Keycloak -------------------------------------------------------

Outcome = Literal["applied", "failed", "removed", "skipped"]


def component_name(row: DirectoryConnector) -> str:
    """The component's name in the realm: stable per directory, so a rename changes nothing."""
    return f"supportx-{row.id}"


async def _audit_use(
    session: AsyncSession,
    row: DirectoryConnector,
    action: str,
    *,
    reason_code: str | None = None,
    security: str | None = None,
) -> None:
    # Every use of the federation account is audited (product owner, 2026-11-03).
    details: dict[str, str] = {"account": "supportx-federation"}
    if security is not None:
        details["security"] = security
    await record(
        session,
        action_code=action,
        facts=WORKER,
        reason_code=reason_code,
        object_type="directory_connector",
        object_id=row.id,
        details=details,
    )


async def _apply(session: AsyncSession, settings: Settings, row: DirectoryConnector) -> Outcome:
    found = ldap_settings(row)
    password = await secrets.read_owned(session, _ring(settings), row.secret_ref)
    error: str | None = None
    if password is None:
        error = "ldap_bind_password_missing"
    else:
        try:
            row.keycloak_component_id = await put_ldap_federation(
                settings,
                component=lambda realm: ldap.component(
                    found,
                    name=component_name(row),
                    realm_id=realm,
                    bind_password=password,
                    enabled=row.enabled,
                ),
                mappers=lambda component_id: ldap.mappers(found, component_id=component_id),
            )
        except (FederationFailed, FederationNotInstalled) as exc:
            error = exc.code
    row.federation_state = FAILED if error else APPLIED
    row.federation_error = error
    await _audit_use(
        session,
        row,
        "directory.federation_failed" if error else "directory.federation_applied",
        security=found.security.value,
        reason_code=error,
    )
    await session.flush()
    await _announce(session, row, "synced")
    return "failed" if error else "applied"


async def _remove(session: AsyncSession, settings: Settings, row: DirectoryConnector) -> Outcome:
    if row.keycloak_component_id is None:
        return "skipped"  # never reached Keycloak
    try:
        await remove_ldap_federation(settings, row.keycloak_component_id)
    except (FederationFailed, FederationNotInstalled) as exc:
        # Raised, so the consumer retries: a removed directory must not stay in the realm. No
        # audit entry here, as this transaction rolls back; the worker's log and, after the
        # last attempt, the dead-letter queue show it.
        log.warning("ldap_federation_remove_failed", directory_id=str(row.id), code=exc.code)
        raise
    row.keycloak_component_id = None
    await _audit_use(session, row, "directory.federation_removed")
    await session.flush()
    return "removed"


async def apply_federation(
    session: AsyncSession, settings: Settings, directory_id: uuid.UUID
) -> Outcome:
    """Bring Keycloak to the row as it is now (the newest save wins; repeats change nothing)."""
    row = await session.scalar(
        select(DirectoryConnector).where(DirectoryConnector.id == directory_id).with_for_update()
    )
    if row is None or row.source != LDAP:
        return "skipped"
    if row.deleted_at is not None:
        return await _remove(session, settings, row)
    if row.federation_state != PENDING:
        return "skipped"  # applied by an earlier event already
    return await _apply(session, settings, row)


async def _handle(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    assert session is not None  # noqa: S101 - transactional consumer
    if envelope.payload.get("change") == "synced":
        return  # this worker's own announcement
    outcome = await apply_federation(
        session, get_settings(), uuid.UUID(str(envelope.payload["directory_id"]))
    )
    log.info("ldap_federation", outcome=outcome)


LDAP_FEDERATION_APPLY = ConsumerSpec(
    name="integrations__ldap_federation_apply",
    event_types=(DirectoryChanged.event_type,),
    handler=_handle,
)

__all__ = [
    "LDAP_FEDERATION_APPLY",
    "DirectoryView",
    "apply_federation",
    "create_ldap_directory",
    "get_ldap_directory",
    "ldap_settings",
    "list_ldap_directories",
    "remove_ldap_directory",
    "update_ldap_directory",
]
