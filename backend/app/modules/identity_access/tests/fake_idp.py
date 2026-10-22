"""A fake Keycloak realm for tests: discovery, JWKS, token and logout endpoints over
httpx.MockTransport, issuing real RS256-signed ID tokens (so signature checks are exercised)."""

import base64
import json
import secrets
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ISSUER = "http://idp.test/realms/supportx"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _int_b64(value: int) -> str:
    return _b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


@dataclass
class FakeUser:
    """A user the fake IdP can log in."""

    subject: str
    email: str
    name: str
    locale: str = "en"
    roles: tuple[str, ...] = ("technician",)
    organizations: dict[str, uuid.UUID] = field(default_factory=dict)  # alias -> tenant id


@dataclass
class FakeIdp:
    """Keycloak stand-in. `pending` maps issued codes to (user, nonce, client)."""

    key: rsa.RSAPrivateKey = field(default_factory=lambda: rsa.generate_private_key(65537, 2048))
    kid: str = "kid-1"
    available: bool = True
    refresh_ok: bool = True
    access_lifetime: int = 300
    pending: dict[str, tuple[FakeUser, str, str]] = field(default_factory=dict)
    refresh_tokens: dict[str, tuple[FakeUser, str]] = field(default_factory=dict)
    ended_sessions: list[str] = field(default_factory=list)
    token_overrides: dict[str, Any] = field(default_factory=dict)
    now: Callable[[], float] = time.time  # point at a FrozenClock to keep token times in step

    # --- token minting -------------------------------------------------------------------------

    def sign(self, claims: dict[str, Any], *, alg: str = "RS256", kid: str | None = None) -> str:
        header = _b64(json.dumps({"alg": alg, "kid": kid or self.kid, "typ": "JWT"}).encode())
        payload = _b64(json.dumps(claims).encode())
        signature = self.key.sign(
            f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256()
        )
        return f"{header}.{payload}.{_b64(signature)}"

    def claims_for(self, user: FakeUser, client_id: str, nonce: str | None) -> dict[str, Any]:
        now = int(self.now())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": client_id,
            "azp": client_id,
            "sub": user.subject,
            "exp": now + self.access_lifetime,
            "iat": now,
            "email": user.email,
            "name": user.name,
            "locale": user.locale,
            "sid": "kc-session-" + user.subject,
            "supportx_roles": list(user.roles),
            "supportx_organizations": {
                alias: {"tenant_id": [str(tenant)], "id": str(uuid.uuid4())}
                for alias, tenant in user.organizations.items()
            },
        }
        if nonce is not None:
            claims["nonce"] = nonce
        return {**claims, **self.token_overrides}

    def issue_code(self, authorize_url: str, user: FakeUser) -> tuple[str, str]:
        """What Keycloak would do after the user logs in: returns (code, state)."""
        query = parse_qs(urlsplit(authorize_url).query)
        code = secrets.token_urlsafe(16)
        self.pending[code] = (user, query["nonce"][0], query["client_id"][0])
        return code, query["state"][0]

    def _tokens(self, user: FakeUser, client_id: str, nonce: str | None) -> dict[str, Any]:
        refresh = secrets.token_urlsafe(16)
        self.refresh_tokens[refresh] = (user, client_id)
        return {
            "access_token": "at-" + secrets.token_urlsafe(8),
            "refresh_token": refresh,
            "id_token": self.sign(self.claims_for(user, client_id, nonce)),
            "expires_in": self.access_lifetime,
        }

    # --- HTTP ----------------------------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - one return per endpoint
        if not self.available:
            msg = "keycloak down"
            raise httpx.ConnectError(msg, request=request)
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            base = f"{ISSUER}/protocol/openid-connect"
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{base}/auth",
                    "token_endpoint": f"{base}/token",
                    "end_session_endpoint": f"{base}/logout",
                    "jwks_uri": f"{base}/certs",
                },
            )
        if path.endswith("/certs"):
            numbers = self.key.public_key().public_numbers()
            jwk = {
                "kty": "RSA",
                "kid": self.kid,
                "alg": "RS256",
                "n": _int_b64(numbers.n),
                "e": _int_b64(numbers.e),
            }
            return httpx.Response(200, json={"keys": [jwk]})
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if path.endswith("/token"):
            if form["grant_type"] == "authorization_code":
                entry = self.pending.pop(form["code"], None)
                if entry is None:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                user, nonce, client_id = entry
                return httpx.Response(200, json=self._tokens(user, client_id, nonce))
            entry2 = self.refresh_tokens.get(form["refresh_token"])
            if entry2 is None or not self.refresh_ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._tokens(entry2[0], entry2[1], None))
        if path.endswith("/logout"):
            self.ended_sessions.append(form.get("refresh_token", ""))
            return httpx.Response(204)
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def public_pem(self) -> bytes:
        return self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )


class MemoryKeyValue:
    """In-memory `KeyValue` (no TTL simulation: expiry is tested via session timestamps)."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def getdel(self, key: str) -> bytes | None:
        return self.data.pop(key, None)

    async def set(self, key: str, value: bytes, *, px: int, nx: bool = False) -> bool | None:
        assert px > 0
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0
