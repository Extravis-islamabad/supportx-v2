"""Every create route is safe to retry (architecture.md §10; engineering-practices audit #19).

A create is a POST that answers 201. A phone or a flaky network retries after a lost answer, so
each must take an `Idempotency-Key` (the retry replays the first answer) or require If-Match (a
retry fails the version check instead of creating twice). A new create route without either
fails here, so the rule cannot drift.
"""

from collections.abc import Iterator

from fastapi.routing import APIRoute, iter_route_contexts

from app.main import create_app
from app.shared.api.concurrency import expected_version
from app.shared.api.idempotency import get_idempotency
from conftest import make_settings
from tests.test_route_permissions import _dependencies

# Create routes of other modules still to take the key, each with its owner (audit #19). The
# list only shrinks: a route that gains the key must leave it (the stale-entry test below).
KNOWN_GAPS: frozenset[str] = frozenset()


def _creates() -> Iterator[tuple[str, bool]]:
    """`POST path` of every 201 route, and whether it is safe to retry."""
    app = create_app(make_settings())
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if not isinstance(route, APIRoute) or not str(context.path).startswith("/api/v1"):
            continue
        if "POST" not in (context.methods or ()) or route.status_code != 201:
            continue
        calls = list(_dependencies(context.dependant))
        yield f"POST {context.path}", get_idempotency in calls or expected_version in calls


def test_every_create_route_takes_an_idempotency_key_or_if_match() -> None:
    unsafe = sorted({name for name, safe in _creates() if not safe} - KNOWN_GAPS)
    assert unsafe == [], f"create routes a retry would run twice: {unsafe}"


def test_the_known_gaps_are_still_gaps() -> None:
    """A route that took the key since must leave KNOWN_GAPS (the list only shrinks)."""
    unsafe = {name for name, safe in _creates() if not safe}
    assert unsafe >= KNOWN_GAPS, f"no longer gaps: {sorted(KNOWN_GAPS - unsafe)}"
