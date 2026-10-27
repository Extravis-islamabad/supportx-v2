"""Single sign-on set-ups, pure rules (WP-039; REQ-SEC-007, REQ-SEC-008; D-094).

A set-up becomes a Keycloak identity provider linked to the tenant's organization:

- created hidden (not on the sign-in page) and only usable by the admin's test sign-in, which
  asks for it by name (`kc_idp_hint`);
- its email domains become domains of the tenant's organization routed to it (Keycloak 26.8:
  `identityProviderAlias` on the organization's domain); a first sign-in through it makes the
  person a member of the organization when their email is in one of them (proved on 26.8.1);
- switched on: shown on the tenant's sign-in page, and, when chosen, people whose email domain
  matches are sent straight to it (`autoRedirect` on those domains).

Attributes (email, names, department, site) are mapped to Keycloak user attributes; SupportX
reads department and site once, when it creates the person (REQ-SEC-007 AC3).
"""

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Literal
from urllib.parse import urlsplit

Protocol = Literal["oidc", "saml"]
Preset = Literal["entra", "okta", "google", "oidc", "saml"]
State = Literal["draft", "tested", "on", "off"]

# Every field problem a set-up can be refused with (labels `errors.field.<code>`, CI-checked).
FIELD_PROBLEMS = frozenset(
    {
        "sso_certificate_expired",
        "sso_certificate_missing",
        "sso_certificate_required",
        "sso_certificate_unreadable",
        "sso_client_id_required",
        "sso_client_rejected",
        "sso_client_secret_required",
        "sso_discovery_invalid",
        "sso_discovery_unreachable",
        "sso_domain_in_use",
        "sso_domain_invalid",
        "sso_domain_public",
        "sso_domain_required",
        "sso_domain_taken",
        "sso_domain_unverified",
        "sso_domains_too_many",
        "sso_issuer_mismatch",
        "sso_issuer_required",
        "sso_metadata_required",
        "sso_metadata_unreachable",
        "sso_metadata_unreadable",
        "sso_name_length",
        "sso_protocol_fixed",
        "sso_sign_in_url_missing",
        "sso_url_invalid",
    }
)

MAX_PROVIDERS = 5
MAX_DOMAINS = 20
DEPARTMENT_ATTRIBUTE = "sx_department"
SITE_ATTRIBUTE = "sx_site"
# Domains everyone shares: claiming one would let a tenant capture other people's sign-ins on
# the installation's shared address (email redirect) and block every other tenant from it.
PUBLIC_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "mail.com",
        "yandex.com",
        "zoho.com",
    }
)
_LABEL = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN = re.compile(rf"^{_LABEL}(\.{_LABEL})+$")
DEFAULT_SCOPES = "openid email profile"
EMAIL_NAME_ID = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
# Where each preset's issuer lives (the admin fills the tenant part; checked, never trusted).
PRESET_ISSUERS: dict[str, str] = {
    "entra": "https://login.microsoftonline.com/",
    "okta": "https://",
    "google": "https://accounts.google.com",
}


@dataclass(frozen=True)
class Problem:
    """One field problem (code → `errors.field.<code>`)."""

    field: str
    code: str
    params: dict[str, str | int | float | bool | None] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class Mapping:
    """Which claim (OIDC) or attribute (SAML) carries each person field; None = not mapped."""

    email: str
    first_name: str
    last_name: str
    department: str | None = None
    site: str | None = None


OIDC_MAPPING = Mapping(email="email", first_name="given_name", last_name="family_name")
SAML_MAPPING = Mapping(
    email="http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    first_name="http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
    last_name="http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname",
)


def normalise_domains(values: list[str]) -> tuple[list[str], list[Problem]]:
    """Lower-case unique email domains, or the problems (each at `domains`)."""
    found: list[str] = []
    problems: list[Problem] = []
    for raw in values:
        domain = raw.strip().lower().lstrip("@").rstrip(".")
        if not domain:
            continue
        if not _DOMAIN.fullmatch(domain) or len(domain) > 253:  # noqa: PLR2004 - DNS limit
            problems.append(Problem("domains", "sso_domain_invalid", {"domain": domain}))
        elif domain in PUBLIC_MAIL_DOMAINS:
            problems.append(Problem("domains", "sso_domain_public", {"domain": domain}))
        elif domain not in found:
            found.append(domain)
    if not found and not problems:
        problems.append(Problem("domains", "sso_domain_required"))
    if len(found) > MAX_DOMAINS:
        problems.append(Problem("domains", "sso_domains_too_many", {"max": MAX_DOMAINS}))
    return found, problems


