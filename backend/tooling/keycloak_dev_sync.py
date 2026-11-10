"""`make keycloak-dev-sync`: bring an existing LOCAL dev realm up to what D-151 needs. DEV ONLY.

Keycloak imports the dev realm file only when the realm does not exist yet. A dev stack whose
realm was made before D-151 therefore lacks the dev quick sign-in's settings, and the only way
the docs offered to get them was deleting the realm (`make dev-reset`), which wipes the dev and
showcase data (rule 5h). This step sets exactly those settings through the admin API, and
nothing else:

- `directAccessGrantsEnabled` on the console and portal clients (the password grant the quick
  sign-in uses);
- the realm's remember-me, and its SSO idle and max lifespans (with their remember-me twins)
  raised to at least the dev realm file's 7 days. A longer value is kept.

It never touches users, credentials, roles or data, prints no secret, and is idempotent.

It refuses unless this is the local dev stack:
- Keycloak's address is loopback;
- the quick sign-in is switched on for this stack (SUPPORTX_DEV_QUICK_SIGN_IN=true, which
  `make dev-quick-sign-in` writes);
- every redirect address of the console and portal clients is a localhost one.
A realm on any real installation fails the last check, as the chart's realm has the
installation's own addresses.

Environment: SUPPORTX_KEYCLOAK_URL, SUPPORTX_KEYCLOAK_ADMIN_USER (default admin),
SUPPORTX_KEYCLOAK_ADMIN_PASSWORD, SUPPORTX_KEYCLOAK_REALM (default supportx),
SUPPORTX_DEV_QUICK_SIGN_IN, SUPPORTX_KEYCLOAK_WAIT_SECONDS (default 60).
"""

import asyncio
import ipaddress
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx

from tooling.keycloak_theme import admin_token

CLIENTS = ("supportx-console", "supportx-portal")
WEEK = (
    7 * 24 * 3600
)  # the dev realm file's session values (deploy/helm/.../dev/supportx-realm.json)
SESSION_VALUES = (
    "ssoSessionIdleTimeout",
    "ssoSessionMaxLifespan",
    "ssoSessionIdleTimeoutRememberMe",
    "ssoSessionMaxLifespanRememberMe",
)


class RefusedError(RuntimeError):
    """Not the local dev stack: nothing was changed."""


def _local_host(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_local(keycloak_url: str, quick_sign_in: str | None) -> None:
    """Refuse unless Keycloak is on this machine and the stack switched the quick sign-in on."""
    if not _local_host(urlsplit(keycloak_url).hostname):
        msg = "Keycloak is not on this machine (its address is not loopback)"
        raise RefusedError(msg)
    if (quick_sign_in or "").strip().lower() != "true":
        msg = "the dev quick sign-in is not switched on here (run make dev-quick-sign-in)"
        raise RefusedError(msg)


def check_clients(clients: Mapping[str, Mapping[str, Any]]) -> None:
    """Refuse unless both clients exist and send people back to localhost addresses only."""
    for client_id in CLIENTS:
        client = clients.get(client_id)
        if client is None:
            msg = f"the realm has no {client_id} client"
            raise RefusedError(msg)
        uris: Sequence[str] = client.get("redirectUris") or ()
        if not uris or not all(_local_host(urlsplit(uri).hostname) for uri in uris):
            msg = f"{client_id} redirects outside localhost: not the local dev realm"
            raise RefusedError(msg)


def realm_changes(realm: Mapping[str, Any]) -> dict[str, Any]:
    """The realm settings to set: remember-me on, session values raised to at least a week."""
    found: dict[str, Any] = {}
    if realm.get("rememberMe") is not True:
        found["rememberMe"] = True
    for name in SESSION_VALUES:
        current = realm.get(name)
        if not isinstance(current, int) or current < WEEK:
            found[name] = WEEK
    return found


async def _clients(http: httpx.AsyncClient, realm: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for client_id in CLIENTS:
        response = await http.get(f"/admin/realms/{realm}/clients", params={"clientId": client_id})
        response.raise_for_status()
        rows = [c for c in response.json() if c.get("clientId") == client_id]
        if rows:
            found[client_id] = rows[0]
    return found


async def run(  # noqa: PLR0913 - every input of the step, keyword-only
    base_url: str,
    *,
    user: str,
    password: str,
    realm: str,
    quick_sign_in: str | None,
    wait_seconds: float,
) -> list[str]:
    """Apply the deltas; returns what changed (empty: nothing to do). Raises RefusedError."""
    check_local(base_url, quick_sign_in)
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as http:
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            try:
                token = await admin_token(http, user, password)
                break
            except httpx.TransportError:
                if asyncio.get_running_loop().time() > deadline:
                    raise
                await asyncio.sleep(2)
        if token is None:
            msg = "the bootstrap admin was refused"
            raise RefusedError(msg)
        http.headers["Authorization"] = f"Bearer {token}"
        found = await http.get(f"/admin/realms/{realm}")
        if found.status_code == httpx.codes.NOT_FOUND:
            msg = f"realm {realm} does not exist (the stack imports it on first start)"
            raise RefusedError(msg)
        found.raise_for_status()
        clients = await _clients(http, realm)
        check_clients(clients)  # before any change
        changed: list[str] = []
        for client_id, client in clients.items():
            if client.get("directAccessGrantsEnabled") is not True:
                updated = {**client, "directAccessGrantsEnabled": True}
                put = await http.put(f"/admin/realms/{realm}/clients/{client['id']}", json=updated)
                put.raise_for_status()
                changed.append(f"{client_id}: password grant on")
        settings = realm_changes(found.json())
        if settings:
            put = await http.put(f"/admin/realms/{realm}", json=settings)
            put.raise_for_status()
            changed.append("realm: " + ", ".join(sorted(settings)))
        return changed


def main() -> int:  # pragma: no cover - thin CLI over tested functions
    """Read the environment, run the step, report (never a secret)."""
    env = os.environ
    realm = env.get("SUPPORTX_KEYCLOAK_REALM", "supportx")
    try:
        changed = asyncio.run(
            run(
                env["SUPPORTX_KEYCLOAK_URL"],
                user=env.get("SUPPORTX_KEYCLOAK_ADMIN_USER", "admin"),
                password=env.get("SUPPORTX_KEYCLOAK_ADMIN_PASSWORD", ""),
                realm=realm,
                quick_sign_in=env.get("SUPPORTX_DEV_QUICK_SIGN_IN"),
                wait_seconds=float(env.get("SUPPORTX_KEYCLOAK_WAIT_SECONDS", "60")),
            )
        )
    except RefusedError as error:
        sys.stderr.write(f"keycloak dev sync: REFUSED, nothing changed: {error}\n")
        return 1
    except httpx.HTTPError as error:
        sys.stderr.write(
            f"keycloak dev sync: Keycloak unavailable or refused: {type(error).__name__}\n"
        )
        return 1
    if changed:
        sys.stdout.write(f"keycloak dev sync: realm {realm}: " + "; ".join(changed) + "\n")
    else:
        sys.stdout.write(f"keycloak dev sync: realm {realm} already has the dev settings\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
