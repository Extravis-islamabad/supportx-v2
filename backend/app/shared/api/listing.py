"""List endpoints: sorting, signed cursors, keyset pagination and the page envelope (WP-008).

    GET /api/v1/users?status=active&sort=-last_login_at,display_name&limit=25
    GET /api/v1/users?filter={"field":"user_type","op":"eq","value":"technician"}&cursor=<next>

Sorting: up to three allowlisted fields (`-` = descending); the record ID is always appended as
the final tie-breaker, so the order is total and pages never overlap or skip rows.

Pagination is keyset ("seek"), not OFFSET: the cursor holds the last row's sort values and ID, and
the next page is "rows after that position". Rows inserted meanwhile appear in the right place
instead of shifting every later page (architecture.md §10). NULLs sort as the largest value, as
PostgreSQL does by default.

Cursors are opaque to clients and signed (HMAC-SHA256). The signature covers the endpoint, the
tenant, the user, the sort and a fingerprint of the filter: a cursor that was tampered with, or is
reused by another tenant or user, on another endpoint, or with a different filter or sort, is
rejected with 400 `invalid_cursor`.
"""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, tzinfo
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, Select, and_, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import TenantSession
from app.core.errors import BadRequest, FieldError, ParamValue, ValidationFailed
from app.core.tenancy import TenantContext, resolve_tenant
from app.shared.api.filters import (
    DEFAULT_LIMITS,
    FieldType,
    FilterField,
    ResourceFields,
    compile_filter,
    compile_simple,
    parse_filter_json,
)

MAX_SORT_FIELDS = 3
TOTAL_CAP = 10_000
RESERVED_PARAMETERS = frozenset({"filter", "sort", "limit", "cursor", "include_total"})
_CURSOR_VERSION = 1


# --- envelope ------------------------------------------------------------------------------------


class Page[ItemT](BaseModel):
    """Standard list response."""

    items: list[ItemT]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page.")
    has_more: bool
    estimated_total: int | None = Field(
        default=None,
        description=(
            "Only with include_total=true: matching rows, counted up to 10,000 "
            "(10,000 means 'at least')."
        ),
    )


# --- sorting -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SortKey:
    """One ORDER BY term."""

    name: str
    column: Any  # ORM column attribute; Any: SQLAlchemy generics
    type: FieldType
    descending: bool


def parse_sort(text: str | None, resource: ResourceFields) -> list[SortKey]:
    """`-created_at,display_name` → sort keys, always ending with the ID (ascending)."""
    terms = [t.strip() for t in (text or ",".join(resource.default_sort)).split(",") if t.strip()]
    if not terms or len(terms) > MAX_SORT_FIELDS:
        raise _invalid(
            at="sort",
            field_code="invalid_sort",
            problem="invalid_sort",
            params={"max_fields": MAX_SORT_FIELDS},
        )
    keys: list[SortKey] = []
    for term in terms:
        descending = term.startswith("-")
        name = term.removeprefix("-")
        spec = resource.get(name)
        if spec is None or not spec.sortable:
            raise _invalid(
                at="sort",
                field_code="unknown_sort_field",
                problem="invalid_sort",
                params={"field": name[:64]},
            )
        if any(key.name == name for key in keys):
            raise _invalid(
                at="sort",
                field_code="duplicate_sort_field",
                problem="invalid_sort",
                params={"field": name},
            )
        keys.append(SortKey(name, spec.column, spec.type, descending))
    keys.append(SortKey("id", resource.id_column, FieldType.UUID, descending=False))
    return keys


def order_by(keys: Sequence[SortKey]) -> list[Any]:
    """ORDER BY terms (NULLs largest: last ascending, first descending)."""
    return [
        key.column.desc().nulls_first() if key.descending else key.column.asc().nulls_last()
        for key in keys
    ]


def sort_signature(keys: Sequence[SortKey]) -> str:
    """Canonical text of a sort, bound into cursors."""
    return ",".join(("-" if k.descending else "") + k.name for k in keys)


# --- keyset --------------------------------------------------------------------------------------


def _after(key: SortKey, value: Any) -> ColumnElement[bool]:  # noqa: ANN401 - typed by key
    """Rows strictly after `value` in this key's direction (NULL = largest)."""
    column = key.column
    if value is None:
        # Ascending, NULLs come last: nothing is strictly after them (ties go to the next key).
        # Descending, NULLs come first: every non-NULL value is after them.
        return column.is_not(None) if key.descending else false()
    if key.descending:
        return column < value  # type: ignore[no-any-return]  # Any column attribute
    return or_(column > value, column.is_(None))


def _equal(key: SortKey, value: Any) -> ColumnElement[bool]:  # noqa: ANN401 - typed by key
    return key.column.is_(None) if value is None else key.column == value  # type: ignore[no-any-return]  # Any column


def keyset_after(keys: Sequence[SortKey], values: Sequence[Any]) -> ColumnElement[bool]:
    """(k1 after v1) OR (k1 = v1 AND k2 after v2) OR ... — works for mixed directions."""
    clauses = []
    for i, key in enumerate(keys):
        equal_prefix = [_equal(keys[j], values[j]) for j in range(i)]
        clauses.append(and_(*equal_prefix, _after(key, values[i])))
    return or_(*clauses)


