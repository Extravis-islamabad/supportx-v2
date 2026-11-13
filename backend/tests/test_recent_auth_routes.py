"""Every sensitive route asks for a recent confirmation, from one list (REQ-SEC-027; lane B A2).

RECENT_AUTH_ROUTES (app/core/recent_auth.py) is the one list: each route in it carries
RecentAuth, no other route does, and none is listed twice.
"""

from app.core.recent_auth import RECENT_AUTH_ROUTES, require_recent_auth
from app.main import create_app
from conftest import make_settings
from tests.test_route_permissions import _dependencies, api_routes


def _guarded() -> set[str]:
    app = create_app(make_settings())
    return {
        f"{method} {path}"
        for method, path, dependant, _endpoint in api_routes(app)
        if require_recent_auth in set(_dependencies(dependant))
    }


def test_the_list_names_no_route_twice() -> None:
    assert len(RECENT_AUTH_ROUTES) == len(set(RECENT_AUTH_ROUTES))


def test_every_listed_route_asks_for_a_recent_confirmation_and_no_other_does() -> None:
    guarded = _guarded()
    assert sorted(set(RECENT_AUTH_ROUTES) - guarded) == []  # listed, but not guarded
    assert sorted(guarded - set(RECENT_AUTH_ROUTES)) == []  # guarded, but not listed
