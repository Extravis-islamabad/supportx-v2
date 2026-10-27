"""Keycloak's admin API, as SupportX's identity service account (WP-039, ADR-036).

Signs in with client credentials as `supportx-identity`, whose roles are only those
`tooling/keycloak_identity.py` grants (people, identity providers, organizations, reading login
events). Everything a tenant admin changes about sign-in goes through here; no tenant admin ever
gets Keycloak console rights (REQ-SEC-017 AC2).

The realm is shared by every tenant (D-010), so this client never takes a tenant's word for what
it may touch: callers pass the tenant, and organization lookups check the organization's
`tenant_id` attribute as well as its alias; identity providers are named and linked per tenant
(service/sso.py checks the link before every change).
"""

import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import Settings
from app.core.errors import ServiceUnavailable

_TOKEN_MARGIN_SECONDS = 30


class IdentityAdminNotConfigured(ServiceUnavailable):
    """No service account secret: the installation has not run the identity set-up step."""

    code = "identity_admin_not_configured"


class IdentityAdminUnavailable(ServiceUnavailable):
    """Keycloak's admin API could not be reached, or refused the service account."""

    code = "identity_admin_unavailable"


class IdentityAdminRefused(Exception):
    """Keycloak refused a change (4xx other than not found); `status` and its message kept."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Organization:
    """A tenant's Keycloak organization (alias = tenant slug)."""

    id: str
    alias: str
    name: str
    domains: tuple[str, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class KeycloakUser:
    """A realm user (only what SupportX reads)."""

    id: str
    email: str
    enabled: bool
    has_password: bool


@dataclass(frozen=True)
class LoginEvent:
    """One login event (only the parts SupportX reads)."""

    type: str
    time_ms: int
    error: str | None
    identity_provider: str | None
    user_id: str | None


class IdentityAdmin(Protocol):
    """What the identity services need from Keycloak (a fake in database tests)."""

    async def organization(self, slug: str, tenant_id: str) -> Organization | None: ...  # noqa: D102 - see KeycloakAdmin

    async def set_organization_domains(  # noqa: D102
        self, organization: Organization, domains: list[dict[str, Any]]
    ) -> None: ...

    async def provider(self, alias: str) -> dict[str, Any] | None: ...  # noqa: D102

    async def create_provider(self, representation: dict[str, Any]) -> None: ...  # noqa: D102

    async def update_provider(self, alias: str, representation: dict[str, Any]) -> None: ...  # noqa: D102

    async def delete_provider(self, alias: str) -> None: ...  # noqa: D102

    async def link_provider(self, organization_id: str, alias: str) -> None: ...  # noqa: D102

    async def linked_providers(self, organization_id: str) -> list[str]: ...  # noqa: D102

    async def replace_mappers(self, alias: str, mappers: list[dict[str, Any]]) -> None: ...  # noqa: D102

    async def parse_saml_metadata(self, metadata: str) -> dict[str, str]: ...  # noqa: D102

    async def logout_user(self, user_id: str) -> None: ...  # noqa: D102

    async def user_attributes(self, user_id: str) -> dict[str, list[str]]: ...  # noqa: D102

    async def find_user(self, email: str) -> KeycloakUser | None: ...  # noqa: D102

    async def create_user(  # noqa: D102
        self, *, email: str, first_name: str, last_name: str, locale: str
    ) -> str: ...

    async def delete_user(self, user_id: str) -> None: ...  # noqa: D102

    async def add_member(self, organization_id: str, user_id: str) -> None: ...  # noqa: D102

    async def remove_member(self, organization_id: str, user_id: str) -> None: ...  # noqa: D102

    async def set_attributes(self, user_id: str, values: dict[str, str]) -> None: ...  # noqa: D102

    async def send_actions_email(  # noqa: D102
        self, user_id: str, actions: list[str], lifespan_seconds: int
    ) -> None: ...

    async def require_actions(self, user_id: str, actions: list[str]) -> None: ...  # noqa: D102

    async def member_tenants(self, user_id: str) -> list[str]: ...  # noqa: D102

    async def login_events(  # noqa: D102
        self, types: list[str], since_ms: int, user_id: str | None = None
    ) -> list[LoginEvent]: ...


class RealmAdmin(Protocol):
    """The realm settings SupportX changes as `supportx-realm` (manage-realm; worker only)."""

    async def set_password_policy(self, policy: str) -> None: ...  # noqa: D102 - see KeycloakAdmin

    async def close(self) -> None: ...  # noqa: D102


def admin_base(settings: Settings) -> tuple[str, str] | None:
    """(Keycloak base URL, realm) from the back-channel realm URL; None when not configured."""
    realm_url = settings.oidc_internal_url or settings.oidc_issuer
    if realm_url is None:
        return None
    parts = urlsplit(realm_url.rstrip("/"))
    head, marker, realm = parts.path.rpartition("/realms/")
    if not marker or not realm:
        return None
    return urlunsplit((parts.scheme, parts.netloc, head, "", "")), realm


class KeycloakAdmin:
    """`IdentityAdmin` over httpx, with the service account's token cached until near expiry."""

    def __init__(  # noqa: PLR0913 - connection settings, keyword-only
        self,
        base_url: str,
        realm: str,
        *,
        client_id: str,
        client_secret: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.realm = realm
        self._client_id = client_id
        self._secret = client_secret
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)
        self._token: tuple[str, float] | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "KeycloakAdmin | None":
        """The client for this installation, or None when the service account is not set up."""
        found = admin_base(settings)
        secret = settings.keycloak_identity_client_secret
        if found is None or secret is None or not secret.get_secret_value():
            return None
        base, realm = found
        return cls(
            base,
            realm,
            client_id=settings.keycloak_identity_client_id,
            client_secret=secret.get_secret_value(),
            timeout=settings.oidc_timeout_seconds,
        )

    @classmethod
    def realm_from_settings(cls, settings: Settings) -> "KeycloakAdmin | None":
        """The realm-settings client (`supportx-realm`), or None when not set up.

        Its service account holds manage-realm, so only the consumers worker gets the secret
        (the chart gives it to no other pod): an API process can never change the realm.
        """
        found = admin_base(settings)
        secret = settings.keycloak_realm_client_secret
        if found is None or secret is None or not secret.get_secret_value():
            return None
        base, realm = found
        return cls(
            base,
            realm,
            client_id=settings.keycloak_realm_client_id,
            client_secret=secret.get_secret_value(),
            timeout=settings.oidc_timeout_seconds,
        )

    async def close(self) -> None:
        """Close the HTTP connection pool."""
        await self._http.aclose()

    async def _bearer(self) -> str:
        now = time.monotonic()
        if self._token is not None and self._token[1] > now:
            return self._token[0]
        try:
            response = await self._http.post(
                f"/realms/{self.realm}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._secret,
                },
            )
        except httpx.TransportError as exc:
            raise IdentityAdminUnavailable from exc
        if response.status_code != httpx.codes.OK:
            raise IdentityAdminUnavailable
        body = response.json()
        token = str(body["access_token"])
        lifetime = float(body.get("expires_in", 60))
        self._token = (token, now + max(lifetime - _TOKEN_MARGIN_SECONDS, 1))
        return token

    async def _call(  # noqa: PLR0913 - one request helper for every admin call
        self,
        method: str,
        path: str,
        *,
        json: Any = None,  # noqa: ANN401 - any JSON body Keycloak takes
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        content: str | None = None,
        missing_ok: bool = False,
    ) -> httpx.Response | None:
        headers = {"Authorization": f"Bearer {await self._bearer()}"}
        if content is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = await self._http.request(
                method,
                f"/admin/realms/{self.realm}{path}",
                headers=headers,
                json=json,
                params=params,
                files=files,
                data=data,
                content=content,
            )
        except httpx.TransportError as exc:
            raise IdentityAdminUnavailable from exc
        if response.status_code == httpx.codes.NOT_FOUND and missing_ok:
            return None
        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            self._token = None
            raise IdentityAdminUnavailable
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise IdentityAdminUnavailable
        if response.status_code >= httpx.codes.BAD_REQUEST:
            try:
                message = str(response.json().get("errorMessage", ""))
            except ValueError:
                message = ""
            raise IdentityAdminRefused(response.status_code, message)
        return response

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:  # noqa: ANN401 - Keycloak's JSON
        response = await self._call(method, path, **kwargs)
        return None if response is None else response.json()

    async def organization(self, slug: str, tenant_id: str) -> Organization | None:
        """The organization with alias `slug` whose `tenant_id` attribute is `tenant_id`.

        Found by the attribute (`q=tenant_id:<id>`; lists leave attributes out), then read in
        full and checked on both: a renamed alias or a copied attribute never matches.
        """
        found = await self._json("GET", "/organizations", params={"q": f"tenant_id:{tenant_id}"})
        for brief in found or []:
            if brief.get("alias") != slug:
                continue
            item = await self._json("GET", f"/organizations/{brief['id']}", missing_ok=True) or {}
            ids = (item.get("attributes") or {}).get("tenant_id") or []
            if item.get("alias") == slug and tenant_id in ids:
                domains = tuple(d["name"] for d in item.get("domains") or [])
                return Organization(item["id"], item["alias"], item["name"], domains, item)
        return None

    async def set_organization_domains(
        self, organization: Organization, domains: list[dict[str, Any]]
    ) -> None:
        """Replace the organization's domains (name, verified, routing).

        Keycloak keeps a domain in one organization only and refuses one another organization has.
        """
        body = {**organization.raw, "domains": domains}
        await self._call("PUT", f"/organizations/{organization.id}", json=body)

    async def provider(self, alias: str) -> dict[str, Any] | None:
        """An identity provider's representation (secrets come back masked)."""
        found = await self._json("GET", f"/identity-provider/instances/{alias}", missing_ok=True)
        return None if found is None else dict(found)

    async def create_provider(self, representation: dict[str, Any]) -> None:
        """A new identity provider."""
        await self._call("POST", "/identity-provider/instances", json=representation)

    async def update_provider(self, alias: str, representation: dict[str, Any]) -> None:
        """Replace an identity provider's settings (a masked secret keeps the stored one)."""
        await self._call("PUT", f"/identity-provider/instances/{alias}", json=representation)

    async def delete_provider(self, alias: str) -> None:
        """Remove an identity provider (and its links); already gone is fine."""
        await self._call("DELETE", f"/identity-provider/instances/{alias}", missing_ok=True)

    async def link_provider(self, organization_id: str, alias: str) -> None:
        """Link an identity provider to an organization (members are onboarded through it)."""
        await self._call(
            "POST", f"/organizations/{organization_id}/identity-providers", content=f'"{alias}"'
        )

    async def linked_providers(self, organization_id: str) -> list[str]:
        """Aliases of the providers linked to the organization."""
        found = await self._json("GET", f"/organizations/{organization_id}/identity-providers")
        return [str(item["alias"]) for item in found or []]

    async def replace_mappers(self, alias: str, mappers: list[dict[str, Any]]) -> None:
        """Make the provider's mappers exactly `mappers`."""
        path = f"/identity-provider/instances/{alias}/mappers"
        for existing in await self._json("GET", path) or []:
            await self._call("DELETE", f"{path}/{existing['id']}", missing_ok=True)
        for mapper in mappers:
            await self._call("POST", path, json={**mapper, "identityProviderAlias": alias})

    async def parse_saml_metadata(self, metadata: str) -> dict[str, str]:
        """Keycloak's own reading of SAML metadata (D-089: no XML parser in SupportX)."""
        found = await self._json(
            "POST",
            "/identity-provider/import-config",
            data={"providerId": "saml"},
            files={"file": ("metadata.xml", metadata.encode(), "application/xml")},
        )
        return {str(k): str(v) for k, v in (found or {}).items()}

    async def logout_user(self, user_id: str) -> None:
        """End every Keycloak session of a person (REQ-SEC-031); unknown is fine."""
        await self._call("POST", f"/users/{user_id}/logout", missing_ok=True)

    async def user_attributes(self, user_id: str) -> dict[str, list[str]]:
        """A person's Keycloak attributes (set by identity provider mappers); unknown: none."""
        found = await self._json("GET", f"/users/{user_id}", missing_ok=True) or {}
        return {
            str(k): [str(v) for v in values]
            for k, values in (found.get("attributes") or {}).items()
        }

    async def find_user(self, email: str) -> KeycloakUser | None:
        """The realm user with this email (exact), or None."""
        found = await self._json(
            "GET", "/users", params={"email": email, "exact": "true", "briefRepresentation": "true"}
        )
        for item in found or []:
            if str(item.get("email", "")).lower() == email.lower():
                credentials = await self._json("GET", f"/users/{item['id']}/credentials") or []
                return KeycloakUser(
                    id=str(item["id"]),
                    email=str(item["email"]),
                    enabled=bool(item.get("enabled", True)),
                    has_password=any(c.get("type") == "password" for c in credentials),
                )
        return None

    async def create_user(self, *, email: str, first_name: str, last_name: str, locale: str) -> str:
        """A new realm user without a password (they set one from the e-mail); its ID."""
        response = await self._call(
            "POST",
            "/users",
            json={
                "username": email,
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
                "enabled": True,
                # Reached through an e-mail SupportX asked for: the address is the person's.
                "emailVerified": True,
                "attributes": {"locale": [locale]},
            },
        )
        assert response is not None  # noqa: S101 - not missing_ok
        return response.headers["location"].rsplit("/", 1)[1]

    async def delete_user(self, user_id: str) -> None:
        """Remove a realm user (an unused invitation's); already gone is fine."""
        await self._call("DELETE", f"/users/{user_id}", missing_ok=True)

    async def add_member(self, organization_id: str, user_id: str) -> None:
        """Make a user a member of the organization (already one is fine)."""
        try:
            await self._call(
                "POST", f"/organizations/{organization_id}/members", content=f'"{user_id}"'
            )
        except IdentityAdminRefused as exc:
            if exc.status != httpx.codes.CONFLICT:
                raise

    async def remove_member(self, organization_id: str, user_id: str) -> None:
        """End a user's membership of the organization; not a member is fine."""
        await self._call(
            "DELETE", f"/organizations/{organization_id}/members/{user_id}", missing_ok=True
        )

    async def set_attributes(self, user_id: str, values: dict[str, str]) -> None:
        """Set some attributes of a user, keeping the others (and the profile)."""
        current = await self._json("GET", f"/users/{user_id}")
        if current is None:
            return
        attributes = dict(current.get("attributes") or {})
        attributes.update({name: [value] for name, value in values.items()})
        await self._call("PUT", f"/users/{user_id}", json={**current, "attributes": attributes})

    async def send_actions_email(
        self, user_id: str, actions: list[str], lifespan_seconds: int
    ) -> None:
        """Keycloak's own e-mail asking the user to do `actions` (D-099), valid that long."""
        await self._call(
            "PUT",
            f"/users/{user_id}/execute-actions-email",
            params={"lifespan": lifespan_seconds},
            json=actions,
        )

    async def require_actions(self, user_id: str, actions: list[str]) -> None:
        """Actions the user must do at their next sign-in (e.g. UPDATE_PASSWORD)."""
        current = await self._json("GET", f"/users/{user_id}")
        if current is None:
            return
        wanted = sorted({*(current.get("requiredActions") or []), *actions})
        await self._call("PUT", f"/users/{user_id}", json={**current, "requiredActions": wanted})

    async def member_tenants(self, user_id: str) -> list[str]:
        """The tenant IDs of the organizations the user is a member of."""
        found = await self._json("GET", f"/organizations/members/{user_id}/organizations") or []
        tenants: list[str] = []
        for brief in found:
            item = await self._json("GET", f"/organizations/{brief['id']}", missing_ok=True) or {}
            tenants += (item.get("attributes") or {}).get("tenant_id") or []
        return tenants

    async def login_events(
        self, types: list[str], since_ms: int, user_id: str | None = None
    ) -> list[LoginEvent]:
        """Login events of `types` since `since_ms`, newest first."""
        params: dict[str, Any] = {"type": types, "dateFrom": _day(since_ms), "max": 50}
        if user_id is not None:
            params["user"] = user_id
        events = []
        for item in await self._json("GET", "/events", params=params) or []:
            if int(item.get("time", 0)) < since_ms:
                continue
            details = item.get("details") or {}
            events.append(
                LoginEvent(
                    type=str(item["type"]),
                    time_ms=int(item["time"]),
                    error=item.get("error"),
                    identity_provider=details.get("identity_provider"),
                    user_id=item.get("userId"),
                )
            )
        return events

    async def set_password_policy(self, policy: str) -> None:
        """The realm's password policy (a partial representation: nothing else changes)."""
        await self._call("PUT", "", json={"passwordPolicy": policy})


def _day(epoch_ms: int) -> str:
    """Keycloak's `dateFrom` takes a day (yyyy-MM-dd); finer filtering happens on `time`."""
    return time.strftime("%Y-%m-%d", time.gmtime(epoch_ms / 1000))
