"""`python -m tooling.keycloak_identity`: the service account SupportX manages identity with.

WP-039 (D-089 D7, D-094, ADR-036): tenant admins set up single sign-on, sessions and (later)
MFA and passwords in SupportX screens; SupportX carries them out through Keycloak's admin API as
the confidential client `supportx-identity` (client credentials only, no browser flow). This step
makes the realm ready for that, on fresh and upgraded installations alike:

- the client exists, with the secret from the installation's secrets (set again when it differs,
  so rotating the secret is a deploy);
- its service account holds exactly the least-privileged admin roles in ROLES (nothing else is
  removed from it by hand without this step putting the list back);
- login events are recorded, kept 7 days: at least the types SupportX reads (sign-ins through
  identity providers and their errors); types or listeners an operator chose are kept (a realm
  that never chose any records every type, as Keycloak does);
- the realm's SSO session lasts at least the platform's longest SupportX session, so SupportX's
  own per-tenant timeouts decide (REQ-SEC-029); shorter realm values are raised, longer kept;
- the user profile declares the attributes single sign-on brings (department and site, read by
  SupportX at a person's first sign-in, REQ-SEC-007 AC3): Keycloak 26 drops undeclared ones.
  Only admins see or change them; the realm's other attributes are kept as they are.

It is never part of the realm import file: a placeholder without its value would leave a
guessable secret. Run by the chart's `keycloak-identity` Job on every Helm revision and by
`make keycloak-identity` for the Compose dev stack. Signs in as the bootstrap admin like
`tooling.keycloak_theme`; when that admin is no longer accepted, it says so and exits 0 (the
operator then creates the client by hand once: docs/architecture/identity.md).

Environment: SUPPORTX_KEYCLOAK_URL, SUPPORTX_KEYCLOAK_ADMIN_USER (default admin),
SUPPORTX_KEYCLOAK_ADMIN_PASSWORD, SUPPORTX_KEYCLOAK_REALM (default supportx),
SUPPORTX_KEYCLOAK_IDENTITY_CLIENT_SECRET, SUPPORTX_KEYCLOAK_WAIT_SECONDS (default 300).
"""

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx

from tooling.keycloak_theme import KeycloakUnavailableError, admin_token

CLIENT_ID = "supportx-identity"
# The admin API rights SupportX needs and nothing more (verified on Keycloak 26.8.1): people
# (sessions, credentials, required actions), identity providers, organizations (members,
# domains, provider links) and reading login events (why a test sign-in failed). No realm,
# client or master-realm rights: it cannot change the realm's settings or reach the console.
ROLES = ("manage-users", "manage-identity-providers", "manage-organizations", "view-events")
EVENT_TYPES = (
    "LOGIN",
    "LOGIN_ERROR",
    "IDENTITY_PROVIDER_LOGIN",
    "IDENTITY_PROVIDER_LOGIN_ERROR",
    "IDENTITY_PROVIDER_FIRST_LOGIN",
    "IDENTITY_PROVIDER_FIRST_LOGIN_ERROR",
    "IDENTITY_PROVIDER_POST_LOGIN",
    "IDENTITY_PROVIDER_POST_LOGIN_ERROR",
)
EVENTS_EXPIRATION_SECONDS = 7 * 86400
# The longest SupportX sessions (Appendix A caps: portal 30 days absolute; 24 hours idle at most).
SSO_IDLE_SECONDS = 24 * 3600
SSO_MAX_SECONDS = 30 * 86400
RETRY_SECONDS = 5.0
# What identity provider mappers store on a person (domain/sso.py DEPARTMENT/SITE_ATTRIBUTE).
PROFILE_ATTRIBUTES = {
    "sx_department": "Department (from single sign-on)",
    "sx_site": "Site (from single sign-on)",
}
MIN_SECRET_LENGTH = 16


class Outcome(StrEnum):
    """What the step found or did."""

    READY = "ready"  # everything was already in place
    UPDATED = "updated"
    NO_REALM = "no_realm"
    ADMIN_REFUSED = "admin_refused"


@dataclass(frozen=True)
class Result:
    """The outcome and what changed (for the log)."""

    outcome: Outcome
    changes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Target:
    """Which Keycloak and realm, as whom, and the client secret to set."""

    base_url: str
    user: str
    password: str = field(repr=False)
    secret: str = field(repr=False, default="")
    realm: str = "supportx"


def _client_body(secret: str) -> dict[str, Any]:
    return {
        "clientId": CLIENT_ID,
        "name": "SupportX identity administration",
        "description": "Service account SupportX uses for SSO, sessions and MFA (WP-039).",
        "enabled": True,
        "publicClient": False,
        "clientAuthenticatorType": "client-secret",
        "secret": secret,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "frontchannelLogout": False,
    }


