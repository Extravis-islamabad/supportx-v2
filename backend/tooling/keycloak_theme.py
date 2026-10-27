"""`python -m tooling.keycloak_theme`: the SupportX login theme on realms that have none (D-078).

Keycloak imports the realm file only on a realm's first start, so an installation upgraded from
before the branding work keeps Keycloak's own login page. This step gives such a realm the
`supportx` theme (docs/architecture/branding.md):

- realm without a login theme: set to `supportx`;
- realm with any login theme (Keycloak's own chosen on purpose, a tenant's custom theme, or
  already `supportx`): left exactly as it is, never overwritten;
- realm missing (not imported yet): nothing to do.

Run by the chart's `keycloak-theme` Job on every Helm revision, and by `make keycloak-theme`
against the Compose dev stack. Signs in as the installation's Keycloak bootstrap admin (master
realm, `admin-cli`). When that admin is no longer accepted (an operator replaced it, as Keycloak
recommends), the step says so and exits 0: the theme is then set by hand once (branding.md) and a
deploy is never blocked by it. Keycloak unreachable after the wait is an error (exit 1).

Environment: SUPPORTX_KEYCLOAK_URL (base URL, e.g. http://supportx-keycloak:8080/auth),
SUPPORTX_KEYCLOAK_ADMIN_USER (default admin), SUPPORTX_KEYCLOAK_ADMIN_PASSWORD,
SUPPORTX_KEYCLOAK_REALM (default supportx), SUPPORTX_KEYCLOAK_THEME (default supportx),
SUPPORTX_KEYCLOAK_WAIT_SECONDS (default 300).
"""

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from enum import StrEnum

import httpx

RETRY_SECONDS = 5.0


class Outcome(StrEnum):
    """What the step did to the realm."""

    SET = "set"
    KEPT = "kept"  # a login theme was already chosen: never overwritten
    NO_REALM = "no_realm"
    ADMIN_REFUSED = "admin_refused"


@dataclass(frozen=True)
class Result:
    """The outcome and the realm's login theme afterwards (None when unknown)."""

    outcome: Outcome
    theme: str | None = None


class KeycloakUnavailableError(RuntimeError):
    """Keycloak did not answer (or answered 5xx) for the whole wait."""


async def admin_token(client: httpx.AsyncClient, user: str, password: str) -> str | None:
    """A master-realm admin token, or None when the credentials are refused."""
    response = await client.post(
        "/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": user,
            "password": password,
        },
    )
    if response.status_code in (400, 401):
        return None
    response.raise_for_status()
    token: str = response.json()["access_token"]
    return token


async def ensure_login_theme(
    client: httpx.AsyncClient, *, user: str, password: str, realm: str, theme: str
) -> Result:
    """Set `theme` as the realm's login theme if it has none; never replace a chosen one."""
    token = await admin_token(client, user, password)
    if token is None:
        return Result(Outcome.ADMIN_REFUSED)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get(f"/admin/realms/{realm}", headers=headers)
    if response.status_code == httpx.codes.NOT_FOUND:
        return Result(Outcome.NO_REALM)
    response.raise_for_status()
    current = response.json().get("loginTheme")
    if current:
        return Result(Outcome.KEPT, current)
    # A partial representation: Keycloak updates only the fields it is given.
    update = await client.put(f"/admin/realms/{realm}", headers=headers, json={"loginTheme": theme})
    update.raise_for_status()
    return Result(Outcome.SET, theme)


@dataclass(frozen=True)
class Target:
    """Which Keycloak, signed in as whom, and which realm gets which theme."""

    base_url: str
    user: str
    password: str = field(repr=False)
    realm: str = "supportx"
    theme: str = "supportx"


async def run(
    target: Target,
    *,
    wait_seconds: float,
    transport: httpx.AsyncBaseTransport | None = None,
    retry_seconds: float = RETRY_SECONDS,
) -> Result:
    """`ensure_login_theme`, retried while Keycloak is starting (connection errors, 5xx)."""
    deadline = time.monotonic() + wait_seconds
    async with httpx.AsyncClient(
        base_url=target.base_url, timeout=10, transport=transport
    ) as client:
        while True:
            try:
                return await ensure_login_theme(
                    client,
                    user=target.user,
                    password=target.password,
                    realm=target.realm,
                    theme=target.theme,
                )
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                retryable = isinstance(error, httpx.TransportError) or (
                    error.response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR
                )
                if not retryable or time.monotonic() >= deadline:
                    raise KeycloakUnavailableError(str(error)) from error
            await asyncio.sleep(retry_seconds)


MESSAGES = {
    Outcome.SET: "keycloak login theme: realm {realm} now uses {theme}",
    Outcome.KEPT: "keycloak login theme: realm {realm} keeps its chosen theme {theme}",
    Outcome.NO_REALM: "keycloak login theme: realm {realm} does not exist yet, nothing to do",
    Outcome.ADMIN_REFUSED: (
        "keycloak login theme: SKIPPED, the bootstrap admin was refused; set the realm's login "
        "theme to supportx by hand if it has none (docs/architecture/branding.md)"
    ),
}


def main() -> int:  # pragma: no cover - thin CLI over tested functions
    """Read the environment, run the step, report."""
    env = os.environ
    realm = env.get("SUPPORTX_KEYCLOAK_REALM", "supportx")
    try:
        target = Target(
            env["SUPPORTX_KEYCLOAK_URL"],
            user=env.get("SUPPORTX_KEYCLOAK_ADMIN_USER", "admin"),
            password=env["SUPPORTX_KEYCLOAK_ADMIN_PASSWORD"],
            realm=realm,
            theme=env.get("SUPPORTX_KEYCLOAK_THEME", "supportx"),
        )
        wait = float(env.get("SUPPORTX_KEYCLOAK_WAIT_SECONDS", "300"))
        result = asyncio.run(run(target, wait_seconds=wait))
    except KeycloakUnavailableError as error:
        sys.stderr.write(f"keycloak login theme: Keycloak unavailable: {error}\n")
        return 1
    sys.stdout.write(MESSAGES[result.outcome].format(realm=realm, theme=result.theme) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
