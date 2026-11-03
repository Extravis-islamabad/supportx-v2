"""AD/LDAP through Keycloak's user federation, as rules with no I/O (WP-040, D-118).

An on-prem customer's directory is connected in Keycloak's realm, not by SupportX: Keycloak
checks AD passwords at sign-in (REQ-SEC-012), imports the people and their changes, and SupportX
reads the result. This module turns what an admin entered into Keycloak's component and mapper
representations, and says what is refused:

- LDAPS (`ldaps://`) by default; plain `ldap://` only by an explicit, audited choice, and never
  with a bind password sent in clear unless that choice was made (StartTLS counts as encrypted);
- read-only: SupportX never writes to the customer's directory;
- people are checked for changes every 30 minutes and read in full once a day (D-118 defaults,
  tenant-editable);
- the attributes SupportX maps (address, names, department, site) come over through mappers,
  department and site into the user attributes single sign-on already uses (`sx_department`,
  `sx_site`); an Active Directory account that is disabled there is disabled at sign-in too.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from app.modules.integrations.domain.directory import (
    Change,
    DirectoryPerson,
    PersonSkipped,
    SkipReason,
)

COMPONENT_PROVIDER = "ldap"
COMPONENT_TYPE = "org.keycloak.storage.UserStorageProvider"
MAPPER_TYPE = "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
CHANGED_SYNC_SECONDS = 30 * 60
FULL_SYNC_SECONDS = 24 * 3600
_DN = re.compile(r"^[^=,\s][^=,]*=[^,]+(,\s*[^=,\s][^=,]*=[^,]+)*$")
_ATTRIBUTE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")


class Vendor(StrEnum):
    """Which kind of directory (decides the defaults of its attributes)."""

    ACTIVE_DIRECTORY = "ad"
    OTHER = "other"  # OpenLDAP and the other LDAP v3 directories


class Security(StrEnum):
    """How the connection is protected."""

    LDAPS = "ldaps"  # TLS from the first byte (port 636): the default
    START_TLS = "start_tls"  # ldap:// upgraded to TLS before the bind
    PLAIN = "plain"  # no encryption: only by an audited choice (`allow_plain`)


@dataclass(frozen=True)
class LdapSettings:
    """What an admin enters for one directory (the bind password is stored apart, sealed)."""

    host: str
    port: int
    security: Security
    vendor: Vendor
    bind_dn: str
    users_dn: str
    allow_plain: bool = False
    groups_dn: str | None = None
    user_filter: str | None = None  # an LDAP filter narrowing who is imported
    department_from: str = "department"
    site_from: str = "physicalDeliveryOfficeName"
    changed_sync_seconds: int = CHANGED_SYNC_SECONDS
    full_sync_seconds: int = FULL_SYNC_SECONDS

    @property
    def url(self) -> str:
        """The connection URL Keycloak uses."""
        scheme = "ldaps" if self.security is Security.LDAPS else "ldap"
        return f"{scheme}://{self.host}:{self.port}"


def _connection_problems(settings: LdapSettings) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    host = settings.host.strip()
    if not host or urlsplit(f"//{host}").hostname != host.lower() or "/" in host:
        found.append(("host", "ldap_host_invalid"))
    if not 1 <= settings.port <= 65535:  # noqa: PLR2004 - the TCP port range
        found.append(("port", "out_of_range"))
    if settings.security is Security.PLAIN and not settings.allow_plain:
        found.append(("security", "plain_connection_refused"))
    return found


def _directory_problems(settings: LdapSettings) -> list[tuple[str, str]]:
    names = {"bind_dn": settings.bind_dn, "users_dn": settings.users_dn}
    if settings.groups_dn is not None:
        names["groups_dn"] = settings.groups_dn
    found = [
        (name, "ldap_dn_invalid") for name, value in names.items() if not _DN.match(value.strip())
    ]
    if settings.user_filter is not None and not (
        settings.user_filter.startswith("(") and settings.user_filter.endswith(")")
    ):
        found.append(("user_filter", "ldap_filter_invalid"))
    found += [
        (name, "ldap_attribute_invalid")
        for name in ("department_from", "site_from")
        if not _ATTRIBUTE.match(getattr(settings, name))
    ]
    return found


def problems(settings: LdapSettings) -> list[tuple[str, str]]:
    """(field, code) for every refused value; empty when the settings may be saved."""
    found = _connection_problems(settings) + _directory_problems(settings)
    if not 300 <= settings.changed_sync_seconds <= 86400:  # noqa: PLR2004 - 5 min to a day
        found.append(("changed_sync_seconds", "out_of_range"))
    if not 3600 <= settings.full_sync_seconds <= 7 * 86400:  # noqa: PLR2004 - an hour to a week
        found.append(("full_sync_seconds", "out_of_range"))
    return found


def _one(value: str | int | bool) -> list[str]:  # noqa: FBT001 - one config value, of any kind
    # Keycloak's component config is a map of string lists.
    if isinstance(value, bool):
        return ["true" if value else "false"]
    return [str(value)]


def component(
    settings: LdapSettings, *, name: str, realm_id: str, bind_password: str, enabled: bool = True
) -> dict[str, Any]:  # Any: Keycloak's JSON
    """The user-federation component for Keycloak's admin API (`POST /components`)."""
    ad = settings.vendor is Vendor.ACTIVE_DIRECTORY
    config: dict[str, list[str]] = {
        "vendor": ["ad" if ad else "other"],
        "connectionUrl": [settings.url],
        "startTls": _one(settings.security is Security.START_TLS),
        "useTruststoreSpi": ["always"],
        "connectionTimeout": ["10000"],
        "authType": ["simple"],
        "bindDn": [settings.bind_dn.strip()],
        "bindCredential": [bind_password],
        "usersDn": [settings.users_dn.strip()],
        "searchScope": ["2"],  # the whole subtree
        "pagination": ["true"],
        "usernameLDAPAttribute": ["sAMAccountName" if ad else "uid"],
        "rdnLDAPAttribute": ["cn" if ad else "uid"],
        "uuidLDAPAttribute": ["objectGUID" if ad else "entryUUID"],
        "userObjectClasses": [
            "person, organizationalPerson, user" if ad else "inetOrgPerson, organizationalPerson"
        ],
        "editMode": ["READ_ONLY"],  # SupportX never writes to the customer's directory
        "syncRegistrations": ["false"],
        "importEnabled": ["true"],
        "batchSizeForSync": ["1000"],
        "fullSyncPeriod": _one(settings.full_sync_seconds),
        "changedSyncPeriod": _one(settings.changed_sync_seconds),
        "trustEmail": ["false"],
        "enabled": _one(enabled),  # a directory switched off in SupportX signs nobody in
        "priority": ["0"],
        "cachePolicy": ["DEFAULT"],
    }
    if settings.user_filter:
        config["customUserSearchFilter"] = [settings.user_filter]
    return {
        "name": name,
        "providerId": COMPONENT_PROVIDER,
        "providerType": COMPONENT_TYPE,
        "parentId": realm_id,
        "config": config,
    }


