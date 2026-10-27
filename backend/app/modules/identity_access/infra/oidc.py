"""OpenID Connect client for Keycloak (authorization code + PKCE, confidential client).

Only the BFF talks to Keycloak's token, logout and JWKS endpoints (back channel); the browser only
ever visits the authorization endpoint. ID tokens are verified with Keycloak's published keys
(RS256) before any claim is trusted.
"""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.errors import ServiceUnavailable

DISCOVERY_PATH = "/.well-known/openid-configuration"
BASE_SCOPES = "openid profile email"
SCOPES = f"{BASE_SCOPES} organization:*"
_METADATA_TTL_SECONDS = 300


class IdentityProviderUnavailable(ServiceUnavailable):
    """Keycloak could not be reached or answered unexpectedly."""

    code = "identity_provider_unavailable"


class TokenRejectedError(Exception):
    """Keycloak refused a code or refresh token (invalid_grant): the user must log in again."""


class InvalidTokenError(Exception):
    """An ID token failed signature or format checks."""


@dataclass(frozen=True)
class ClientCredentials:
    """One registered client (console or portal)."""

    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class TokenSet:
    """Tokens from Keycloak's token endpoint (kept server-side only)."""

    access_token: str
    refresh_token: str
    id_token: str
    expires_in: int


@dataclass(frozen=True)
class PkcePair:
    """PKCE verifier (kept server-side) and its S256 challenge (sent to Keycloak)."""

    verifier: str
    challenge: str

    @classmethod
    def generate(cls) -> "PkcePair":
        """A fresh 64-byte-entropy verifier and its challenge (RFC 7636)."""
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode()).digest()
        return cls(verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode())


def _b64decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _rsa_key(jwk: dict[str, Any]) -> rsa.RSAPublicKey:
    numbers = rsa.RSAPublicNumbers(
        e=int.from_bytes(_b64decode(jwk["e"]), "big"), n=int.from_bytes(_b64decode(jwk["n"]), "big")
    )
    return numbers.public_key()