async def _ensure_client(
    client: httpx.AsyncClient, headers: dict[str, str], realm: str, secret: str
) -> tuple[str, list[str]]:
    """The client's internal ID; created, or its secret and flows put back."""
    base = f"/admin/realms/{realm}/clients"
    found = await client.get(base, headers=headers, params={"clientId": CLIENT_ID})
    found.raise_for_status()
    body = _client_body(secret)
    if not found.json():
        (await client.post(base, headers=headers, json=body)).raise_for_status()
        found = await client.get(base, headers=headers, params={"clientId": CLIENT_ID})
        found.raise_for_status()
        return str(found.json()[0]["id"]), ["client created"]
    current = found.json()[0]
    internal = str(current["id"])
    changes: list[str] = []
    stored = await client.get(f"{base}/{internal}/client-secret", headers=headers)
    stored.raise_for_status()
    drifted = any(current.get(key) != value for key, value in body.items() if key != "secret")
    if drifted or stored.json().get("value") != secret:
        update = await client.put(f"{base}/{internal}", headers=headers, json={**current, **body})
        update.raise_for_status()
        changes.append("client settings or secret set")
    return internal, changes


async def _ensure_roles(
    client: httpx.AsyncClient, headers: dict[str, str], realm: str, internal: str
) -> list[str]:
    """Exactly ROLES of realm-management on the service account (extras removed)."""
    admin = f"/admin/realms/{realm}"
    account = await client.get(f"{admin}/clients/{internal}/service-account-user", headers=headers)
    account.raise_for_status()
    user_id = account.json()["id"]
    management = await client.get(
        f"{admin}/clients", headers=headers, params={"clientId": "realm-management"}
    )
    management.raise_for_status()
    management_id = management.json()[0]["id"]
    mappings = f"{admin}/users/{user_id}/role-mappings/clients/{management_id}"
    held = await client.get(mappings, headers=headers)
    held.raise_for_status()
    held_names = {role["name"]: role for role in held.json()}
    available = await client.get(f"{admin}/clients/{management_id}/roles", headers=headers)
    available.raise_for_status()
    by_name = {role["name"]: role for role in available.json()}
    missing = [by_name[name] for name in ROLES if name not in held_names]
    extra = [role for name, role in held_names.items() if name not in ROLES]
    changes: list[str] = []
    if missing:
        (await client.post(mappings, headers=headers, json=missing)).raise_for_status()
        changes.append("roles granted: " + ", ".join(role["name"] for role in missing))
    if extra:
        removed = await client.request("DELETE", mappings, headers=headers, json=extra)
        removed.raise_for_status()
        changes.append("roles removed: " + ", ".join(role["name"] for role in extra))
    return changes


async def _ensure_events(
    client: httpx.AsyncClient, headers: dict[str, str], realm: str
) -> list[str]:
    """Login events on, with SupportX's types; an operator's additions are kept."""
    path = f"/admin/realms/{realm}/events/config"
    current = await client.get(path, headers=headers)
    current.raise_for_status()
    config = current.json()
    types = list(config.get("enabledEventTypes") or [])
    wanted = types + [kind for kind in EVENT_TYPES if kind not in types]
    expiration = config.get("eventsExpiration") or 0
    if config.get("eventsEnabled") and wanted == types and expiration >= EVENTS_EXPIRATION_SECONDS:
        return []
    update = {
        **config,
        "eventsEnabled": True,
        "enabledEventTypes": wanted,
        "eventsExpiration": max(expiration, EVENTS_EXPIRATION_SECONDS),
    }
    (await client.put(path, headers=headers, json=update)).raise_for_status()
    return ["login events on"]


async def _ensure_sso_session(
    client: httpx.AsyncClient, headers: dict[str, str], realm: str
) -> list[str]:
    """The realm's SSO session at least as long as SupportX's longest; never shortened."""
    path = f"/admin/realms/{realm}"
    current = await client.get(path, headers=headers)
    current.raise_for_status()
    found = current.json()
    update: dict[str, int] = {}
    if (found.get("ssoSessionIdleTimeout") or 0) < SSO_IDLE_SECONDS:
        update["ssoSessionIdleTimeout"] = SSO_IDLE_SECONDS
    if (found.get("ssoSessionMaxLifespan") or 0) < SSO_MAX_SECONDS:
        update["ssoSessionMaxLifespan"] = SSO_MAX_SECONDS
    if not update:
        return []
    # A partial representation: Keycloak updates only the fields it is given.
    (await client.put(path, headers=headers, json=update)).raise_for_status()
    return ["SSO session raised to the SupportX maximum"]