def _attribute_mapper(
    name: str, ldap: str, model: str, *, parent: str
) -> dict[str, Any]:  # Any: Keycloak's JSON
    return {
        "name": name,
        "providerId": "user-attribute-ldap-mapper",
        "providerType": MAPPER_TYPE,
        "parentId": parent,
        "config": {
            "ldap.attribute": [ldap],
            "user.model.attribute": [model],
            "read.only": ["true"],
            "always.read.value.from.ldap": ["true"],
            "is.mandatory.in.ldap": ["false"],
        },
    }


def mappers(
    settings: LdapSettings, *, component_id: str
) -> list[dict[str, Any]]:  # Any: Keycloak's JSON
    """The mappers SupportX relies on, under the component (replaced as a whole on a change)."""
    found = [
        _attribute_mapper("email", "mail", "email", parent=component_id),
        _attribute_mapper("first name", "givenName", "firstName", parent=component_id),
        _attribute_mapper("last name", "sn", "lastName", parent=component_id),
        # Department and site land where single sign-on puts them (WP-039 D6).
        _attribute_mapper(
            "department", settings.department_from, "sx_department", parent=component_id
        ),
        _attribute_mapper("site", settings.site_from, "sx_site", parent=component_id),
    ]
    if settings.vendor is Vendor.ACTIVE_DIRECTORY:
        # An account disabled in AD cannot sign in at its next attempt (REQ-INT-064).
        found.append(
            {
                "name": "account controls",
                "providerId": "msad-user-account-control-mapper",
                "providerType": MAPPER_TYPE,
                "parentId": component_id,
                "config": {"password.policy.hints.enabled": ["false"]},
            }
        )
    if settings.groups_dn:
        found.append(
            {
                "name": "groups",
                "providerId": "group-ldap-mapper",
                "providerType": MAPPER_TYPE,
                "parentId": component_id,
                "config": {
                    "groups.dn": [settings.groups_dn.strip()],
                    "group.name.ldap.attribute": ["cn"],
                    "group.object.classes": [
                        "group" if settings.vendor is Vendor.ACTIVE_DIRECTORY else "groupOfNames"
                    ],
                    "membership.ldap.attribute": ["member"],
                    "membership.attribute.type": ["DN"],
                    "mode": ["READ_ONLY"],
                    "user.roles.retrieve.strategy": ["LOAD_GROUPS_BY_MEMBER_ATTRIBUTE"],
                    "preserve.group.inheritance": ["false"],
                    "drop.non.existing.groups.during.sync": ["false"],
                },
            }
        )
    return found


# --- the people Keycloak imported --------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]+$")
_NAME_MAX = 100


def _first(attributes: Mapping[str, object], key: str) -> str | None:
    values = attributes.get(key)
    if isinstance(values, list) and values and isinstance(values[0], str) and values[0].strip():
        return values[0].strip()
    return None


def _name(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def from_keycloak(user: Mapping[str, object]) -> Change:
    """One federated user, as Keycloak's admin API returns it, as a directory change.

    The person's ID is the directory's own (`LDAP_ID`: objectGUID or entryUUID), so the link
    survives the component being created again; Keycloak's user ID is the fallback. Everyone is
    read on every run (no delta), so every field is present: a missing department clears it.
    """
    raw = user.get("attributes")
    attributes: Mapping[str, object] = raw if isinstance(raw, Mapping) else {}
    external_id = _first(attributes, "LDAP_ID") or str(user.get("id") or "")
    email = _name(user.get("email"))
    if email is None:
        return PersonSkipped(external_id, SkipReason.NO_ADDRESS)
    if not _EMAIL.match(email):
        return PersonSkipped(external_id, SkipReason.NOT_AN_EMAIL)
    names = {"first_name": _name(user.get("firstName")), "last_name": _name(user.get("lastName"))}
    skipped = tuple(
        (field, SkipReason.TOO_LONG)
        for field, value in names.items()
        if value is not None and len(value) > _NAME_MAX
    )
    values = {k: v for k, v in names.items() if v is None or len(v) <= _NAME_MAX}
    return DirectoryPerson(
        external_id=external_id,
        enabled=user.get("enabled") is not False,
        values={"email": email.lower(), **values},
        refs={
            "department": _first(attributes, "sx_department"),
            "site": _first(attributes, "sx_site"),
        },
        skipped=skipped,
    )
