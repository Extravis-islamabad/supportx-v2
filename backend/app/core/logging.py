"""Structured logging (architecture.md §15; WP-004).

One structlog pipeline for our own logs and for stdlib loggers (uvicorn, libraries): JSON lines in
production, readable console output in dev. Every line carries `request_id` and `tenant_id` (bound
per request through contextvars; `None` outside a request, tenant arrives with WP-006) plus the
OpenTelemetry trace and span IDs when a span is active. Secrets and obvious PII are redacted at
the source, before anything is rendered (§15 "PII redaction at source").
"""

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from opentelemetry import trace

from app.core.config import Settings

REDACTED = "[REDACTED]"

# Keys whose values are never logged. Matched case-insensitively as a substring of the key name,
# so `db_password`, `X-Api-Key` and `user_email` are all caught.
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "x-api-key",
    "credential",
    "private_key",
    "session",
    "email",
    "phone",
    "mobile",
    "national_id",
    "passport",
    "iban",
    "card_number",
)
# user:password@ inside any URL-looking string.
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]*:[^/\s@]*@")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Library loggers that install their own handlers; they are routed through ours instead.
_STDLIB_LOGGERS_TO_ROUTE = ("uvicorn", "uvicorn.error", "asyncio")
_installed_handler: logging.Handler | None = None


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def redact(value: Any) -> Any:  # noqa: ANN401 - log values are arbitrary by nature
    """Return `value` with sensitive keys masked and credentials/emails scrubbed from strings."""
    if isinstance(value, Mapping):
        return {
            k: REDACTED if isinstance(k, str) and _is_sensitive(k) else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(redact(v) for v in value)
    if isinstance(value, str):
        return _EMAIL.sub(REDACTED, _URL_CREDENTIALS.sub(rf"\g<scheme>{REDACTED}@", value))
    return value


def redact_processor(
    _logger: Any,  # noqa: ANN401 - structlog processor signature
    _method: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Apply `redact` to every field of a structlog event."""
    return {
        key: REDACTED if _is_sensitive(key) else redact(value) for key, value in event_dict.items()
    }


def add_context_defaults(
    _logger: Any,  # noqa: ANN401 - structlog processor signature
    _method: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Guarantee `request_id` and `tenant_id` on every line (None outside a request)."""
    event_dict.setdefault("request_id", None)
    event_dict.setdefault("tenant_id", None)
    return event_dict


def add_trace_context(
    _logger: Any,  # noqa: ANN401 - structlog processor signature
    _method: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Attach the current OpenTelemetry trace/span IDs so logs and traces can be joined."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_context_defaults,
        add_trace_context,
        structlog.stdlib.ExtraAdder(),
        redact_processor,
    ]


def configure_logging(settings: Settings) -> None:
    """Route structlog and stdlib logging through one renderer chosen by the profile."""
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.effective_log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    shared = _shared_processors()
    structlog.configure(
        processors=[
            *shared,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )
    # Replace only the handler we installed earlier (create_app may run many times in tests);
    # handlers added by others, such as pytest's log capture, are left alone.
    global _installed_handler  # noqa: PLW0603 - one handler per process, swapped on reconfigure
    root = logging.getLogger()
    if _installed_handler is not None:
        root.removeHandler(_installed_handler)
    root.addHandler(handler)
    _installed_handler = handler
    root.setLevel(settings.log_level.upper())
    for name in _STDLIB_LOGGERS_TO_ROUTE:
        stdlib_logger = logging.getLogger(name)
        stdlib_logger.handlers = []
        stdlib_logger.propagate = True
    # RequestContextMiddleware writes the access line (with request ID, status, duration), so
    # uvicorn's own access log would only duplicate it.
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers = []
    uvicorn_access.propagate = False
    # HTTP client libraries log every outgoing request at INFO; keep only their warnings.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger named after the calling module."""
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
