"""Centrifugo server API client (WP-011): publish, disconnect, presence, batch.

Used by the fan-out worker (publications and revocation) and by the BFF (cut a signed-out
session's connection at once). Calls go to `{centrifugo_api_url}/api/<method>` with the API key;
the key never leaves the backend.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings

# Disconnect codes 4000-4499 tell the client to reconnect (4500+ would be terminal). The client
# reconnects with fresh tokens, so channels the user lost are refused from then on (§8.2).
ACCESS_CHANGED = 4000
SESSION_ENDED = 4001


class CentrifugoError(RuntimeError):
    """Centrifugo refused a call or could not be reached."""


@dataclass(frozen=True)
class Publish:
    """One publication."""

    channel: str
    data: Mapping[str, Any]
    # Centrifugo drops a second publication with the same key (within minutes): a retried batch
    # after a crash or timeout does not show the same change twice.
    idempotency_key: str | None = None

    def command(self) -> dict[str, Any]:
        """As a batch command."""
        params: dict[str, Any] = {"channel": self.channel, "data": dict(self.data)}
        if self.idempotency_key is not None:
            params["idempotency_key"] = self.idempotency_key
        return {"publish": params}


@dataclass(frozen=True)
class Disconnect:
    """Close every connection of one realtime user (`{tenant}:{user}`)."""

    user: str
    code: int = ACCESS_CHANGED
    reason: str = "access changed"

    def command(self) -> dict[str, Any]:
        """As a batch command."""
        return {
            "disconnect": {
                "user": self.user,
                "disconnect": {"code": self.code, "reason": self.reason},
            }
        }


Command = Publish | Disconnect


class CentrifugoClient:
    """Thin async client for the server HTTP API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "CentrifugoClient | None":
        """None when realtime is not configured (dev without the stack, most unit tests)."""
        if settings.centrifugo_api_url is None or settings.centrifugo_api_key is None:
            return None
        return cls(
            settings.centrifugo_api_url,
            settings.centrifugo_api_key.get_secret_value(),
            timeout=settings.centrifugo_timeout_seconds,
        )

    async def call(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """One API method; raises CentrifugoError on transport errors and error replies."""
        try:
            response = await self._http.post(f"/api/{method}", json=dict(params))
        except httpx.HTTPError as exc:
            msg = f"centrifugo {method}: {type(exc).__name__}"
            raise CentrifugoError(msg) from exc
        if response.status_code != httpx.codes.OK:
            msg = f"centrifugo {method}: HTTP {response.status_code}"
            raise CentrifugoError(msg)
        body: dict[str, Any] = response.json()
        if "error" in body:
            msg = f"centrifugo {method}: {body['error'].get('message', 'error')}"
            raise CentrifugoError(msg)
        return body

    async def publish(self, publication: Publish) -> None:
        """Publish one message."""
        await self.call("publish", publication.command()["publish"])

    async def disconnect(
        self, user: str, code: int = ACCESS_CHANGED, reason: str = "access changed"
    ) -> None:
        """Close the user's connections; they reconnect with fresh tokens."""
        await self.call("disconnect", Disconnect(user, code, reason).command()["disconnect"])

    async def presence(self, channel: str) -> dict[str, Any]:
        """Who is subscribed to `channel` (clients with their connection info)."""
        body = await self.call("presence", {"channel": channel})
        presence: dict[str, Any] = body.get("result", {}).get("presence", {})
        return presence

    async def batch(self, commands: Sequence[Command]) -> int:
        """Run many commands in one round trip (in parallel); returns how many failed."""
        if not commands:
            return 0
        body = await self.call(
            "batch", {"commands": [c.command() for c in commands], "parallel": True}
        )
        replies: list[dict[str, Any]] = body.get("replies", [])
        return sum(1 for reply in replies if "error" in reply)

    async def aclose(self) -> None:
        """Close the HTTP connection pool."""
        await self._http.aclose()