# --- cursors -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CursorScope:
    """What a cursor is bound to."""

    endpoint: str
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    sort: str
    filter_fingerprint: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _encode_value(key: SortKey, value: Any) -> Any:  # noqa: ANN401 - typed by key
    if value is None:
        return None
    if key.type is FieldType.DATETIME:
        return value.isoformat()
    if key.type is FieldType.UUID:
        return str(value)
    return value


def _decode_value(key: SortKey, value: Any) -> Any:  # noqa: ANN401 - typed by key
    if value is None:
        return None
    if key.type is FieldType.DATETIME:
        return datetime.fromisoformat(value)
    if key.type is FieldType.UUID:
        return uuid.UUID(value)
    if key.type is FieldType.INTEGER and type(value) is not int:
        raise ValueError
    if key.type in {FieldType.STRING, FieldType.ENUM} and not isinstance(value, str):
        raise ValueError
    return value


def _cursor_values(payload: str, expected: int) -> list[Any]:
    """The sort values inside a (signature-checked) cursor payload; ValueError if malformed."""
    body = json.loads(_unb64(payload))
    values = body["k"]
    if body.get("v") != _CURSOR_VERSION or not isinstance(values, list) or len(values) != expected:
        raise ValueError
    return values


class CursorCodec:
    """Signs and verifies cursors with one process-wide key."""

    def __init__(self, key: bytes) -> None:
        self._key = key

    @classmethod
    def from_settings(cls, settings: Settings) -> "CursorCodec":
        """Key from SUPPORTX_CURSOR_SECRET, else derived from the session secret, else random."""
        if settings.cursor_secret is not None:
            return cls(settings.cursor_secret.get_secret_value().encode())
        if settings.session_secret is not None:
            secret = settings.session_secret.get_secret_value().encode()
            return cls(hmac.new(secret, b"supportx-cursor-v1", hashlib.sha256).digest())
        return cls(secrets.token_bytes(32))

    def _sign(self, scope: CursorScope, payload: str) -> str:
        message = "\n".join(
            [
                payload,
                scope.endpoint,
                str(scope.tenant_id),
                str(scope.user_id or ""),
                scope.sort,
                scope.filter_fingerprint,
            ]
        )
        return _b64(hmac.new(self._key, message.encode(), hashlib.sha256).digest())

    def encode(self, scope: CursorScope, keys: Sequence[SortKey], row_values: Sequence[Any]) -> str:
        """Cursor for "after this row"."""
        body = {
            "v": _CURSOR_VERSION,
            "k": [_encode_value(k, v) for k, v in zip(keys, row_values, strict=True)],
        }
        payload = _b64(json.dumps(body, separators=(",", ":")).encode())
        return f"{payload}.{self._sign(scope, payload)}"

    def decode(self, cursor: str, scope: CursorScope, keys: Sequence[SortKey]) -> list[Any]:
        """Sort values from a cursor issued for exactly this scope; 400 invalid_cursor otherwise."""
        if len(cursor) > 2048 or cursor.count(".") != 1:  # noqa: PLR2004 - generous size bound
            raise BadRequest(code="invalid_cursor")
        payload, signature = cursor.split(".")
        if not hmac.compare_digest(signature, self._sign(scope, payload)):
            raise BadRequest(code="invalid_cursor")
        try:
            values = _cursor_values(payload, len(keys))
            return [_decode_value(k, v) for k, v in zip(keys, values, strict=True)]
        except (ValueError, KeyError, TypeError, binascii.Error) as exc:
            raise BadRequest(code="invalid_cursor") from exc


def get_cursor_codec(request: Request) -> CursorCodec:
    """The app's codec (built once at startup, see app.main)."""
    codec: CursorCodec | None = getattr(request.app.state, "cursor_codec", None)
    if codec is None:
        codec = CursorCodec.from_settings(request.app.state.settings)
        request.app.state.cursor_codec = codec
    return codec


# --- the list query ------------------------------------------------------------------------------


def _invalid(
    *, at: str, field_code: str, problem: str, params: dict[str, ParamValue] | None = None
) -> ValidationFailed:
    """422 `problem` with one field error `field_code` at query parameter `at`."""
    return ValidationFailed(
        code=problem,
        errors=[
            FieldError(
                field=at,
                code=field_code,
                message_key=f"errors.field.{field_code}",
                params=params or {},
            )
        ],
    )


TIME_ZONE_HEADER = "X-Time-Zone"


def request_zone(request: Request) -> tzinfo:
    """The requester's time zone (IANA name in X-Time-Zone, sent by our apps); UTC otherwise.

    Only used for calendar boundaries in filters, never for access decisions, so an unknown or
    missing value simply falls back to UTC.
    """
    name = request.headers.get(TIME_ZONE_HEADER, "").strip()
    if not name or len(name) > 64:  # noqa: PLR2004 - IANA names are short
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def _route_path(request: Request) -> str:
    """`GET /api/v1/users` (the route template, not the concrete URL)."""
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    return f"{request.method} {path}"


