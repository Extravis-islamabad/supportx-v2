"""Centrifugo connection and subscription tokens (architecture.md §8.2; WP-011).

Both are HS256 JWTs signed with the key Centrifugo verifies (`client.token.hmac_secret_key`).
They carry only what Centrifugo needs: who (`sub` = `{tenant}:{user}`), until when, for which
channel, and the viewer's display name for presence. Never a session ID, role or permission.
Built with the standard library: a JWT is three base64url parts and one HMAC.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Mapping
from typing import Any

AUDIENCE = "supportx-realtime"
ISSUER = "supportx-api"


def realtime_user(tenant_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """Centrifugo user ID: per tenant, so revoking one tenant's access leaves the others alone."""
    return f"{tenant_id}:{user_id}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign(claims: Mapping[str, Any], secret: str) -> str:
    """An HS256 JWT."""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps(dict(claims), separators=(",", ":"), default=str).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(signature)}"


def decode_unverified(token: str) -> dict[str, Any]:
    """The claims, without checking the signature (tests and diagnostics only)."""
    payload = token.split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    claims: dict[str, Any] = json.loads(base64.urlsafe_b64decode(padded))
    return claims


def connection_token(  # noqa: PLR0913 - every claim is a separate, explicit input
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    display_name: str,
    secret: str,
    ttl_seconds: int,
    now: float | None = None,
) -> str:
    """Lets one signed-in user of one tenant connect. `info` is shown to co-viewers (presence)."""
    issued = int(now if now is not None else time.time())
    return sign(
        {
            "sub": realtime_user(tenant_id, user_id),
            "aud": AUDIENCE,
            "iss": ISSUER,
            "iat": issued,
            "exp": issued + ttl_seconds,
            "info": {"user_id": str(user_id), "name": display_name},
        },
        secret,
    )


def subscription_token(  # noqa: PLR0913 - every claim is a separate, explicit input
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    channel: str,
    secret: str,
    ttl_seconds: int,
    presence: bool = False,
    now: float | None = None,
) -> str:
    """Lets that user join one channel, after the policy layer allowed it.

    `presence` turns on presence and join/leave messages for this subscription only (record
    channels): list channels with thousands of subscribers must not broadcast every join.
    """
    issued = int(now if now is not None else time.time())
    claims: dict[str, Any] = {
        "sub": realtime_user(tenant_id, user_id),
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": issued,
        "exp": issued + ttl_seconds,
        "channel": channel,
    }
    if presence:
        claims["override"] = {
            "presence": {"value": True},
            "join_leave": {"value": True},
            "force_push_join_leave": {"value": True},
        }
    return sign(claims, secret)