async def _ensure_user_profile(
    client: httpx.AsyncClient, headers: dict[str, str], realm: str
) -> list[str]:
    """The single sign-on attributes declared in the user profile (admins only)."""
    path = f"/admin/realms/{realm}/users/profile"
    current = await client.get(path, headers=headers)
    current.raise_for_status()
    profile = current.json()
    attributes = list(profile.get("attributes") or [])
    known = {attribute["name"] for attribute in attributes}
    missing = [name for name in PROFILE_ATTRIBUTES if name not in known]
    if not missing:
        return []
    attributes += [
        {
            "name": name,
            "displayName": PROFILE_ATTRIBUTES[name],
            "permissions": {"view": ["admin"], "edit": ["admin"]},
            "multivalued": False,
        }
        for name in missing
    ]
    (
        await client.put(path, headers=headers, json={**profile, "attributes": attributes})
    ).raise_for_status()
    return ["user profile: " + ", ".join(missing)]


async def ensure_identity_admin(client: httpx.AsyncClient, target: Target) -> Result:
    """Everything in the module docstring, idempotent."""
    token = await admin_token(client, target.user, target.password)
    if token is None:
        return Result(Outcome.ADMIN_REFUSED)
    headers = {"Authorization": f"Bearer {token}"}
    realm = await client.get(f"/admin/realms/{target.realm}", headers=headers)
    if realm.status_code == httpx.codes.NOT_FOUND:
        return Result(Outcome.NO_REALM)
    realm.raise_for_status()
    internal, changes = await _ensure_client(client, headers, target.realm, target.secret)
    changes += await _ensure_roles(client, headers, target.realm, internal)
    changes += await _ensure_events(client, headers, target.realm)
    changes += await _ensure_sso_session(client, headers, target.realm)
    changes += await _ensure_user_profile(client, headers, target.realm)
    return Result(Outcome.UPDATED if changes else Outcome.READY, tuple(changes))


async def run(
    target: Target,
    *,
    wait_seconds: float,
    transport: httpx.AsyncBaseTransport | None = None,
    retry_seconds: float = RETRY_SECONDS,
) -> Result:
    """`ensure_identity_admin`, retried while Keycloak is starting (connection errors, 5xx)."""
    deadline = time.monotonic() + wait_seconds
    async with httpx.AsyncClient(
        base_url=target.base_url, timeout=10, transport=transport
    ) as client:
        while True:
            try:
                return await ensure_identity_admin(client, target)
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                retryable = isinstance(error, httpx.TransportError) or (
                    error.response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR
                )
                if not retryable or time.monotonic() >= deadline:
                    raise KeycloakUnavailableError(str(error)) from error
            await asyncio.sleep(retry_seconds)


def main() -> int:  # pragma: no cover - thin CLI over tested functions
    """Read the environment, run the step, report."""
    env = os.environ
    realm = env.get("SUPPORTX_KEYCLOAK_REALM", "supportx")
    secret = env.get("SUPPORTX_KEYCLOAK_IDENTITY_CLIENT_SECRET", "")
    if len(secret) < MIN_SECRET_LENGTH:
        sys.stderr.write("keycloak identity: SUPPORTX_KEYCLOAK_IDENTITY_CLIENT_SECRET is not set\n")
        return 1
    target = Target(
        env["SUPPORTX_KEYCLOAK_URL"],
        user=env.get("SUPPORTX_KEYCLOAK_ADMIN_USER", "admin"),
        password=env["SUPPORTX_KEYCLOAK_ADMIN_PASSWORD"],
        secret=secret,
        realm=realm,
    )
    try:
        result = asyncio.run(
            run(target, wait_seconds=float(env.get("SUPPORTX_KEYCLOAK_WAIT_SECONDS", "300")))
        )
    except KeycloakUnavailableError as error:
        sys.stderr.write(f"keycloak identity: Keycloak unavailable: {error}\n")
        return 1
    messages = {
        Outcome.READY: f"keycloak identity: realm {realm} ready, nothing changed",
        Outcome.UPDATED: f"keycloak identity: realm {realm}: " + "; ".join(result.changes),
        Outcome.NO_REALM: f"keycloak identity: realm {realm} does not exist yet, nothing to do",
        Outcome.ADMIN_REFUSED: (
            "keycloak identity: SKIPPED, the bootstrap admin was refused; create the "
            f"{CLIENT_ID} client by hand (docs/architecture/identity.md)"
        ),
    }
    sys.stdout.write(messages[result.outcome] + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
