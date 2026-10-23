"""Sorting, cursors, ETags, deprecation, rate-limit decisions, OpenAPI. Pure, no I/O."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import Response
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.core.errors import BadRequest, PreconditionRequired, ValidationFailed
from app.shared.api.concurrency import etag_for, expected_version, not_modified, parse_etag
from app.shared.api.deprecation import Deprecation
from app.shared.api.idempotency import fingerprint, idempotency_key
from app.shared.api.listing import (
    CursorCodec,
    CursorScope,
    keyset_after,
    order_by,
    parse_sort,
    sort_signature,
)
from app.shared.api.ratelimit import Decision, SettingsPolicyProvider
from app.shared.api.tests.test_filters import THINGS
from conftest import make_settings

TENANT, OTHER_TENANT = uuid.uuid4(), uuid.uuid4()
USER = uuid.uuid4()


def scope(**overrides: Any) -> CursorScope:  # noqa: ANN401 - dataclass fields
    values: dict[str, Any] = {
        "endpoint": "GET /api/v1/things",
        "tenant_id": TENANT,
        "user_id": USER,
        "sort": "-created_at,id",
        "filter_fingerprint": "f" * 64,
        **overrides,
    }
    return CursorScope(**values)


# --- sorting -------------------------------------------------------------------------------------


def test_sort_always_ends_with_the_id() -> None:
    keys = parse_sort("-priority,title", THINGS)
    assert [(k.name, k.descending) for k in keys] == [
        ("priority", True),
        ("title", False),
        ("id", False),
    ]
    assert sort_signature(keys) == "-priority,title,id"
    assert [k.name for k in parse_sort(None, THINGS)] == ["created_at", "id"]  # the default
    terms = [str(t.compile(dialect=postgresql.dialect())) for t in order_by(keys)]  # type: ignore[no-untyped-call]  # SQLAlchemy factory
    assert terms == [
        "things.priority DESC NULLS FIRST",
        "things.title ASC NULLS LAST",
        "things.id ASC NULLS LAST",
    ]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("status", "unknown_sort_field"),  # filterable but not sortable
        ("-owner_id", "unknown_sort_field"),
        ("title;DROP TABLE x", "unknown_sort_field"),
        ("title,-title", "duplicate_sort_field"),
        ("title,priority,created_at,title", "invalid_sort"),
        (" , ", "invalid_sort"),
    ],
)
def test_bad_sorts(text: str, code: str) -> None:
    with pytest.raises(ValidationFailed) as caught:
        parse_sort(text, THINGS)
    assert caught.value.instance_code == "invalid_sort"
    assert caught.value.errors[0].code == code


def test_keyset_handles_mixed_directions_and_nulls() -> None:
    keys = parse_sort("-priority,title", THINGS)
    text = str(
        keyset_after(keys, [3, None, uuid.uuid4()]).compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    )
    assert "things.priority < " in text
    assert "things.priority = " in text
    assert "things.title IS NULL" in text
    assert "things.id > " in text


# --- cursors -------------------------------------------------------------------------------------


def test_cursor_round_trip_keeps_types() -> None:
    codec = CursorCodec(b"k" * 32)
    keys = parse_sort("-created_at", THINGS)
    when, last_id = datetime(2026, 10, 23, 9, 0, tzinfo=UTC), uuid.uuid4()
    cursor = codec.encode(scope(), keys, [when, last_id])
    assert codec.decode(cursor, scope(), keys) == [when, last_id]
    assert str(last_id) not in cursor  # opaque enough: not human-editable


@pytest.mark.parametrize(
    "other",
    [
        {"tenant_id": OTHER_TENANT},
        {"user_id": uuid.uuid4()},
        {"user_id": None},
        {"endpoint": "GET /api/v1/other"},
        {"sort": "created_at,id"},
        {"filter_fingerprint": "0" * 64},
    ],
)
def test_cursor_is_bound_to_its_scope(other: dict[str, Any]) -> None:
    codec = CursorCodec(b"k" * 32)
    keys = parse_sort("-created_at", THINGS)
    cursor = codec.encode(scope(), keys, [datetime.now(UTC), uuid.uuid4()])
    with pytest.raises(BadRequest) as caught:
        codec.decode(cursor, scope(**other), keys)
    assert caught.value.instance_code == "invalid_cursor"


def test_tampered_or_foreign_cursors_are_rejected() -> None:
    codec = CursorCodec(b"k" * 32)
    keys = parse_sort("-created_at", THINGS)
    good = codec.encode(scope(), keys, [datetime.now(UTC), uuid.uuid4()])
    payload, signature = good.split(".")
    forged_payload = CursorCodec(b"x" * 32).encode(scope(), keys, [datetime.now(UTC), uuid.uuid4()])
    for bad in (
        payload[:-2] + "AA." + signature,  # edited payload
        payload + "." + signature[:-2] + "AA",  # edited signature
        forged_payload,  # signed with another key
        "not-a-cursor",
        "a.b.c",
        "x" * 3000,
        "",
    ):
        with pytest.raises(BadRequest):
            codec.decode(bad, scope(), keys)


def test_cursor_key_comes_from_settings() -> None:
    explicit = CursorCodec.from_settings(make_settings(cursor_secret="c" * 40))
    derived = CursorCodec.from_settings(make_settings(session_secret="s" * 40))
    again = CursorCodec.from_settings(make_settings(session_secret="s" * 40))
    keys = parse_sort("title", THINGS)
    cursor = derived.encode(scope(), keys, ["b", uuid.uuid4()])
    assert again.decode(cursor, scope(), keys)[0] == "b"  # stable across processes
    with pytest.raises(BadRequest):
        explicit.decode(cursor, scope(), keys)


# --- ETags ---------------------------------------------------------------------------------------


def request_with(**headers: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (k.lower().replace("_", "-").encode(), v.encode()) for k, v in headers.items()
            ],
        }
    )


def test_etags() -> None:
    assert etag_for(7) == '"7"'
    assert parse_etag('"7"') == parse_etag('W/"7"') == 7
    for bad in ("7", '"abc"', '"-1"', '"7" "8"'):
        with pytest.raises(BadRequest):
            parse_etag(bad)


def test_if_match_is_required_and_strict() -> None:
    assert expected_version('"3"') == 3
    with pytest.raises(PreconditionRequired):
        expected_version(None)
    with pytest.raises(PreconditionRequired):
        expected_version("  ")
    for bad in ("*", '"3", "4"'):
        with pytest.raises(BadRequest):
            expected_version(bad)


def test_if_none_match_gives_304_only_for_the_current_version() -> None:
    hit = not_modified(request_with(if_none_match='"4"'), 4)
    assert isinstance(hit, Response)
    assert hit.status_code == 304
    assert hit.headers["etag"] == '"4"'
    assert not_modified(request_with(if_none_match='"3"'), 4) is None
    assert not_modified(request_with(), 4) is None


# --- deprecation, idempotency helpers, rate-limit decisions ---------------------------------------


def test_deprecation_headers_and_minimum_notice() -> None:
    deprecation = Deprecation(since=date(2026, 11, 1), sunset=date(2027, 11, 1), link="https://d/x")
    assert deprecation.headers() == {
        "Deprecation": "@1793491200",
        "Sunset": "Mon, 01 Nov 2027 00:00:00 GMT",
        "Link": '<https://d/x>; rel="deprecation"',
    }
    with pytest.raises(ValueError, match="12 months"):
        Deprecation(since=date(2026, 11, 1), sunset=date(2027, 1, 1))


def test_idempotency_fingerprint_ignores_key_order_but_not_values_or_route() -> None:
    assert fingerprint("POST /x", {"a": 1, "b": 2}) == fingerprint("POST /x", {"b": 2, "a": 1})
    assert fingerprint("POST /x", {"a": 1}) != fingerprint("POST /x", {"a": 2})
    assert fingerprint("POST /x", {"a": 1}) != fingerprint("POST /y", {"a": 1})


def test_idempotency_key_format() -> None:
    assert idempotency_key(None) is None
    assert idempotency_key("0b0f6f0e-9d4e-4a77-9b3e-1f2b3c4d5e6f") is not None
    for bad in ("", "has space", "x" * 256, "naïve"):
        with pytest.raises(BadRequest):
            idempotency_key(bad)


def test_rate_limit_headers() -> None:
    allowed = Decision(allowed=True, limit=10, remaining=7, reset_seconds=30, window_seconds=60)
    assert allowed.headers() == {
        "RateLimit-Limit": "10",
        "RateLimit-Remaining": "7",
        "RateLimit-Reset": "30",
        "RateLimit-Policy": "10;w=60",
    }
    refused = Decision(allowed=False, limit=10, remaining=0, reset_seconds=12, window_seconds=60)
    assert refused.headers()["Retry-After"] == "12"


async def test_rate_limit_policy_from_settings() -> None:
    provider = SettingsPolicyProvider(
        make_settings(
            rate_limits={"default": {"user": 100, "tenant": 1000}, "users": {"user": 5}},
            rate_limit_window_seconds=30,
        )
    )
    users = await provider.policy_for("users", TENANT)
    other = await provider.policy_for("tickets", TENANT)
    assert (users.user, users.tenant, users.window_seconds) == (5, 1000, 30)
    assert (other.user, other.tenant) == (100, 1000)


async def test_deprecated_route_sends_headers_and_is_marked_in_openapi() -> None:
    from fastapi import APIRouter, FastAPI  # noqa: PLC0415 - local app for this check
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    old = Deprecation(since=date(2026, 11, 1), sunset=date(2027, 11, 1))
    router = APIRouter()

    @router.get("/old", deprecated=True, dependencies=[old.dependency])
    async def old_endpoint() -> dict[str, str]:
        return {"ok": "yes"}

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get("/old")
    assert response.headers["deprecation"] == "@1793491200"
    assert response.headers["sunset"] == "Mon, 01 Nov 2027 00:00:00 GMT"
    assert app.openapi()["paths"]["/old"]["get"]["deprecated"] is True
