"""Every sensitive route asks for a recent confirmation, from one list (REQ-SEC-027; lane B A2).

RECENT_AUTH_ROUTES (app/core/recent_auth.py) is the one list: each route in it carries
RecentAuth, no other route does, and none is listed twice. A route guarded for some changes only
(CONDITIONAL_RECENT_AUTH) calls require_recent_auth in its endpoint instead.
"""

import inspect

from app.core.recent_auth import (
    CONDITIONAL_RECENT_AUTH,
    RECENT_AUTH_ROUTES,
    require_recent_auth,
)
from app.main import create_app
from conftest import make_settings
from tooling.route_permissions import api_routes, route_dependencies


def _guarded() -> set[str]:
    app = create_app(make_settings())
    return {
        f"{method} {path}"
        for method, path, dependant, _endpoint in api_routes(app)
        if require_recent_auth in set(route_dependencies(dependant))
    }


def test_the_list_names_no_route_twice() -> None:
    assert len(RECENT_AUTH_ROUTES) == len(set(RECENT_AUTH_ROUTES))


def test_every_listed_route_asks_for_a_recent_confirmation_and_no_other_does() -> None:
    guarded = _guarded()
    assert sorted(set(RECENT_AUTH_ROUTES) - guarded) == []  # listed, but not guarded
    assert sorted(guarded - set(RECENT_AUTH_ROUTES)) == []  # guarded, but not listed


def test_each_conditionally_guarded_route_asks_in_its_endpoint() -> None:
    app = create_app(make_settings())
    endpoints = {f"{method} {path}": endpoint for method, path, _d, endpoint in api_routes(app)}
    for route in CONDITIONAL_RECENT_AUTH:
        assert route in endpoints, f"{route}: no such route"
        assert route not in RECENT_AUTH_ROUTES  # one way or the other, never both
        assert "require_recent_auth(" in inspect.getsource(endpoints[route]), route
