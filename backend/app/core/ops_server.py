"""Internal operations endpoint for one process: `/metrics`, `/healthz`, `/readyz` (WP-014).

Workers have no HTTP server of their own, so Kubernetes probes and Prometheus need this one; the
API uses it only for `/metrics` (its health lives on the public port, ADR-018). It listens on a
separate port (`SUPPORTX_METRICS_PORT`, 9464) that is never routed publicly (architecture.md §15).

Deliberately tiny and dependency-free (asyncio streams): GET only, no request bodies, a short read
timeout, one response per connection. Because it runs on the process's own event loop, a blocked
loop makes `/healthz` time out, which is exactly what a liveness probe should notice.
"""

import asyncio
import contextlib
from collections.abc import Callable

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from app.core.logging import get_logger

log = get_logger(__name__)

_READ_TIMEOUT_SECONDS = 5.0
_MAX_REQUEST_LINE = 2048


def _response(status: str, body: bytes, content_type: str = "text/plain; charset=utf-8") -> bytes:
    head = (
        f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    )
    return head.encode() + body


class OpsServer:
    """Serves the process's metrics and, for workers, its liveness and readiness."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        ready: Callable[[], bool] = lambda: True,
    ) -> None:
        self.host = host
        self.port = port
        self.ready = ready
        self._server: asyncio.Server | None = None

    def handle_path(self, path: str) -> bytes:
        """The full HTTP response for one GET path."""
        if path == "/metrics":
            return _response("200 OK", generate_latest(REGISTRY), CONTENT_TYPE_LATEST)
        if path == "/healthz":
            return _response("200 OK", b"ok\n")
        if path == "/readyz":
            if self.ready():
                return _response("200 OK", b"ready\n")
            return _response("503 Service Unavailable", b"not ready\n")
        return _response("404 Not Found", b"not found\n")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), _READ_TIMEOUT_SECONDS)
            parts = line[:_MAX_REQUEST_LINE].decode("latin-1").split()
            if len(parts) >= 2 and parts[0] in {"GET", "HEAD"}:  # noqa: PLR2004 - method and path
                path = parts[1].split("?", 1)[0]
                response = self.handle_path(path)
                if parts[0] == "HEAD":
                    response = response.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
            else:
                response = _response("405 Method Not Allowed", b"")
            writer.write(response)
            await writer.drain()
        except (TimeoutError, ConnectionError, UnicodeDecodeError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    async def start(self) -> None:
        """Start listening (returns at once; the server runs on the current loop)."""
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        # Port 0 (tests) picks a free port: report the real one.
        self.port = int(self._server.sockets[0].getsockname()[1])
        log.info("ops_server_listening", host=self.host, port=self.port)

    async def stop(self) -> None:
        """Stop listening."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
