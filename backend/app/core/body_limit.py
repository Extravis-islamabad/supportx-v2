"""A cap on how much of a request body the API reads (lane B; found reviewing #495).

FastAPI reads and parses a JSON body completely before the route or any dependency runs, so a
check on `Content-Length` inside a route caps nothing, and a chunked request sends no length at
all. This middleware counts the bytes as they arrive and stops the request at the cap with
413 `payload_too_large` (RFC 9457, labelled like any error), whatever the headers say.

- Every request gets `DEFAULT_MAX_BYTES`. A declared `Content-Length` above the cap is refused
  before anything is read; a body without one is refused at the first chunk that passes it.
- The few routes that stream a large body (file uploads, imports) raise their own cap with the
  `body_limit(n)` dependency, which runs before they read the stream (they have no body
  parameter, so FastAPI reads nothing first). They keep their own, more precise checks too. A
  raised cap applies to bytes counted from then on, and a declared length is checked against
  the raised cap only, as the early check skips requests whose route raises it.
- `MAX_ANY_BYTES` is the most any route may raise it to.

The chart routes through the Gateway API or a plain Ingress, neither of which has a standard
body-size setting; an operator's proxy may cap earlier (docs/deployment.md), but the API never
relies on it.
"""

import re
from http import HTTPStatus

from fastapi import Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_MAX_BYTES = 1024 * 1024  # JSON bodies: the largest real one (a rich text reply) is far less
MAX_ANY_BYTES = 128 * 1024 * 1024  # uploads: a tenant's file cap is at most 100 MB
SCOPE_KEY = "supportx.body_limit"
# Matched on scope["path"], which includes no root_path: SupportX mounts the API at /api/v1 with
# no root_path today; one would have to be prefixed here (lane C, #496).
# Routes that raise their cap (body_limit): their early `Content-Length` check waits for the
# route's own number. Method and path pattern, under /api/v1.
# The workflow and holiday imports cap themselves below DEFAULT_MAX_BYTES, so are not listed.
STREAMED: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(r"^/api/v1/files$")),
    ("POST", re.compile(r"^/api/v1/people-imports$")),
    ("POST", re.compile(r"^/api/v1/assets/imports$")),
    ("POST", re.compile(r"^/api/v1/[a-z-]+/checklist-library/import$")),
)


class RequestTooLarge(StarletteHTTPException):
    """The body passed its cap: 413 `payload_too_large`.

    An HTTPException, so FastAPI's own body reading lets it through instead of making it a 400.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(status_code=413, headers={"Connection": "close"})
        self.limit = limit


def _streamed(scope: Scope) -> bool:
    method, path = scope.get("method", ""), scope.get("path", "")
    return any(method == m and pattern.match(path) for m, pattern in STREAMED)


def _declared(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class BodyLimitMiddleware:
    """Counts each request's body bytes against its cap (see the module docstring)."""

    def __init__(self, app: ASGIApp, default_max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.app = app
        self.default = default_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Set the request's default cap, refuse a declared length above it, count the rest."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        state[SCOPE_KEY] = self.default
        declared = _declared(scope)
        if declared is not None and declared > self.default and not _streamed(scope):
            await _refuse(scope, send, self.default)
            return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                limit = int(state.get(SCOPE_KEY, self.default))
                if seen > limit:
                    raise RequestTooLarge(limit)
            return message

        await self.app(scope, counted, send)


async def _refuse(scope: Scope, send: Send, limit: int) -> None:
    """413 before reading anything, as the error handlers would write it."""
    from app.core.errors import problem, problem_response  # noqa: PLC0415 - errors imports this

    response = problem_response(
        problem(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            "payload_too_large",
            params={"max_bytes": limit},
            instance=scope.get("path", ""),
        ),
        headers={"Connection": "close"},
    )
    await response(scope, _drain, send)


async def _drain() -> Message:  # never asked for: the response does not read the request
    return {"type": "http.disconnect"}


class RaiseCap:
    """A route dependency that raises this request's cap (see `body_limit`)."""

    def __init__(self, max_bytes: int) -> None:
        if not 0 < max_bytes <= MAX_ANY_BYTES:
            msg = f"body_limit must be between 1 and {MAX_ANY_BYTES} bytes"
            raise ValueError(msg)
        self.max_bytes = max_bytes

    def __call__(self, request: Request) -> None:
        """Raise the cap before the route reads its stream."""
        request.scope.setdefault("state", {})[SCOPE_KEY] = self.max_bytes


def body_limit(max_bytes: int) -> RaiseCap:
    """The dependency for a route that streams a large body (an upload or an import).

    Its path must be in STREAMED too (a declared length is checked against its own cap, not the
    default); tests/test_body_limit.py fails when the two disagree.
    """
    return RaiseCap(max_bytes)