def verify_rs256(token: str, jwks: dict[str, Any]) -> dict[str, Any]:
    """Claims of an RS256 JWT whose signature matches a key in `jwks`, else InvalidTokenError."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64decode(header_b64))
        payload = json.loads(_b64decode(payload_b64))
        signature = _b64decode(signature_b64)
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidTokenError("malformed token") from exc  # noqa: EM101, TRY003 - internal reason, logged, never shown to clients
    if header.get("alg") != "RS256":
        raise InvalidTokenError("unexpected algorithm")  # noqa: EM101, TRY003 - internal reason, logged, never shown to clients
    keys = [
        k
        for k in jwks.get("keys", [])
        if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"
    ]
    for jwk in keys:
        try:
            _rsa_key(jwk).verify(
                signature,
                f"{header_b64}.{payload_b64}".encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature:
            continue
        if not isinstance(payload, dict):
            raise InvalidTokenError("claims are not an object")  # noqa: EM101, TRY003 - internal reason, logged, never shown to clients
        return payload
    raise InvalidTokenError("signature does not match any published key")  # noqa: EM101, TRY003 - internal reason, logged, never shown to clients


class OidcClient:
    """Keycloak endpoints for one realm, discovered from the issuer URL and cached.

    `internal_url` is where this process reaches the realm when the public issuer is not
    reachable from inside the cluster (WP-014). Keycloak, run with a dynamic back channel, then
    answers discovery with internal token / keys / logout endpoints but the public authorization
    endpoint and issuer, so browsers and token checks keep using the public URL.
    """

    def __init__(
        self, issuer: str, http: httpx.AsyncClient, internal_url: str | None = None
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.discovery_base = (internal_url or issuer).rstrip("/")
        self._http = http
        self._metadata: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._fetched_at = 0.0

    def _backchannel(self, url: str) -> str:
        """An endpoint this process calls itself, moved to the internal base when there is one.

        Keycloak's dynamic back channel already answers internal token and key URLs, but keeps
        the logout and revocation endpoints on the public host (browsers use them too).
        """
        if self.discovery_base != self.issuer and url.startswith(self.issuer + "/"):
            return self.discovery_base + url[len(self.issuer) :]
        return url

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IdentityProviderUnavailable from exc
        if not isinstance(data, dict):
            raise IdentityProviderUnavailable
        return data

    async def metadata(self) -> dict[str, Any]:
        """OIDC discovery document (cached for five minutes)."""
        if self._metadata is None or time.monotonic() - self._fetched_at > _METADATA_TTL_SECONDS:
            self._metadata = await self._get_json(self.discovery_base + DISCOVERY_PATH)
            self._jwks = None
            self._fetched_at = time.monotonic()
        return self._metadata

    async def jwks(self, *, refresh: bool = False) -> dict[str, Any]:
        """Keycloak's signing keys (refetched once when a token names an unknown key)."""
        if self._jwks is None or refresh:
            self._jwks = await self._get_json(
                self._backchannel((await self.metadata())["jwks_uri"])
            )
        return self._jwks

    async def authorization_url(  # noqa: PLR0913 - keyword-only request parts, most optional
        self,
        client: ClientCredentials,
        *,
        state: str,
        nonce: str,
        pkce: PkcePair,
        locale: str | None = None,
        organization: str | None = None,
    ) -> str:
        """Where to send the browser to log in.

        `organization` (a tenant's address, WP-017) asks for that organization only: Keycloak
        brands its pages with it, and the scope cannot be combined with `organization:*`.
        """
        params = {
            "client_id": client.client_id,
            "response_type": "code",
            "redirect_uri": client.redirect_uri,
            "scope": SCOPES
            if organization is None
            else f"{BASE_SCOPES} organization:{organization}",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
        }
        if locale:
            params["ui_locales"] = locale
        return f"{(await self.metadata())['authorization_endpoint']}?{urlencode(params)}"

    async def _token_request(self, client: ClientCredentials, form: dict[str, str]) -> TokenSet:
        endpoint = self._backchannel((await self.metadata())["token_endpoint"])
        try:
            response = await self._http.post(
                endpoint,
                data={**form, "client_id": client.client_id, "client_secret": client.client_secret},
            )
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailable from exc
        if response.status_code in {400, 401}:
            raise TokenRejectedError(response.json().get("error", "invalid_grant"))
        if response.status_code != 200:  # noqa: PLR2004 - HTTP OK
            raise IdentityProviderUnavailable
        body = response.json()
        return TokenSet(
            access_token=body["access_token"],
            refresh_token=body["refresh_token"],
            id_token=body["id_token"],
            expires_in=int(body.get("expires_in", 60)),
        )

    async def exchange_code(
        self, client: ClientCredentials, *, code: str, verifier: str
    ) -> TokenSet:
        """Authorization code + PKCE verifier → tokens."""
        return await self._token_request(
            client,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": client.redirect_uri,
                "code_verifier": verifier,
            },
        )

    async def refresh(self, client: ClientCredentials, refresh_token: str) -> TokenSet:
        """Refresh token → new tokens (TokenRejectedError if the Keycloak session is gone)."""
        return await self._token_request(
            client, {"grant_type": "refresh_token", "refresh_token": refresh_token, "scope": SCOPES}
        )

    async def verify_id_token(self, id_token: str) -> dict[str, Any]:
        """Claims of a signature-checked ID token."""
        try:
            return verify_rs256(id_token, await self.jwks())
        except InvalidTokenError:
            # Key rotation: refetch the key set once before giving up.
            return verify_rs256(id_token, await self.jwks(refresh=True))

    async def end_session(self, client: ClientCredentials, refresh_token: str) -> bool:
        """End the Keycloak SSO session from the back channel. False if Keycloak refused."""
        endpoint = self._backchannel((await self.metadata())["end_session_endpoint"])
        try:
            response = await self._http.post(
                endpoint,
                data={
                    "client_id": client.client_id,
                    "client_secret": client.client_secret,
                    "refresh_token": refresh_token,
                },
            )
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailable from exc
        return response.status_code in {200, 204}
