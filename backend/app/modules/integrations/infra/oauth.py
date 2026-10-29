"""OAuth 2.0 for API mailboxes: Microsoft identity platform and Google (WP-024 session 2).

The customer's own app (D-109 (2), docs/guides/mail-oauth-apps.md) proves itself with a client
secret or, for Microsoft, a certificate whose private key signs a short client assertion
(RFC 7523). Tokens are asked for the least scopes that read, mark and move mail
(`domain.mailboxes.scopes_for`).

Nothing here logs a secret, a token, an authorization code or a response body: a refusal is
reduced to a reason code the mail page shows (`oauth_*`), so a provider's error text (which can
echo request parameters) never reaches logs or screens.
"""

import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import urlencode

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.modules.integrations.domain.mailboxes import CredentialKind, MailboxProtocol
from app.modules.integrations.infra.imap import MailboxUnavailableError

TIMEOUT_SECONDS = 30.0
ASSERTION_SECONDS = 600
# Reason codes (labels "mailbox.reason.<code>"); each says what an admin can do about it.
OAUTH_NOT_CONNECTED = "oauth_not_connected"  # nobody has signed in as the mailbox yet
OAUTH_CONSENT_REVOKED = "oauth_consent_revoked"  # invalid_grant: sign in again
OAUTH_CLIENT_REJECTED = "oauth_client_rejected"  # invalid_client: secret expired or wrong
OAUTH_NOT_ALLOWED = "oauth_not_allowed"  # the app may not read this mailbox (scope, policy)
OAUTH_UNREACHABLE = "oauth_unreachable"
OAUTH_CERTIFICATE_INVALID = "oauth_certificate_invalid"
OAUTH_WRONG_ACCOUNT = "oauth_wrong_account"  # signed in as another account than the mailbox


@dataclass(frozen=True)
class Endpoints:
    """Where Microsoft and Google answer (settings; sovereign clouds and tests change them)."""

    microsoft_login: str = "https://login.microsoftonline.com"
    graph: str = "https://graph.microsoft.com/v1.0"
    google_authorize: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_token: str = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL
    gmail: str = "https://gmail.googleapis.com/gmail/v1"


@dataclass(frozen=True)
class Client:
    """The customer's OAuth app as one mailbox uses it."""

    protocol: MailboxProtocol
    client_id: str
    credential_kind: CredentialKind
    credential: str  # the client secret, or a PEM with the private key and its certificate
    directory_id: str | None = None  # Microsoft Entra tenant (directory) ID


@dataclass(frozen=True)
class Tokens:
    """What a token endpoint gave; `refresh_token` only for delegated sign-in."""

    access_token: str
    refresh_token: str | None
    expires_in: int


@dataclass(frozen=True)
class Certificate:
    """A Microsoft app certificate: the signing key, its thumbprint and when it stops working."""

    key: rsa.RSAPrivateKey
    thumbprint: str  # base64url SHA-256 of the DER certificate (x5t#S256)
    expires_at: datetime


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def load_certificate(pem: str) -> Certificate:
    """The private key and certificate from one PEM (as an admin pastes it); refused if unusable."""
    data = pem.encode()
    try:
        key = serialization.load_pem_private_key(data, password=None)
        cert = x509.load_pem_x509_certificate(data)
    except ValueError as exc:
        raise MailboxUnavailableError(OAUTH_CERTIFICATE_INVALID) from exc
    if not isinstance(key, rsa.RSAPrivateKey):  # Microsoft signs client assertions with RS256
        raise MailboxUnavailableError(OAUTH_CERTIFICATE_INVALID)
    der = cert.public_bytes(serialization.Encoding.DER)
    return Certificate(key, _b64url(hashlib.sha256(der).digest()), cert.not_valid_after_utc)


def client_assertion(certificate: Certificate, client_id: str, audience: str) -> str:
    """A signed JWT that proves the app to Microsoft (RFC 7523), valid for ten minutes."""
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "x5t#S256": certificate.thumbprint}
    claims = {
        "aud": audience,
        "iss": client_id,
        "sub": client_id,
        "jti": str(uuid.uuid4()),
        "nbf": now,
        "exp": now + ASSERTION_SECONDS,
    }
    signing_input = ".".join(
        _b64url(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims)
    )
    signature = certificate.key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(signature)}"