def check_url(value: str, field_name: str) -> Problem | None:
    """An absolute http(s) URL without credentials, or a problem at `field_name`."""
    parts = urlsplit(value.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username:
        return Problem(field_name, "sso_url_invalid")
    return None


def alias_for(slug: str, token: str) -> str:
    """The Keycloak alias of a tenant's set-up: unique, and naming the tenant for operators."""
    return f"sx-{slug}-{token}"[:60]


def oidc_config(discovery: dict[str, Any], *, client_id: str, scopes: str) -> dict[str, str]:
    """Keycloak OIDC broker settings from the provider's discovery document."""
    config = {
        "issuer": str(discovery["issuer"]),
        "authorizationUrl": str(discovery["authorization_endpoint"]),
        "tokenUrl": str(discovery["token_endpoint"]),
        "jwksUrl": str(discovery.get("jwks_uri", "")),
        "useJwksUrl": "true",
        "validateSignature": "true",
        "clientId": client_id,
        "clientAuthMethod": "client_secret_post",
        "defaultScope": scopes or DEFAULT_SCOPES,
        "pkceEnabled": "true",
        "pkceMethod": "S256",
        "syncMode": "IMPORT",
    }
    if discovery.get("userinfo_endpoint"):
        config["userInfoUrl"] = str(discovery["userinfo_endpoint"])
    if discovery.get("end_session_endpoint"):
        config["logoutUrl"] = str(discovery["end_session_endpoint"])
    return config


def saml_config(parsed: dict[str, str]) -> dict[str, str]:
    """Keycloak SAML broker settings from Keycloak's reading of the metadata (or the fields)."""
    keep = (
        "singleSignOnServiceUrl",
        "singleLogoutServiceUrl",
        "signingCertificate",
        "idpEntityId",
        "postBindingResponse",
        "postBindingAuthnRequest",
        "postBindingLogout",
        "wantAuthnRequestsSigned",
        "nameIDPolicyFormat",
    )
    config = {key: parsed[key] for key in keep if parsed.get(key)}
    config |= {
        # The assertion must be signed with the provider's certificate (REQ-SEC-007 AC1).
        "validateSignature": "true",
        # The person is the assertion's subject (NameID), as an email address by default.
        "principalType": "SUBJECT",
        "nameIDPolicyFormat": parsed.get("nameIDPolicyFormat") or EMAIL_NAME_ID,
        "syncMode": "IMPORT",
    }
    return config


def route_domains(
    current: list[dict[str, Any]], *, alias: str, mine: list[str], drop: set[str], redirect: bool
) -> list[dict[str, Any]]:
    """The organization's domains after a set-up's change (Keycloak 26.8 domain routing).

    `mine` are routed to `alias` (sending people straight there when `redirect`), `drop` are
    removed (only domains SupportX added); a domain once routed to `alias` but no longer the
    set-up's is unrouted; every other domain stays exactly as it was.
    """
    found: list[dict[str, Any]] = []
    for domain in current:
        name = domain["name"]
        if name in drop:
            continue
        if name in mine:
            found.append({**domain, "identityProviderAlias": alias, "autoRedirect": redirect})
        elif domain.get("identityProviderAlias") == alias:
            kept = {k: v for k, v in domain.items() if k != "identityProviderAlias"}
            found.append({**kept, "autoRedirect": False})
        else:
            found.append(domain)
    names = {d["name"] for d in found}
    found += [
        {"name": name, "verified": False, "identityProviderAlias": alias, "autoRedirect": redirect}
        for name in mine
        if name not in names
    ]
    return found


def representation(  # noqa: PLR0913 - every part of the provider, keyword-only
    *,
    alias: str,
    protocol: Protocol,
    display_name: str,
    config: dict[str, str],
    state: State,
    client_secret: str | None = None,
) -> dict[str, Any]:
    """The Keycloak identity provider for a set-up in `state` (secret only when given)."""
    if client_secret is not None:
        config = config | {"clientSecret": client_secret}
    return {
        "alias": alias,
        "displayName": display_name,
        "providerId": protocol,
        # Enabled in every state but off: the admin's test sign-in needs it. Hidden until on.
        "enabled": state != "off",
        "hideOnLogin": state != "on",
        "trustEmail": True,
        "storeToken": False,
        "linkOnly": False,
        "firstBrokerLoginFlowAlias": "first broker login",
        "config": config,
    }


def mappers(protocol: Protocol, mapping: Mapping) -> list[dict[str, Any]]:
    """Keycloak mappers putting each mapped claim or attribute on the user."""
    kind = (
        "oidc-user-attribute-idp-mapper" if protocol == "oidc" else "saml-user-attribute-idp-mapper"
    )
    source = "claim" if protocol == "oidc" else "attribute.name"
    targets = {
        "email": mapping.email,
        "firstName": mapping.first_name,
        "lastName": mapping.last_name,
        DEPARTMENT_ATTRIBUTE: mapping.department,
        SITE_ATTRIBUTE: mapping.site,
    }
    return [
        {
            "name": f"sx {target}",
            "identityProviderMapper": kind,
            "config": {source: claim, "user.attribute": target, "syncMode": "INHERIT"},
        }
        for target, claim in targets.items()
        if claim
    ]


# Connection check results (REQ-SEC-007 AC1: a plain reason; codes → `sso_check.<code>`).
CheckCode = Literal[
    "ok",
    "discovery_unreachable",
    "discovery_invalid",
    "issuer_mismatch",
    "client_rejected",
    "metadata_unreadable",
    "certificate_missing",
    "certificate_expired",
    "certificate_not_yet_valid",
    "sign_in_url_missing",
    "not_https",
]


def issuer_matches(configured: str, discovered: str) -> bool:
    """The discovery document belongs to the issuer typed (trailing slash aside)."""
    return configured.rstrip("/") == discovered.rstrip("/")