@dataclass(frozen=True)
class ListQuery:
    """Everything a list endpoint needs, validated: WHERE, ORDER BY, page size and position."""

    resource: ResourceFields
    where: ColumnElement[bool]
    sort: list[SortKey]
    limit: int
    after: list[Any] | None
    include_total: bool
    scope: CursorScope
    codec: CursorCodec


@dataclass(frozen=True)
class PageResult[RowT]:
    """Rows of one page plus the envelope fields."""

    rows: list[RowT]
    next_cursor: str | None
    has_more: bool
    estimated_total: int | None


FieldsFor = Callable[[AsyncSession], Awaitable[Mapping[str, FilterField]]]


def list_query(
    resource: ResourceFields,
    *,
    extra_parameters: frozenset[str] = frozenset(),
    fields_for: FieldsFor | None = None,
) -> Any:  # noqa: ANN401 - returns a FastAPI dependency
    """FastAPI dependency: `query: Annotated[ListQuery, Depends(list_query(RESOURCE))]`.

    `extra_parameters` are query parameters the endpoint reads itself (e.g. `view`): they are
    not simple filters, but they are part of the cursor's fingerprint, so a cursor of one view
    cannot be replayed on another. `fields_for` adds the tenant's own fields to the allowlist
    for this request (WP-026: custom fields as `custom.<key>`), read in the request's session.
    """

    async def dependency(  # noqa: PLR0913, PLR0917 - FastAPI reads parameters from the signature
        request: Request,
        tenant: Annotated[TenantContext, Depends(resolve_tenant)],
        session: TenantSession,
        codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
        filter_: Annotated[
            str | None,
            Query(
                alias="filter",
                description="Filter DSL as JSON (schema: FilterExpression).",
                max_length=DEFAULT_LIMITS.max_chars,
            ),
        ] = None,
        sort: Annotated[str | None, Query(description="e.g. -created_at,display_name")] = None,
        limit: Annotated[int | None, Query(description="Page size (default 50, max 200).")] = None,
        cursor: Annotated[
            str | None, Query(description="next_cursor of the previous page.")
        ] = None,
        include_total: Annotated[bool, Query(description="Also count matches (capped).")] = False,  # noqa: FBT002 - query flag
    ) -> ListQuery:
        settings: Settings = request.app.state.settings
        allowed = resource
        if fields_for is not None:
            allowed = replace(resource, fields={**resource.fields, **await fields_for(session)})
        size = settings.page_size_default if limit is None else limit
        if not 1 <= size <= settings.page_size_max:
            raise _invalid(
                at="limit",
                field_code="out_of_range",
                problem="invalid_page_size",
                params={"max": settings.page_size_max},
            )
        simple: dict[str, list[str]] = {}
        own: dict[str, list[str]] = {}
        for name, value in request.query_params.multi_items():
            if name in extra_parameters:
                own.setdefault(name, []).append(value)
            elif name not in RESERVED_PARAMETERS:
                simple.setdefault(name, []).append(value)
        # Calendar filters ("today", "this week") use the requester's time zone (WP-012).
        now = datetime.now(request_zone(request))
        tree = parse_filter_json(filter_) if filter_ is not None else None
        where = and_(
            compile_simple(simple, allowed),
            compile_filter(tree, allowed, now=now) if tree is not None else true(),
        )
        keys = parse_sort(sort, allowed)
        fingerprint = hashlib.sha256(
            json.dumps(
                [tree, sorted(simple.items()), sorted(own.items())]
                if own
                else [tree, sorted(simple.items())],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        scope = CursorScope(
            endpoint=_route_path(request),
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            sort=sort_signature(keys),
            filter_fingerprint=fingerprint,
        )
        after = codec.decode(cursor, scope, keys) if cursor else None
        return ListQuery(allowed, where, keys, size, after, include_total, scope, codec)

    return dependency


async def paginate(
    session: AsyncSession, statement: Select[Any], query: ListQuery
) -> PageResult[Any]:
    """Run `statement` (a SELECT of the resource's entity) as one page of `query`."""
    filtered = statement.where(query.where)
    page_statement = filtered
    if query.after is not None:
        page_statement = page_statement.where(keyset_after(query.sort, query.after))
    page_statement = page_statement.order_by(*order_by(query.sort)).limit(query.limit + 1)
    rows = list((await session.scalars(page_statement)).all())
    has_more = len(rows) > query.limit
    rows = rows[: query.limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        values = [getattr(last, _attribute(key)) for key in query.sort]
        next_cursor = query.codec.encode(query.scope, query.sort, values)
    total = None
    if query.include_total:
        capped = filtered.with_only_columns(query.resource.id_column).limit(TOTAL_CAP).subquery()
        total = int(await session.scalar(select(func.count()).select_from(capped)) or 0)
    return PageResult(rows, next_cursor, has_more, total)


def _attribute(key: SortKey) -> str:
    return str(key.column.key)
