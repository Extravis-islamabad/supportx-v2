"""ASGI middleware: request context and security headers (architecture.md §10, §11; WP-004).

Both are plain ASGI middleware rather than BaseHTTPMiddleware, so contextvars flow into the
endpoint and streaming responses are not buffered.
"""

import time
from collections.abc import Iterable

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import internal_error_response, notify_error
from app.core.logging import get_logger
from app.core.request_context import (
    REQUEST_ID_HEADER,
    accept_request_id,
    bind_request,
    clear_request,
)

log = get_logger("app.access")

# API responses are JSON only: nothing may load scripts, frames or other resources from them.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Swagger UI (dev docs only) loads its bundle from jsDelivr and needs inline bootstrapping.
DOCS_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: "
    "https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)
BASE_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"),
    ("Cache-Control", "no-store"),
)
HSTS = ("Strict-Transport-Security", "max-age=63072000; includeSubDomains")


class RequestContextMiddleware:
    """Give every request an ID and turn unhandled exceptions into a generic 500 problem.

    The ID is bound for logging and echoed back in X-Request-ID; one access line is logged per
    request. Clients never see a stack trace.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI connection."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = accept_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        bind_request(request_id)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            log.exception("unhandled_exception", path=scope.get("path"))
            if response_started:
                raise
            await notify_error(Request(scope), 500, "internal_error")
            await internal_error_response(scope.get("path"))(scope, receive, send_with_request_id)
        finally:
            log.info(
                "request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            clear_request()


class SecurityHeadersMiddleware:
    """Add browser security headers to every HTTP response."""

    def __init__(self, app: ASGIApp, *, docs_paths: Iterable[str] = (), hsts: bool = False) -> None:
        self.app = app
        self.docs_paths = frozenset(docs_paths)
        self.headers = BASE_SECURITY_HEADERS + ((HSTS,) if hsts else ())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI connection."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        csp = DOCS_CSP if scope.get("path") in self.docs_paths else API_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers:
                    headers.setdefault(name, value)
                headers.setdefault("Content-Security-Policy", csp)
            await send(message)

        await self.app(scope, receive, send_with_headers)
