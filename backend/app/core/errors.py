"""RFC 9457 problem details for every error the API returns (architecture.md §10; WP-004).

Each error carries a stable machine `code`, a `message_key` the UI translates through the labels
package (CLAUDE.md rule d), optional `params` for that message, and optional field-level `errors`.
Clients never see exception names, internal messages or stack traces: unexpected exceptions become
a generic `internal_error` and the details go to the server log only.
"""

import typing
from collections.abc import Awaitable, Callable, Mapping, Sequence
from http import HTTPStatus
from typing import Any, ClassVar

import valkey.exceptions
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_core.core_schema import ErrorType
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.core.request_context import current_request_id

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_TYPE_PREFIX = "urn:supportx:problem:"

ParamValue = str | int | float | bool | None

log = get_logger(__name__)


class FieldError(BaseModel):
    """One invalid input field."""

    field: str = Field(description="Dotted path of the field, e.g. `body.title`.")
    code: str = Field(description="Stable machine code, e.g. `missing`.")
    message_key: str = Field(description="Labels key the UI translates.")
    params: dict[str, ParamValue] = Field(default_factory=dict)


class ProblemDetail(BaseModel):
    """RFC 9457 problem details, extended with SupportX's machine code and message key."""

    type: str = Field(description="URI reference identifying the problem type.")
    title: str = Field(description="Short, generic English summary (not for display).")
    status: int
    code: str = Field(description="Stable machine code clients switch on.")
    message_key: str = Field(description="Labels key the UI translates into the user's language.")
    params: dict[str, ParamValue] = Field(default_factory=dict)
    errors: list[FieldError] = Field(default_factory=list)
    instance: str | None = Field(default=None, description="Request path that failed.")
    request_id: str | None = None


