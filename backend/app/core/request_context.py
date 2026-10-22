"""Per-request context: request ID now, tenant ID from WP-006 (architecture.md §15).

Values live in structlog's contextvars, so every log line written while handling a request carries
them automatically, including lines from libraries routed through stdlib logging.
"""

import re

import structlog
import uuid_utils

REQUEST_ID_HEADER = "X-Request-ID"
# Client-supplied IDs are accepted only if they are short and plain, so they cannot inject
# content into logs or headers; anything else is replaced with a fresh ID.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def new_request_id() -> str:
    """Time-ordered request ID (UUIDv7), so IDs sort by arrival in logs."""
    return str(uuid_utils.uuid7())


def accept_request_id(candidate: str | None) -> str:
    """Use the caller's X-Request-ID when it is safe, otherwise generate one."""
    if candidate and _VALID_REQUEST_ID.fullmatch(candidate):
        return candidate
    return new_request_id()


def bind_request(request_id: str) -> None:
    """Start a fresh logging context for one request."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, tenant_id=None)


def clear_request() -> None:
    """Drop the request's logging context."""
    structlog.contextvars.clear_contextvars()


def current_request_id() -> str | None:
    """Request ID of the request being handled, if any."""
    value = structlog.contextvars.get_contextvars().get("request_id")
    return value if isinstance(value, str) else None