class OAuth:
    """Token requests and consent addresses for one installation's endpoints."""

    def __init__(
        self, endpoints: Endpoints, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.endpoints = endpoints
        self._transport = transport  # tests: a fake Microsoft or Google

    def http(self) -> httpx.AsyncClient:
        """An HTTP client for the provider APIs (the readers use it too)."""
        return httpx.AsyncClient(
            transport=self._transport, timeout=TIMEOUT_SECONDS, follow_redirects=False
        )

    def token_url(self, client: Client) -> str:
        """The client's token endpoint."""
        if client.protocol is MailboxProtocol.GMAIL:
            return self.endpoints.google_token
        return f"{self.endpoints.microsoft_login}/{client.directory_id}/oauth2/v2.0/token"

    def authorize_url(  # noqa: PLR0913 - the consent request's parts, explicit
        self,
        client: Client,
        *,
        redirect_uri: str,
        scopes: tuple[str, ...],
        state: str,
        code_challenge: str,
        login_hint: str,
    ) -> str:
        """Where the admin signs in as the mailbox and allows access (PKCE, S256)."""
        query: dict[str, str] = {
            "client_id": client.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "login_hint": login_hint,
        }
        if client.protocol is MailboxProtocol.GMAIL:
            # A refresh token, and every time (Google sends one only on a fresh consent).
            query |= {"access_type": "offline", "prompt": "consent"}
            return f"{self.endpoints.google_authorize}?{urlencode(query)}"
        base = f"{self.endpoints.microsoft_login}/{client.directory_id}/oauth2/v2.0/authorize"
        return f"{base}?{urlencode(query)}"

    def _credentials(self, client: Client) -> dict[str, str]:
        if client.credential_kind is CredentialKind.CERTIFICATE:
            certificate = load_certificate(client.credential)
            return {
                "client_id": client.client_id,
                "client_assertion_type": ("urn:ietf:params:oauth:client-assertion-type:jwt-bearer"),
                "client_assertion": client_assertion(
                    certificate, client.client_id, self.token_url(client)
                ),
            }
        return {"client_id": client.client_id, "client_secret": client.credential}

    async def _token(self, client: Client, form: dict[str, str]) -> Tokens:
        try:
            async with self.http() as http:
                response = await http.post(
                    self.token_url(client), data=form | self._credentials(client)
                )
        except httpx.HTTPError as exc:
            raise MailboxUnavailableError(OAUTH_UNREACHABLE) from exc
        if response.status_code >= 400:  # noqa: PLR2004 - HTTP error range
            raise MailboxUnavailableError(_refusal(response))
        try:
            body = response.json()
            return Tokens(
                access_token=str(body["access_token"]),
                refresh_token=body.get("refresh_token"),
                expires_in=int(body.get("expires_in", 3600)),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise MailboxUnavailableError(OAUTH_UNREACHABLE) from exc

    async def app_token(self, client: Client, scopes: tuple[str, ...]) -> Tokens:
        """Client credentials (Graph application permission): no one signs in."""
        return await self._token(
            client, {"grant_type": "client_credentials", "scope": " ".join(scopes)}
        )

    async def exchange(
        self, client: Client, *, code: str, redirect_uri: str, verifier: str
    ) -> Tokens:
        """The authorization code from the consent screen, for tokens."""
        return await self._token(
            client,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
        )

    async def refresh(self, client: Client, refresh_token: str, scopes: tuple[str, ...]) -> Tokens:
        """A new access token (and, from Microsoft, a new refresh token to keep)."""
        return await self._token(
            client,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": " ".join(scopes),
            },
        )


def _refusal(response: httpx.Response) -> str:
    """The provider's error reduced to a reason code (never its text)."""
    try:
        error = str(response.json().get("error", ""))
    except ValueError:
        error = ""
    reasons: dict[str, str] = {
        "invalid_grant": OAUTH_CONSENT_REVOKED,
        "invalid_client": OAUTH_CLIENT_REJECTED,
        "unauthorized_client": OAUTH_CLIENT_REJECTED,
        "invalid_scope": OAUTH_NOT_ALLOWED,
        "access_denied": OAUTH_NOT_ALLOWED,
        "consent_required": OAUTH_CONSENT_REVOKED,
        "interaction_required": OAUTH_CONSENT_REVOKED,
    }
    if error in reasons:
        return reasons[error]
    return OAUTH_UNREACHABLE if response.status_code >= 500 else OAUTH_NOT_ALLOWED  # noqa: PLR2004


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge) for one consent (RFC 7636)."""
    verifier = _b64url(uuid.uuid4().bytes + uuid.uuid4().bytes)
    return verifier, _b64url(hashlib.sha256(verifier.encode()).digest())


Provider = Literal["microsoft", "google"]
