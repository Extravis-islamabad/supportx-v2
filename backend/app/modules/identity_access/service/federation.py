"""Directory federation in Keycloak, for the integrations module (WP-040, D-118).

An on-prem customer's AD/LDAP directory is connected in Keycloak's realm. The integrations
module owns the directory record and its bind password. Keycloak is this module's, so the
federation calls stay here, behind a public interface: write or remove one component with its
mappers, or ask for a sync.

Every call acts as `supportx-federation`, the account with only manage-realm (product owner,
2026-11-03). That account exists only where the installation turned LDAP on, so
`FederationNotInstalled` is the answer everywhere else. The caller audits each use.
"""

from collections.abc import Callable
from typing import Any

from app.core.config import Settings
from app.core.errors import ServiceUnavailable
from app.core.logging import get_logger
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdminRefused,
    IdentityAdminUnavailable,
    KeycloakAdmin,
)

log = get_logger(__name__)

# Any: Keycloak's JSON, built by the integrations domain (`integrations.domain.ldap`).
ComponentFor = Callable[[str], dict[str, Any]]  # realm ID -> the component
MappersFor = Callable[[str], list[dict[str, Any]]]  # component ID -> its mappers


class FederationNotInstalled(ServiceUnavailable):
    """No federation account here: LDAP is not turned on for this installation."""

    code = "ldap_federation_not_installed"


class FederationFailed(Exception):
    """Keycloak could not be reached or refused the change; `code` says which, for the screen."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def federation_installed(settings: Settings) -> bool:
    """Whether this installation has the federation account (its secret is configured)."""
    return settings.keycloak_federation_client_secret is not None


def _admin(settings: Settings) -> KeycloakAdmin:
    admin = KeycloakAdmin.federation_from_settings(settings)
    if admin is None:
        raise FederationNotInstalled
    return admin


def _failed(exc: Exception) -> FederationFailed:
    if isinstance(exc, IdentityAdminRefused):
        # The message can name the customer's server; the log keeps it, the screen gets a code.
        log.warning("ldap_federation_refused", status=exc.status, reason=exc.message)
        return FederationFailed("ldap_federation_refused")
    return FederationFailed("ldap_federation_keycloak_unavailable")


async def put_ldap_federation(
    settings: Settings, *, component: ComponentFor, mappers: MappersFor
) -> str:
    """Create or replace the component (found by its name) and exactly its mappers; its ID."""
    admin = _admin(settings)
    try:
        component_id = await admin.put_federation_component(component(await admin.realm_id()))
        await admin.replace_federation_mappers(component_id, mappers(component_id))
    except (IdentityAdminUnavailable, IdentityAdminRefused) as exc:
        raise _failed(exc) from exc
    finally:
        await admin.close()
    return component_id


async def remove_ldap_federation(settings: Settings, component_id: str) -> None:
    """Remove the component and its mappers (Keycloak drops the users it imported from it)."""
    admin = _admin(settings)
    try:
        await admin.delete_federation_component(component_id)
    except (IdentityAdminUnavailable, IdentityAdminRefused) as exc:
        raise _failed(exc) from exc
    finally:
        await admin.close()


async def sync_ldap_federation(
    settings: Settings, component_id: str, *, full: bool
) -> dict[str, Any]:  # Any: Keycloak's sync result (added, updated, removed, failed)
    """Ask Keycloak to read the directory now: the changes only, or everyone."""
    admin = _admin(settings)
    try:
        return await admin.sync_federation(component_id, full=full)
    except (IdentityAdminUnavailable, IdentityAdminRefused) as exc:
        raise _failed(exc) from exc
    finally:
        await admin.close()