class AppError(Exception):
    """Base for errors raised on purpose by services; each maps to one HTTP status and code."""

    status: ClassVar[HTTPStatus] = HTTPStatus.INTERNAL_SERVER_ERROR
    code: ClassVar[str] = "internal_error"

    def __init__(
        self,
        *,
        params: Mapping[str, ParamValue] | None = None,
        errors: Sequence[FieldError] = (),
        code: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.params = dict(params or {})
        self.errors = list(errors)
        # Response headers that belong to the problem (Retry-After, RateLimit-*, ETag ...).
        self.headers = dict(headers or {})
        # A subclass may narrow the code per raise site (e.g. `not_found` → `ticket_not_found`).
        self.instance_code = code or self.code
        super().__init__(self.instance_code)


class BadRequest(AppError):
    """The request is malformed in a way field validation does not cover."""

    status = HTTPStatus.BAD_REQUEST
    code = "bad_request"


class Unauthenticated(AppError):
    """No valid session or credentials."""

    status = HTTPStatus.UNAUTHORIZED
    code = "unauthenticated"


class PermissionDenied(AppError):
    """Authenticated, but not allowed to do this."""

    status = HTTPStatus.FORBIDDEN
    code = "permission_denied"


class EntitlementRequired(AppError):
    """The licence/plan does not include this feature or limit (WP-009, CLAUDE.md rule f)."""

    status = HTTPStatus.FORBIDDEN
    code = "entitlement_required"


class ReadOnlyMode(AppError):
    """The tenant's licence/plan is read-only: data can be viewed and exported, not changed.

    Raised for every write while the entitlement state is read_only or invalid (architecture.md
    §13.6, WP-009). `params.reason` says why (expired, suspended, licence_mismatch ...).
    """

    status = HTTPStatus.FORBIDDEN
    code = "read_only_mode"


class LimitReached(AppError):
    """Adding one more would exceed a counted licence limit (technicians, assets ...; §13.6)."""

    status = HTTPStatus.FORBIDDEN
    code = "limit_reached"


class NotFound(AppError):
    """The resource does not exist or is not visible to the caller."""

    status = HTTPStatus.NOT_FOUND
    code = "not_found"


class Conflict(AppError):
    """State conflict, e.g. stale version on update (CLAUDE.md rule g)."""

    status = HTTPStatus.CONFLICT
    code = "conflict"


class PreconditionRequired(AppError):
    """A conditional header is mandatory here, e.g. If-Match on updates (RFC 6585)."""

    status = HTTPStatus.PRECONDITION_REQUIRED
    code = "precondition_required"


class ValidationFailed(AppError):
    """Input is well-formed but breaks a business rule or field constraint."""

    status = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "validation_failed"


class RateLimited(AppError):
    """Too many requests for this token or tenant."""

    status = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"


class ServiceUnavailable(AppError):
    """A dependency is down; the client may retry later."""

    status = HTTPStatus.SERVICE_UNAVAILABLE
    code = "service_unavailable"


def message_key_for(code: str) -> str:
    """Labels key for an error code: `not_found` → `errors.not_found`."""
    return f"errors.{code}"


def problem(  # noqa: PLR0913 - mirrors the RFC 9457 members
    status: HTTPStatus,
    code: str,
    *,
    params: Mapping[str, ParamValue] | None = None,
    errors: Sequence[FieldError] = (),
    instance: str | None = None,
    request_id: str | None = None,
) -> ProblemDetail:
    """Build a problem document; `title` is the generic HTTP phrase, never internal detail."""
    return ProblemDetail(
        type=f"{PROBLEM_TYPE_PREFIX}{code}",
        title=status.phrase,
        status=status.value,
        code=code,
        message_key=message_key_for(code),
        params=dict(params or {}),
        errors=list(errors),
        instance=instance,
        request_id=request_id,
    )


def problem_response(
    detail: ProblemDetail, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    """Serialise a problem with the RFC 9457 media type."""
    return JSONResponse(
        detail.model_dump(mode="json"),
        status_code=detail.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers or {}),
    )


def internal_error_response(path: str | None) -> JSONResponse:
    """Build the only body a client ever sees for an unexpected exception."""
    return problem_response(
        problem(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "internal_error",
            instance=path,
            request_id=current_request_id(),
        )
    )


# Request-validation codes from Pydantic, in the app's own words (QA WP-021 BUG-01, BUG-02;
# QA6 AUT-01, AUT-02): Pydantic's own codes ("uuid_parsing", "date_from_datetime_parsing" ...)
# never reach a person. A missing or empty value where one is needed is "required"; a wrong date,
# number or choice says so plainly; a limit names itself; anything else is "invalid_value".
_REQUIRED_TYPES = frozenset(
    {"missing", "string_type", "int_type", "float_type", "bool_type", "uuid_type", "dict_type"}
)
_PREFIX_CODES: tuple[tuple[str, str], ...] = (
    ("date", "invalid_date"),
    ("datetime", "invalid_date"),
    ("time", "invalid_date"),
    ("timezone", "invalid_date"),
    ("int", "invalid_number"),
    ("float", "invalid_number"),
    ("decimal", "invalid_number"),
    ("complex", "invalid_number"),
    ("finite_number", "invalid_number"),
    ("multiple_of", "invalid_number"),
    ("literal_error", "invalid_choice"),
    ("enum", "invalid_choice"),
    ("string", "invalid_text"),
)
# The codes a request-validation error may carry, each with an `errors.field.<code>` label (a
# test checks every Pydantic error type lands on one of them).
VALIDATION_CODES = frozenset(
    {
        "required",
        "value_too_long",
        "value_too_short",
        "too_many_values",
        "below_minimum",
        "above_maximum",
        *(code for _, code in _PREFIX_CODES),
        "invalid_value",
    }
)
_MESSAGE_KEYS = {"value_too_long": "errors.field.value_too_long_max"}


def _limit_code(kind: str, context: Mapping[str, Any]) -> tuple[str, dict[str, ParamValue]] | None:
    """A broken length or range limit, named with its limit (None: not a limit error)."""
    found: tuple[str, dict[str, ParamValue]] | None = None
    if kind == "string_too_long":
        found = "value_too_long", {"max_length": context.get("max_length", 0)}
    elif kind in {"string_too_short", "too_short"}:
        least = context.get("min_length", 1)
        if least == 1:
            found = "required", {}
        elif kind == "string_too_short":
            found = "value_too_short", {"min": least}
        else:
            found = "invalid_value", {}
    elif kind == "too_long":
        found = "too_many_values", {"max": context.get("max_length", 0)}
    elif kind in {"greater_than", "greater_than_equal"}:
        found = "below_minimum", {"min": str(context.get("gt", context.get("ge", "")))}
    elif kind in {"less_than", "less_than_equal"}:
        found = "above_maximum", {"max": str(context.get("lt", context.get("le", "")))}
    return found


# Pydantic's own error types; any other code was raised by the app itself and has its label.
# `invalid_key` is also the app's code for a question key (catalog), so it passes through.
_PYDANTIC_TYPES = frozenset(typing.get_args(ErrorType)) - {"invalid_key"}

_EMPTY_MEANS_REQUIRED = ("uuid", "date", "datetime", "time", "int", "float", "decimal")


def _validation_code(error: Mapping[str, Any]) -> tuple[str, dict[str, ParamValue]]:
    """The app's code for one Pydantic error and the params its message uses."""
    kind = str(error.get("type", "invalid"))
    given = error.get("input", "")
    if kind not in _PYDANTIC_TYPES:
        context: Mapping[str, Any] = error.get("ctx") or {}
        return kind, {
            key: value
            for key, value in context.items()
            if isinstance(value, str | int | float | bool) and key != "error"
        }
    if kind == "missing" or (kind in _REQUIRED_TYPES and given is None):
        return "required", {}
    limit = _limit_code(kind, error.get("ctx") or {})
    if limit is not None:
        return limit
    if given in (None, "") and kind.startswith(_EMPTY_MEANS_REQUIRED):
        return "required", {}
    return next(
        (code for prefix, code in _PREFIX_CODES if kind == prefix or kind.startswith(f"{prefix}_")),
        ("invalid_value"),
    ), {}


def _field_error(error: Mapping[str, Any]) -> FieldError:
    code, params = _validation_code(error)
    return FieldError(
        field=".".join(str(part) for part in error.get("loc", ())),
        code=code,
        message_key=_MESSAGE_KEYS.get(code, f"errors.field.{code}"),
        params=params,
    )


def _field_errors(exc: RequestValidationError) -> list[FieldError]:
    return [_field_error(error) for error in exc.errors()]


# Status codes Starlette raises itself (unknown route, wrong method ...) mapped to stable codes.
_HTTP_STATUS_CODES: Mapping[int, str] = {
    HTTPStatus.BAD_REQUEST: "bad_request",
    HTTPStatus.UNAUTHORIZED: "unauthenticated",
    HTTPStatus.FORBIDDEN: "permission_denied",
    HTTPStatus.NOT_FOUND: "not_found",
    HTTPStatus.METHOD_NOT_ALLOWED: "method_not_allowed",
    HTTPStatus.NOT_ACCEPTABLE: "not_acceptable",
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "payload_too_large",
    HTTPStatus.UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    HTTPStatus.TOO_MANY_REQUESTS: "rate_limited",
}


# --- error observers -------------------------------------------------------------------------
# Core cannot import modules, so modules that must react to refused or failed requests register
# here at startup. The audit module logs refused and failed attempts at audited routes this way
# (REQ-AUD-005; ADR-027). Observers run after the request's transaction has rolled back, must
# not raise, and must be quick: they delay the error response.

ErrorObserver = Callable[[Request, int, str], Awaitable[None]]
_error_observers: list[ErrorObserver] = []


def register_error_observer(observer: ErrorObserver) -> None:
    """Call `observer(request, status, code)` for every error response."""
    _error_observers.append(observer)


def unregister_error_observer(observer: ErrorObserver) -> None:
    """Undo `register_error_observer` (app shutdown)."""
    if observer in _error_observers:
        _error_observers.remove(observer)


async def notify_error(request: Request, status: int, code: str) -> None:
    """Tell every observer about an error response; an observer's failure is only logged."""
    for observer in _error_observers:
        try:
            await observer(request, status, code)
        except Exception:
            log.warning("error_observer_failed", code=code, exc_info=True)


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - registered for AppError only
    if exc.status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        log.error("app_error", code=exc.instance_code, status=exc.status.value)
    await notify_error(request, exc.status.value, exc.instance_code)
    return problem_response(
        problem(
            exc.status,
            exc.instance_code,
            params=exc.params,
            errors=exc.errors,
            instance=request.url.path,
            request_id=current_request_id(),
        ),
        headers=exc.headers,
    )


# Valkey still unreachable after the client's own bounded retry (app/core/valkey.py), e.g. in the
# seconds of a Sentinel failover: the client may try again, so 503 with Retry-After, not a bare 500
# (k3d HA smoke, 2026-11-06: a sign-in right after the failover answered 500).
VALKEY_DOWN = (valkey.exceptions.ConnectionError, valkey.exceptions.TimeoutError)
VALKEY_RETRY_AFTER = "2"


async def _valkey_down_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, VALKEY_DOWN)  # noqa: S101 - registered for these types only
    log.warning("valkey_unavailable", error=type(exc).__name__, path=request.url.path)
    await notify_error(request, HTTPStatus.SERVICE_UNAVAILABLE.value, ServiceUnavailable.code)
    return problem_response(
        problem(
            HTTPStatus.SERVICE_UNAVAILABLE,
            ServiceUnavailable.code,
            instance=request.url.path,
            request_id=current_request_id(),
        ),
        headers={"Retry-After": VALKEY_RETRY_AFTER},
    )


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - registered for this type only
    await notify_error(request, HTTPStatus.UNPROCESSABLE_ENTITY.value, "validation_failed")
    return problem_response(
        problem(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "validation_failed",
            errors=_field_errors(exc),
            instance=request.url.path,
            request_id=current_request_id(),
        )
    )


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 - registered for this type only
    status = HTTPStatus(exc.status_code)
    code = _HTTP_STATUS_CODES.get(status, "internal_error" if status >= 500 else "bad_request")  # noqa: PLR2004 - 5xx boundary
    return problem_response(
        problem(status, code, instance=request.url.path, request_id=current_request_id()),
        headers=exc.headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Map every error type to problem details.

    Unexpected exceptions are handled one layer out, in RequestContextMiddleware, so they still
    get a request ID and security headers.
    """
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    for kind in VALKEY_DOWN:
        app.add_exception_handler(kind, _valkey_down_handler)
